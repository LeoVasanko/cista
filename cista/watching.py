import asyncio
import shutil
import sys
import threading
import time
from contextlib import suppress
from os import stat_result
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG

import msgspec

# Debug instrumentation
def _dbg(msg):
    print(f"[watch] {time.perf_counter():.3f} {msg}", file=sys.stderr, flush=True)
from natsort import humansorted, natsort_keygen, ns
from sanic.log import logger

from cista import config
from cista.fileio import fuid
from cista.protocol import FileEntry, Space, UpdDel, UpdIns, UpdKeep

pubsub = {}
sortkey = natsort_keygen(alg=ns.LOCALE)


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self._space = Space(0, 0, 0, 0)
        self.root: list[FileEntry] = []

    @property
    def space(self):
        with self.lock:
            return self._space

    @space.setter
    def space(self, space):
        with self.lock:
            self._space = space


def treeiter(rootmod):
    relpath = PurePosixPath()
    for i, entry in enumerate(rootmod):
        if entry.level > 0:
            relpath = PurePosixPath(*relpath.parts[: entry.level - 1]) / entry.name
        yield i, relpath, entry


def treeget(rootmod: list[FileEntry], path: PurePosixPath):
    t0 = time.perf_counter()
    begin = None
    ret = []

    for i, relpath, entry in treeiter(rootmod):
        if begin is None:
            if relpath == path:
                begin = i
                ret.append(entry)
            continue
        if entry.level <= len(path.parts):
            break
        ret.append(entry)

    dur = time.perf_counter() - t0
    if dur > 0.01:
        _dbg(f"treeget({path}) scanned {len(rootmod)} entries in {dur*1000:.1f}ms, found {len(ret)} items")
    return begin, ret


def treeinspos(rootmod: list[FileEntry], relpath: PurePosixPath, relfile: int):
    # Find the first entry greater than the new one
    # precondition: the new entry doesn't exist
    t0 = time.perf_counter()
    isfile = 0
    level = 0
    i = 0
    iter_count = 0
    for i, rel, entry in treeiter(rootmod):
        iter_count += 1
        if entry.level > level:
            # We haven't found item at level, skip subdirectories
            continue
        if entry.level < level:
            # We have passed the level, so the new item is the first
            return i
        if level == 0:
            # root
            level += 1
            continue

        ename = rel.parts[level - 1]
        name = relpath.parts[level - 1]

        esort = sortkey(ename)
        nsort = sortkey(name)
        # Non-leaf are always folders, only use relfile at leaf
        isfile = relfile if len(relpath.parts) == level else 0

        # First compare by isfile, then by sorting order and if that too matches then case sensitive
        cmp = (
            entry.isfile - isfile
            or (esort > nsort) - (esort < nsort)
            or (ename > name) - (ename < name)
        )

        if cmp > 0:
            return i
        if cmp < 0:
            continue

        level += 1
        if level > len(relpath.parts):
            logger.error(
                f"insertpos level overflow: relpath={relpath}, i={i}, entry.name={entry.name}, entry.level={entry.level}, level={level}"
            )
            break
    else:
        i += 1

    dur = time.perf_counter() - t0
    if dur > 0.01:
        _dbg(f"treeinspos({relpath}) iterated {iter_count}/{len(rootmod)} entries in {dur*1000:.1f}ms -> pos {i}")
    return i


state = State()
rootpath: Path = None  # type: ignore
quit = threading.Event()

## Filesystem scanning


