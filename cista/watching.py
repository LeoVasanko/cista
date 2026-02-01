import asyncio
import queue
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
            logger.error(
                f"insertpos level overflow: relpath={relpath}, i={i}, entry.name={entry.name}, entry.level={entry.level}, level={level}"
            )
            break
    else:
        i += 1

    return i


state = State()
rootpath: Path = None  # type: ignore
quit = threading.Event()

# Thread-safe queue for signaling path updates from websockets
_update_queue: queue.Queue[PurePosixPath] = queue.Queue()


def notify_change(*paths: PurePosixPath | str):
    """Signal that paths have changed. Called from control/upload websockets."""
    for path in paths:
        if isinstance(path, str):
            path = PurePosixPath(path)
        # Convert absolute paths to relative (strip leading /)
        if path.is_absolute():
            path = (
                PurePosixPath(*path.parts[1:])
                if len(path.parts) > 1
                else PurePosixPath()
            )
        # Skip root paths (empty, '.') to avoid full tree walks
        if not path.parts or path.parts == (".",):
            continue
        _update_queue.put(path)


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
        return

    if obegin is not None:
        del rootmod[obegin : obegin + len(old)]

    if new:
        i = treeinspos(rootmod, relpath, new[0].isfile)
        rootmod[i:i] = new


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
    iteration_count = 0
    # Precompute index maps to allow deterministic tie-breaking when both
    # candidates exist in both sequences but are not equal (rename/move cases)
    old_pos = {e: i for i, e in enumerate(old)}
    new_pos = {e: i for i, e in enumerate(new)}

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

    return msgspec.json.encode({"update": update}).decode()


def format_space(usage):
    return msgspec.json.encode({"space": usage}).decode()


def format_root(root):
    return msgspec.json.encode({"root": root}).decode()


def broadcast(msg, loop):
    fut = asyncio.run_coroutine_threadsafe(abroadcast(msg), loop)
    return fut.result()


async def abroadcast(msg):
    client_count = 0
    try:
        for queue in pubsub.values():
            queue.put_nowait(msg)
            client_count += 1
    except Exception:
        # Log because asyncio would silently eat the error
        logger.exception("Broadcast error")
    return client_count


## Watcher thread


class PathIndex:
    """O(1) path lookup index for the flat FileEntry tree."""

    def __init__(self, root: list[FileEntry]):
        self.root = root
        self._index: dict[PurePosixPath, tuple[int, int]] = {}
        self._rebuild()

    def _rebuild(self):
        """Build path -> (start_idx, count) mapping in single O(n) pass."""
        index: dict[PurePosixPath, tuple[int, int]] = {}
        path_stack: list[tuple[PurePosixPath, int]] = []  # (path, start_idx)

        for i, entry in enumerate(self.root):
            # Pop completed paths from stack
            while path_stack and entry.level <= len(path_stack[-1][0].parts):
                completed_path, start_idx = path_stack.pop()
                index[completed_path] = (start_idx, i - start_idx)

            # Build current path
            if entry.level == 0:
                current_path = PurePosixPath()
            else:
                parent = path_stack[-1][0] if path_stack else PurePosixPath()
                current_path = parent / entry.name

            path_stack.append((current_path, i))

        # Close remaining paths
        for path, start_idx in path_stack:
            index[path] = (start_idx, len(self.root) - start_idx)

        self._index = index

    def get(self, path: PurePosixPath) -> tuple[int | None, list[FileEntry]]:
        """O(1) lookup: returns (start_idx, entries) or (None, [])."""
        if path not in self._index:
            return None, []
        start, count = self._index[path]
        return start, self.root[start : start + count]

    def find_insert_pos(self, path: PurePosixPath, isfile: int) -> int:
        """Find insertion position using index + binary search."""
        if not path.parts:
            return 0

        parent = path.parent
        name = path.name

        # Find parent's range
        if parent == PurePosixPath():
            # Insert at root level - scan root's direct children
            start, count = 0, len(self.root)
            target_level = 1
        elif parent in self._index:
            start, count = self._index[parent]
            start += 1  # Skip parent entry itself
            count -= 1
            target_level = len(parent.parts) + 1
        else:
            # Parent doesn't exist, shouldn't happen
            return len(self.root)

        # Binary search among direct children at target_level
        # Collect children indices first
        children = []
        i = start
        end = start + count
        while i < end:
            entry = self.root[i]
            if entry.level == target_level:
                children.append(i)
            i += 1

        if not children:
            return start

        # Binary search for insertion point
        nsort = sortkey(name)
        lo, hi = 0, len(children)
        while lo < hi:
            mid = (lo + hi) // 2
            idx = children[mid]
            entry = self.root[idx]
            ename = entry.name
            esort = sortkey(ename)
            # Compare: isfile, then sort key, then case-sensitive
            cmp = (
                entry.isfile - isfile
                or (esort > nsort) - (esort < nsort)
                or (ename > name) - (ename < name)
            )
            if cmp < 0:
                lo = mid + 1
            else:
                hi = mid

        if lo < len(children):
            return children[lo]
        elif children:
            # Insert after last child's subtree
            last_idx = children[-1]
            last_entry = self.root[last_idx]
            if last_entry.isfile:
                return last_idx + 1
            # Find end of last child's subtree
            last_path = parent / last_entry.name
            if last_path in self._index:
                s, c = self._index[last_path]
                return s + c
            return last_idx + 1
        return start

    def apply_update(
        self, path: PurePosixPath, new_entries: list[FileEntry]
    ) -> list[FileEntry]:
        """Apply an update and return the new root. Rebuilds index."""
        start, old_entries = self.get(path)

        if old_entries == new_entries:
            return self.root

        new_root = self.root[:]

        if start is not None:
            del new_root[start : start + len(old_entries)]

        if new_entries:
            # Rebuild index on modified list to find insert pos
            self.root = new_root
            self._rebuild()
            insert_pos = self.find_insert_pos(path, new_entries[0].isfile)
            new_root[insert_pos:insert_pos] = new_entries

        self.root = new_root
        self._rebuild()
        return new_root


