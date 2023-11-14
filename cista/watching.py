import asyncio
import shutil
import stat
import sys
import threading
import time
from os import stat_result
from pathlib import Path, PurePosixPath

import msgspec
from natsort import humansorted, natsort_keygen, ns
from sanic.log import logging

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
quit = False
modified_flags = (
    "IN_CREATE",
    "IN_DELETE",
    "IN_DELETE_SELF",
    "IN_MODIFY",
    "IN_MOVE_SELF",
    "IN_MOVED_FROM",
    "IN_MOVED_TO",
)


def watcher_thread(loop):
    global rootpath
    import inotify.adapters

    while not quit:
        rootpath = config.config.path
        i = inotify.adapters.InotifyTree(rootpath.as_posix())
        # Initialize the tree from filesystem
        new = walk()
        with state.lock:
            old = state.root
            if old != new:
                state.root = new
                broadcast(format_update(old, new), loop)

        # The watching is not entirely reliable, so do a full refresh every 30 seconds
        refreshdl = time.monotonic() + 30.0

        for event in i.event_gen():
            if quit:
                return
            # Disk usage update
            du = shutil.disk_usage(rootpath)
            space = Space(*du, storage=state.root[0].size)
            if space != state.space:
                state.space = space
                broadcast(format_space(space), loop)
                break
            # Do a full refresh?
            if time.monotonic() > refreshdl:
                break
            if event is None:
                continue
            _, flags, path, filename = event
            if not any(f in modified_flags for f in flags):
                continue
            # Update modified path
            path = PurePosixPath(path) / filename
            try:
                update(path.relative_to(rootpath), loop)
            except Exception as e:
                print("Watching error", e, path, rootpath)
                raise
        i = None  # Free the inotify object


def watcher_thread_poll(loop):
    global rootpath

    while not quit:
        rootpath = config.config.path
        new = walk()
        with state.lock:
            old = state.root
            if old != new:
                state.root = new
                broadcast(format_update(old, new), loop)

        # Disk usage update
        du = shutil.disk_usage(rootpath)
        space = Space(*du, storage=state.root[0].size)
        if space != state.space:
            state.space = space
            broadcast(format_space(space), loop)

        time.sleep(2.0)


def walk(rel=PurePosixPath()) -> list[FileEntry]:  # noqa: B008
    path = rootpath / rel
    try:
        st = path.stat()
    except OSError:
        return []
    return _walk(rel, int(not stat.S_ISDIR(st.st_mode)), st)


def _walk(rel: PurePosixPath, isfile: int, st: stat_result) -> list[FileEntry]:
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
    ret = [entry]
    path = rootpath / rel
    try:
        li = []
        for f in path.iterdir():
            if quit:
                raise SystemExit("quit")
            if f.name.startswith("."):
                continue  # No dotfiles
            s = f.stat()
            li.append((int(not stat.S_ISDIR(s.st_mode)), f.name, s))
        for [isfile, name, s] in humansorted(li):
            if quit:
                raise SystemExit("quit")
            subtree = _walk(rel / name, isfile, s)
            child = subtree[0]
            entry.mtime = max(entry.mtime, child.mtime)
            entry.size += child.size
            ret.extend(subtree)
    except FileNotFoundError:
        pass  # Things may be rapidly in motion
    except OSError as e:
        print("OS error walking path", path, e)
    return ret


def update(relpath: PurePosixPath, loop):
    """Called by inotify updates, check the filesystem and broadcast any changes."""
    if rootpath is None or relpath is None:
        print("ERROR", rootpath, relpath)
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
        logging.exception("Broadcast error")


async def start(app, loop):
    config.load_config()
    use_inotify = sys.platform == "linux"
    app.ctx.watcher = threading.Thread(
        target=watcher_thread if use_inotify else watcher_thread_poll,
        args=[loop],
    )
    app.ctx.watcher.start()


async def stop(app, loop):
    global quit
    quit = True
    app.ctx.watcher.join()