def walk(rel: PurePosixPath, stat: stat_result | None = None) -> list[FileEntry]:
    t0 = time.perf_counter()
    path = rootpath / rel
    ret = []
    try:
        st = stat or path.stat()
        isfile = int(not S_ISDIR(st.st_mode))
        entry = FileEntry(
            level=len(rel.parts),
            name=rel.name,
            key=fuid(st),
            mtime=int(st.st_mtime),
            size=st.st_size if isfile else 0,
            isfile=isfile,
        )
        if isfile:
            return [entry]
        # Walk all entries of the directory
        ret: list[FileEntry] = [...]  # type: ignore
        li = []
        for f in path.iterdir():
            if quit.is_set():
                raise SystemExit("quit")
            if f.name.startswith("."):
                continue  # No dotfiles
            with suppress(FileNotFoundError):
                s = f.lstat()
                isfile = S_ISREG(s.st_mode)
                isdir = S_ISDIR(s.st_mode)
                if not isfile and not isdir:
                    continue
                li.append((int(isfile), f.name, s))
        # Build the tree as a list of FileEntries
        for [_, name, s] in humansorted(li):
            sub = walk(rel / name, stat=s)
            child = sub[0]
            entry = FileEntry(
                level=entry.level,
                name=entry.name,
                key=entry.key,
                size=entry.size + child.size,
                mtime=max(entry.mtime, child.mtime),
                isfile=entry.isfile,
            )
            ret.extend(sub)
    except FileNotFoundError:
        pass  # Things may be rapidly in motion
    except OSError as e:
        if e.errno == 13:  # Permission denied
            pass
        logger.error(f"Watching {path=}: {e!r}")
    if ret:
        ret[0] = entry
    dur = time.perf_counter() - t0
    if dur > 0.05:
        _dbg(f"walk({rel}) returned {len(ret)} entries in {dur*1000:.1f}ms")
    return ret


def update_root(loop):
    """Full filesystem scan"""
    t0 = time.perf_counter()
    old = state.root
    new = walk(PurePosixPath())
    t_walk = time.perf_counter()
    if old != new:
        update = format_update(old, new)
        t_format = time.perf_counter()
        with state.lock:
            broadcast(update, loop)
            state.root = new
        t_done = time.perf_counter()
        _dbg(f"update_root: walk={t_walk-t0:.3f}s format={t_format-t_walk:.3f}s broadcast={t_done-t_format:.3f}s total={t_done-t0:.3f}s ({len(new)} entries)")


def update_path(rootmod: list[FileEntry], relpath: PurePosixPath, loop):
    """Called on FS updates, check the filesystem and broadcast any changes."""
    t0 = time.perf_counter()
    new = walk(relpath)
    t_walk = time.perf_counter()
    obegin, old = treeget(rootmod, relpath)
    t_get = time.perf_counter()

    if old == new:
        dur = time.perf_counter() - t0
        if dur > 0.01:
            _dbg(f"update_path({relpath}) no change, walk={t_walk-t0:.3f}s get={t_get-t_walk:.3f}s")
        return

    if obegin is not None:
        del rootmod[obegin : obegin + len(old)]
    t_del = time.perf_counter()

    if new:
        i = treeinspos(rootmod, relpath, new[0].isfile)
        t_inspos = time.perf_counter()
        rootmod[i:i] = new
        t_ins = time.perf_counter()
        _dbg(f"update_path({relpath}) walk={t_walk-t0:.3f}s get={t_get-t_walk:.3f}s del={t_del-t_get:.3f}s inspos={t_inspos-t_del:.3f}s ins={t_ins-t_inspos:.3f}s total={t_ins-t0:.3f}s (old={len(old)} new={len(new)} tree={len(rootmod)})")
    else:
        _dbg(f"update_path({relpath}) DELETED walk={t_walk-t0:.3f}s get={t_get-t_walk:.3f}s del={t_del-t_get:.3f}s (old={len(old)})")


def update_space(loop):
    """Called periodically to update the disk usage."""
    du = shutil.disk_usage(rootpath)
    space = Space(*du, storage=state.root[0].size)
    # Update only on difference above 1 MB
    tol = 10**6
    old = msgspec.structs.astuple(state.space)
    new = msgspec.structs.astuple(space)
    if any(abs(o - n) > tol for o, n in zip(old, new, strict=True)):
        state.space = space
        broadcast(format_space(space), loop)


## Messaging