def collapse_paths(paths: set[PurePosixPath]) -> set[PurePosixPath]:
    """Remove child paths if parent is in set."""
    if not paths:
        return paths
    # Filter out root paths (empty or '.') which would cause full tree walks
    paths = {p for p in paths if p.parts and p.parts != (".",)}
    if not paths:
        return set()
    # Sort by depth (fewest parts first)
    sorted_paths = sorted(paths, key=lambda p: len(p.parts))
    result = set()
    for path in sorted_paths:
        # Check if any ancestor is already in result
        is_child = False
        for i in range(len(path.parts)):
            ancestor = PurePosixPath(*path.parts[:i]) if i > 0 else PurePosixPath()
            if ancestor in result:
                is_child = True
                break
        if not is_child:
            result.add(path)
    return result


# Debounce settings
DEBOUNCE_DELAY = 0.01  # Wait 10ms after last event
DEBOUNCE_MAX = 0.1  # But no more than 100ms total


def watcher(loop):
    """Unified watcher thread handling inotify, websocket signals, and periodic scans."""
    use_inotify = sys.platform == "linux"
    inotify_tree = None
    modified_flags = frozenset()

    if use_inotify:
        import inotify.adapters

        modified_flags = frozenset(
            (
                "IN_CREATE",
                "IN_DELETE",
                "IN_DELETE_SELF",
                "IN_MODIFY",
                "IN_MOVE_SELF",
                "IN_MOVED_FROM",
                "IN_MOVED_TO",
            )
        )

    while not quit.is_set():
        if use_inotify:
            import inotify.adapters

            inotify_tree = inotify.adapters.InotifyTree(rootpath.as_posix())

        # Initialize the tree from filesystem
        update_root(loop)
        path_index = PathIndex(state.root[:])

        trefresh = time.monotonic() + 300.0
        tspace = time.monotonic() + 5.0

        # Pending changes: path -> {"ws": count, "inotify": count}
        dirty_paths: dict[PurePosixPath, dict[str, int]] = {}
        first_event_time: float | None = None
        last_event_time: float | None = None

        def add_dirty(path: PurePosixPath, source: str) -> bool:
            """Add path to dirty set. Returns True if added, False if redundant."""
            nonlocal first_event_time, last_event_time
            # Check if already covered by an existing dirty path
            for existing in dirty_paths:
                if path == existing or (
                    len(path.parts) > len(existing.parts)
                    and path.parts[: len(existing.parts)] == existing.parts
                ):
                    # Count the event even if skipped
                    dirty_paths[existing][source] = (
                        dirty_paths[existing].get(source, 0) + 1
                    )
                    return False
            # Remove any paths that would be covered by this new one
            covered = {
                p
                for p in dirty_paths
                if len(p.parts) > len(path.parts)
                and p.parts[: len(path.parts)] == path.parts
            }
            # Aggregate counts from covered paths
            counts: dict[str, int] = {source: 1}
            for p in covered:
                for s, c in dirty_paths[p].items():
                    counts[s] = counts.get(s, 0) + c
                del dirty_paths[p]
            dirty_paths[path] = counts
            now = time.monotonic()
            if first_event_time is None:
                first_event_time = now
            last_event_time = now
            return True

        while not quit.is_set():
            now = time.monotonic()

            # Full refresh every 300s
            if now >= trefresh:
                break

            # Disk usage update every 5s
            if now >= tspace:
                tspace = now + 5.0
                update_space(loop)

            # Check if we should flush pending changes
            should_flush = False
            if dirty_paths:
                time_since_last = now - last_event_time if last_event_time else 0
                time_since_first = now - first_event_time if first_event_time else 0
                if (
                    time_since_last >= DEBOUNCE_DELAY
                    or time_since_first >= DEBOUNCE_MAX
                ):
                    should_flush = True

            if should_flush:
                paths_to_process = dirty_paths.copy()
                dirty_paths.clear()
                first_event_time = None
                last_event_time = None

                # Collapse paths (remove children if parent present)
                collapsed = collapse_paths(set(paths_to_process.keys()))

                # Process each collapsed path
                new_root = path_index.root
                for path in collapsed:
                    new_entries = walk(path)
                    new_root = path_index.apply_update(path, new_entries)

                # Broadcast if changed
                if new_root != state.root:
                    try:
                        update_msg = format_update(state.root, new_root)
                        with state.lock:
                            broadcast(update_msg, loop)
                            state.root = new_root
                    except Exception:
                        logger.exception("format_update failed; full rescan")
                        try:
                            fresh = walk(PurePosixPath())
                            path_index = PathIndex(fresh)
                            update_msg = format_update(state.root, fresh)
                            with state.lock:
                                broadcast(update_msg, loop)
                                state.root = fresh
                        except Exception:
                            logger.exception("Fallback failed; sending full root")
                            with state.lock:
                                broadcast(format_root(fresh), loop)
                                state.root = fresh

            # Collect events from websocket signals (non-blocking)
            try:
                while True:
                    path = _update_queue.get_nowait()
                    add_dirty(path, "ws")
            except queue.Empty:
                pass

            # Collect inotify events if available (short timeout for responsiveness)
            if inotify_tree:
                for event in inotify_tree.event_gen(yield_nones=False, timeout_s=0.05):
                    if quit.is_set():
                        return
                    if not (modified_flags & set(event[1])):
                        continue

                    # Extract relative path
                    path = PurePosixPath(event[2]) / event[3]
                    try:
                        rel_path = path.relative_to(rootpath)
                    except ValueError:
                        continue

                    # Skip dotfiles
                    if any(part.startswith(".") for part in rel_path.parts):
                        continue

                    add_dirty(rel_path, "inotify")

                    # Don't block too long collecting events
                    now = time.monotonic()
                    if first_event_time and now - first_event_time >= DEBOUNCE_MAX:
                        break
            else:
                # No inotify, just sleep briefly for responsiveness
                time.sleep(0.05)

        if inotify_tree:
            del inotify_tree


def start(app):
    global rootpath
    config.load_config()
    rootpath = config.config.path
    app.ctx.watcher = threading.Thread(
        target=watcher,
        args=[app.loop],
        # Descriptive name for system monitoring
        name=f"cista-watcher {rootpath}",
    )
    app.ctx.watcher.start()


def stop(app):
    quit.set()
    app.ctx.watcher.join()
