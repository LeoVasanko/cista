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
        self._listing: list[FileEntry] = []

    @property
    def space(self):
        with self.lock:
            return self._space

    @space.setter
    def space(self, space):
        with self.lock:
            self._space = space

    @property
    def root(self) -> list[FileEntry]:
        with self.lock:
            return self._listing[:]

    @root.setter
    def root(self, listing: list[FileEntry]):
        with self.lock:
            self._listing = listing

    def _slice(self, idx: PurePosixPath | tuple[PurePosixPath, int]):
        relpath, relfile = idx if isinstance(idx, tuple) else (idx, 0)
        begin, end = 0, len(self._listing)
        level = 0
        isfile = 0

        # Special case for root
        if not relpath.parts:
            return slice(begin, end)

        begin += 1
        for part in relpath.parts:
            level += 1
            found = False

            while begin < end:
                entry = self._listing[begin]

                if entry.level < level:
                    break

                if entry.level == level:
                    if entry.name == part:
                        found = True
                        if level == len(relpath.parts):
                            isfile = relfile
                        else:
                            begin += 1
                        break
                    cmp = entry.isfile - isfile or sortkey(entry.name) > sortkey(part)
                    if cmp > 0:
                        break

                begin += 1

            if not found:
                return slice(begin, begin)

        # Found the starting point, now find the end of the slice
        for end in range(begin + 1, len(self._listing) + 1):
            if end == len(self._listing) or self._listing[end].level <= level:
                break
        return slice(begin, end)

    def __getitem__(self, index: PurePosixPath | tuple[PurePosixPath, int]):
        with self.lock:
            return self._listing[self._slice(index)]

    def __setitem__(
        self, index: tuple[PurePosixPath, int], value: list[FileEntry]
    ) -> None:
        rel, isfile = index
        with self.lock:
            if rel.parts:
                parent = self._slice(rel.parent)
                if parent.start == parent.stop:
                    raise ValueError(
                        f"Parent folder {rel.as_posix()} is missing for {rel.name}"
                    )
            self._listing[self._slice(index)] = value

    def __delitem__(self, relpath: PurePosixPath):
        with self.lock:
            del self._listing[self._slice(relpath)]


state = State()
rootpath: Path = None  # type: ignore
quit = threading.Event()

## Filesystem scanning


def walk(rel: PurePosixPath, stat: stat_result | None = None) -> list[FileEntry]:
    path = rootpath / rel
    ret = []
    try:
        st = stat or path.stat()
        isfile = not S_ISDIR(st.st_mode)
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
        ret = [entry]
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
            ret.extend(sub)
            child = sub[0]
            entry.mtime = max(entry.mtime, child.mtime)
            entry.size += child.size
    except FileNotFoundError:
        pass  # Things may be rapidly in motion
    except OSError as e:
        if e.errno == 13:  # Permission denied
            pass
        logger.error(f"Watching {path=}: {e!r}")
    return ret


def update_root(loop):
    """Full filesystem scan"""
    new = walk(PurePosixPath())
    with state.lock:
        old = state.root
        if old != new:
            state.root = new
            broadcast(format_update(old, new), loop)


def update_path(relpath: PurePosixPath, loop):
    """Called on FS updates, check the filesystem and broadcast any changes."""
    new = walk(relpath)
    with state.lock:
        old = state[relpath]
        if old == new:
            return
        old = state.root
        if new:
            state[relpath, new[0].isfile] = new
        else:
            del state[relpath]
        broadcast(format_update(old, state.root), loop)


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
    update = []
    keep_count = 0
    while oidx < len(old) and nidx < len(new):
        if old[oidx] == new[nidx]:
            keep_count += 1
            oidx += 1
            nidx += 1
            continue
        if keep_count > 0:
            update.append(UpdKeep(keep_count))
            keep_count = 0

        del_count = 0
        rest = new[nidx:]
        while oidx < len(old) and old[oidx] not in rest:
            del_count += 1
            oidx += 1
        if del_count:
            update.append(UpdDel(del_count))
            continue

        insert_items = []
        rest = old[oidx:]
        while nidx < len(new) and new[nidx] not in rest:
            insert_items.append(new[nidx])
            nidx += 1
        update.append(UpdIns(insert_items))

    # Diff any remaining
    if keep_count > 0:
        update.append(UpdKeep(keep_count))
    if oidx < len(old):
        update.append(UpdDel(len(old) - oidx))
    elif nidx < len(new):
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
        update_root(loop)
        trefresh = time.monotonic() + 30.0
        tspace = time.monotonic() + 5.0
        # Watch for changes (frequent wakeups needed for quiting)
        for event in i.event_gen(timeout_s=0.1):
            if quit.is_set():
                break
            t = time.monotonic()
            # The watching is not entirely reliable, so do a full refresh every 30 seconds
            if t >= trefresh:
                break
            # Disk usage update
            if t >= tspace:
                tspace = time.monotonic() + 5.0
                update_space(loop)
            # Inotify event, update the tree
            if event and any(f in modified_flags for f in event[1]):
                # Update modified path
                update_path(PurePosixPath(event[2]) / event[3], loop)

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