def format_update(old, new):
    t0 = time.perf_counter()
    # Make keep/del/insert diff until one of the lists ends
    oidx, nidx = 0, 0
    oremain, nremain = set(old), set(new)
    update = []
    keep_count = 0
    iteration_count = 0
    # Precompute index maps to allow deterministic tie-breaking when both
    # candidates exist in both sequences but are not equal (rename/move cases)
    old_pos = {e: i for i, e in enumerate(old)}
    new_pos = {e: i for i, e in enumerate(new)}
    t_setup = time.perf_counter()

    while oidx < len(old) and nidx < len(new):
        iteration_count += 1

        # Emergency brake for potential infinite loops
        if iteration_count > 50000:
            logger.error(
                f"format_update potential infinite loop! iteration={iteration_count}, oidx={oidx}, nidx={nidx}"
            )
            raise Exception(
                f"format_update infinite loop detected at iteration {iteration_count}"
            )

        modified = False
        # Matching entries are kept
        if old[oidx] == new[nidx]:
            entry = old[oidx]
            oremain.discard(entry)
            nremain.discard(entry)
            keep_count += 1
            oidx += 1
            nidx += 1
            continue

        if keep_count > 0:
            modified = True
            update.append(UpdKeep(keep_count))
            keep_count = 0

        # Items only in old are deleted
        del_count = 0
        while oidx < len(old) and old[oidx] not in nremain:
            oremain.remove(old[oidx])
            del_count += 1
            oidx += 1
        if del_count:
            update.append(UpdDel(del_count))
            continue

        # Items only in new are inserted
        insert_items = []
        while nidx < len(new) and new[nidx] not in oremain:
            entry = new[nidx]
            nremain.discard(entry)
            insert_items.append(entry)
            nidx += 1
        if insert_items:
            modified = True
            update.append(UpdIns(insert_items))

        if not modified:
            # Tie-break: both items exist in both lists but don't match here.
            # Decide whether to delete old[oidx] first or insert new[nidx] first
            # based on which alignment is closer.
            if oidx >= len(old) or nidx >= len(new):
                break
            cur_old = old[oidx]
            cur_new = new[nidx]

            pos_old_in_new = new_pos.get(cur_old)
            pos_new_in_old = old_pos.get(cur_new)

            # Default distances if not present (shouldn't happen if in remain sets)
            dist_del = (pos_old_in_new - nidx) if pos_old_in_new is not None else 1
            dist_ins = (pos_new_in_old - oidx) if pos_new_in_old is not None else 1

            # Prefer the operation with smaller forward distance; tie => delete
            if dist_del <= dist_ins:
                # Delete current old item
                oremain.discard(cur_old)
                update.append(UpdDel(1))
                oidx += 1
            else:
                # Insert current new item
                nremain.discard(cur_new)
                update.append(UpdIns([cur_new]))
                nidx += 1

    # Diff any remaining
    if keep_count > 0:
        update.append(UpdKeep(keep_count))
    if oremain:
        update.append(UpdDel(len(oremain)))
    elif nremain:
        update.append(UpdIns(new[nidx:]))

    t_diff = time.perf_counter()
    result = msgspec.json.encode({"update": update}).decode()
    t_encode = time.perf_counter()
    _dbg(f"format_update: setup={t_setup-t0:.3f}s diff={t_diff-t_setup:.3f}s ({iteration_count} iters) encode={t_encode-t_diff:.3f}s total={t_encode-t0:.3f}s (old={len(old)} new={len(new)} ops={len(update)} msg={len(result)}B)")
    return result


def format_space(usage):
    return msgspec.json.encode({"space": usage}).decode()


def format_root(root):
    return msgspec.json.encode({"root": root}).decode()


def broadcast(msg, loop):
    t0 = time.perf_counter()
    fut = asyncio.run_coroutine_threadsafe(abroadcast(msg), loop)
    t_scheduled = time.perf_counter()
    result = fut.result()
    t_done = time.perf_counter()
    if t_done - t0 > 0.01:
        _dbg(f"broadcast: schedule={t_scheduled-t0:.3f}s wait={t_done-t_scheduled:.3f}s total={t_done-t0:.3f}s ({len(msg)}B to {result} clients)")
    return result


async def abroadcast(msg):
    t0 = time.perf_counter()
    client_count = 0
    try:
        for queue in pubsub.values():
            queue.put_nowait(msg)
            client_count += 1
    except Exception:
        # Log because asyncio would silently eat the error
        logger.exception("Broadcast error")
    dur = time.perf_counter() - t0
    if dur > 0.001:
        _dbg(f"abroadcast: {client_count} clients in {dur*1000:.2f}ms")
    return client_count


## Watcher thread


