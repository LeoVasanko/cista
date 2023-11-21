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
    return begin, ret


def treeinspos(rootmod: list[FileEntry], relpath: PurePosixPath, relfile: int):
    # Find the first entry greater than the new one
    # precondition: the new entry doesn't exist
    isfile = 0
    level = 0
    i = 0
    for i, rel, entry in treeiter(rootmod):
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
            print("ERROR: insertpos", relpath, i, entry.name, entry.level, level)
            break
    else:
        i += 1
    return i


state = State()
rootpath: Path = None  # type: ignore
quit = threading.Event()

## Filesystem scanning


def walk(rel: PurePosixPath, stat: stat_result | None = None) -> list[FileEntry]:
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
    return ret


def update_root(loop):
    """Full filesystem scan"""
    old = state.root
    new = walk(PurePosixPath())
    if old != new:
        update = format_update(old, new)
        with state.lock:
            broadcast(update, loop)
            state.root = new


def update_path(rootmod: list[FileEntry], relpath: PurePosixPath, loop):
    """Called on FS updates, check the filesystem and broadcast any changes."""
    new = walk(relpath)
    obegin, old = treeget(rootmod, relpath)
    if old == new:
        logger.debug(
            f"Watch: Event without changes needed {relpath}"
            if old
            else f"Watch: Event with old and new missing: {relpath}"
        )
        return
    if obegin is not None:
        del rootmod[obegin : obegin + len(old)]
    if new:
        logger.debug(f"Watch: Update {relpath}" if old else f"Watch: Created {relpath}")
        i = treeinspos(rootmod, relpath, new[0].isfile)
        rootmod[i:i] = new
    else:
        logger.debug(f"Watch: Removed {relpath}")


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
    # Make keep/del/insert diff until one of the lists ends
    oidx, nidx = 0, 0
    oremain, nremain = set(old), set(new)
    update = []
    keep_count = 0
    while oidx < len(old) and nidx < len(new):
        modified = False
        # Matching entries are kept
        if old[oidx] == new[nidx]:
            entry = old[oidx]
            oremain.remove(entry)
            nremain.remove(entry)
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
            nremain.remove(entry)
            insert_items.append(entry)
            nidx += 1
        if insert_items:
            modified = True
            update.append(UpdIns(insert_items))

        if not modified:
            raise Exception(
                f"Infinite loop in diff {nidx=} {oidx=} {len(old)=} {len(new)=}"
            )

    # Diff any remaining
    if keep_count > 0:
        update.append(UpdKeep(keep_count))
    if oremain:
        update.append(UpdDel(len(oremain)))
    elif nremain:
        update.append(UpdIns(new[nidx:]))

    return msgspec.json.encode({"update": update}).decode()


def format_space(usage):
    return msgspec.json.encode({"space": usage}).decode()


def format_root(root):
    return msgspec.json.encode({"root": root}).decode()


def broadcast(msg, loop):
    return asyncio.run_coroutine_threadsafe(abroadcast(msg), loop).result()


async def abroadcast(msg):
    try:
        for queue in pubsub.values():
            queue.put_nowait(msg)
    except Exception:
        # Log because asyncio would silently eat the error
        logger.exception("Broadcast error")


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
        t0 = time.perf_counter()
        update_root(loop)
        t1 = time.perf_counter()
        logger.debug(f"Root update took {t1 - t0:.1f}s")
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
            rootmod = state.root[:]
            for event in i.event_gen(yield_nones=False, timeout_s=0.1):
                assert event
                if quit.is_set():
                    return
                interesting = any(f in modified_flags for f in event[1])
                if event[2] == rootpath.as_posix() and event[3] == "zzz":
                    logger.debug(f"Watch: {interesting=} {event=}")
                if interesting:
                    # Update modified path
                    t0 = time.perf_counter()
                    path = PurePosixPath(event[2]) / event[3]
                    update_path(rootmod, path.relative_to(rootpath), loop)
                    t1 = time.perf_counter()
                    logger.debug(f"Watch: Update {event[3]} took {t1 - t0:.1f}s")
                    if not dirty:
                        t = time.monotonic()
                        dirty = True
                # Wait a maximum of 0.5s to push the updates
                if dirty and time.monotonic() >= t + 0.5:
                    break
            if dirty and state.root != rootmod:
                t0 = time.perf_counter()
                update = format_update(state.root, rootmod)
                t1 = time.perf_counter()
                with state.lock:
                    broadcast(update, loop)
                    state.root = rootmod
                t2 = time.perf_counter()
                logger.debug(
                    f"Format update took {t1 - t0:.1f}s, broadcast {t2 - t1:.1f}s"
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


async def start(app, loop):
    global rootpath
    config.load_config()
    rootpath = config.config.path
    use_inotify = sys.platform == "linux"
    app.ctx.watcher = threading.Thread(
        target=watcher_inotify if use_inotify else watcher_poll,
        args=[loop],
        # Descriptive name for system monitoring
        name=f"cista-watcher {rootpath}",
    )
    app.ctx.watcher.start()


async def stop(app, loop):
    quit.set()
    app.ctx.watcher.join()