def watcher_inotify(loop):
    """Inotify watcher thread (Linux only)"""
    import inotify.adapters

    modified_flags = (
        "IN_CREATE",
        "IN_DELETE",
        "IN_DELETE_SELF",
        "IN_MODIFY",
        "IN_MOVE_SELF",
        "IN_MOVED_FROM",
        "IN_MOVED_TO",
    )
    while not quit.is_set():
        i = inotify.adapters.InotifyTree(rootpath.as_posix())
        # Initialize the tree from filesystem
        update_root(loop)
        trefresh = time.monotonic() + 300.0
        tspace = time.monotonic() + 5.0
        # Watch for changes (frequent wakeups needed for quiting)
        while not quit.is_set():
            t = time.monotonic()
            # The watching is not entirely reliable, so do a full refresh every 30 seconds
            if t >= trefresh:
                break
            # Disk usage update
            if t >= tspace:
                tspace = time.monotonic() + 5.0
                update_space(loop)
            # Inotify events, update the tree
            dirty = False
            t_batch_start = time.perf_counter()
            rootmod = state.root[:]
            t_copy = time.perf_counter()
            event_count = 0
            interesting_count = 0
            paths_updated = []
            for event in i.event_gen(yield_nones=False, timeout_s=0.1):
                assert event
                event_count += 1
                if quit.is_set():
                    return
                interesting = any(f in modified_flags for f in event[1])
                if interesting:
                    interesting_count += 1
                    # Update modified path
                    path = PurePosixPath(event[2]) / event[3]
                    try:
                        rel_path = path.relative_to(rootpath)
                        paths_updated.append(str(rel_path))
                        update_path(rootmod, rel_path, loop)
                    except Exception as e:
                        logger.error(
                            f"Error processing inotify event for path {path}: {e}"
                        )
                        raise
                    if not dirty:
                        t = time.monotonic()
                        dirty = True
                # Wait a maximum of 0.2s to push the updates
                if dirty and time.monotonic() >= t + 0.2:
                    break
            t_events_done = time.perf_counter()
            if event_count > 0:
                _dbg(f"inotify batch: {event_count} events, {interesting_count} interesting, copy={t_copy-t_batch_start:.3f}s events={t_events_done-t_copy:.3f}s paths={paths_updated[:5]}{'...' if len(paths_updated) > 5 else ''}")
            if dirty and state.root != rootmod:
                t_diff_start = time.perf_counter()
                try:
                    update = format_update(state.root, rootmod)
                    t_format_done = time.perf_counter()
                    with state.lock:
                        broadcast(update, loop)
                        state.root = rootmod
                    t_broadcast_done = time.perf_counter()
                    _dbg(f"inotify->broadcast TOTAL: batch_to_format={t_diff_start-t_batch_start:.3f}s format={t_format_done-t_diff_start:.3f}s broadcast={t_broadcast_done-t_format_done:.3f}s TOTAL={t_broadcast_done-t_batch_start:.3f}s")
                except Exception:
                    logger.exception(
                        "format_update failed; falling back to full rescan"
                    )
                    # Fallback: full rescan and try diff again; last resort send full root
                    try:
                        fresh = walk(PurePosixPath())
                        try:
                            update = format_update(state.root, fresh)
                            with state.lock:
                                broadcast(update, loop)
                                state.root = fresh
                        except Exception:
                            logger.exception(
                                "Fallback diff failed; sending full root snapshot"
                            )
                            with state.lock:
                                broadcast(format_root(fresh), loop)
                                state.root = fresh
                    except Exception:
                        logger.exception(
                            "Full rescan failed; dropping this batch of updates"
                        )

        del i  # Free the inotify object


def watcher_poll(loop):
    """Polling version of the watcher thread."""
    while not quit.is_set():
        t0 = time.perf_counter()
        update_root(loop)
        update_space(loop)
        dur = time.perf_counter() - t0
        if dur > 1.0:
            logger.debug(f"Reading the full file list took {dur:.1f}s")
        quit.wait(0.1 + 8 * dur)


def start(app):
    global rootpath
    config.load_config()
    rootpath = config.config.path
    use_inotify = sys.platform == "linux"
    app.ctx.watcher = threading.Thread(
        target=watcher_inotify if use_inotify else watcher_poll,
        args=[app.loop],
        # Descriptive name for system monitoring
        name=f"cista-watcher {rootpath}",
    )
    app.ctx.watcher.start()


def stop(app):
    quit.set()
    app.ctx.watcher.join()
