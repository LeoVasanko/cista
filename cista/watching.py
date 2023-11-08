import asyncio
import shutil
import sys
import threading
import time
from pathlib import Path, PurePosixPath

import msgspec
from sanic.log import logging

from cista import config
from cista.fileio import fuid
from cista.protocol import DirEntry, FileEntry, UpdateEntry

pubsub = {}
tree = {"": None}
tree_lock = threading.Lock()
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
disk_usage = None


def watcher_thread(loop):
    global disk_usage, rootpath
    import inotify.adapters

    while True:
        rootpath = config.config.path
        i = inotify.adapters.InotifyTree(rootpath.as_posix())
        old = format_tree() if tree[""] else None
        with tree_lock:
            # Initialize the tree from filesystem
            tree[""] = walk(rootpath)
        msg = format_tree()
        if msg != old:
            asyncio.run_coroutine_threadsafe(broadcast(msg), loop)

        # The watching is not entirely reliable, so do a full refresh every minute
        refreshdl = time.monotonic() + 60.0

        for event in i.event_gen():
            if quit:
                return
            # Disk usage update
            du = shutil.disk_usage(rootpath)
            if du != disk_usage:
                disk_usage = du
                asyncio.run_coroutine_threadsafe(broadcast(format_du()), loop)
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
    global disk_usage, rootpath

    while not quit:
        rootpath = config.config.path
        old = format_tree() if tree[""] else None
        with tree_lock:
            # Initialize the tree from filesystem
            tree[""] = walk(rootpath)
        msg = format_tree()
        if msg != old:
            asyncio.run_coroutine_threadsafe(broadcast(msg), loop)

        # Disk usage update
        du = shutil.disk_usage(rootpath)
        if du != disk_usage:
            disk_usage = du
            asyncio.run_coroutine_threadsafe(broadcast(format_du()), loop)

        time.sleep(1.0)


def format_du():
    return msgspec.json.encode(
        {
            "space": {
                "disk": disk_usage.total,
                "used": disk_usage.used,
                "free": disk_usage.free,
                "storage": tree[""].size,
            },
        },
    ).decode()


def format_tree():
    root = tree[""]
    return msgspec.json.encode({"root": root}).decode()


def walk(path: Path) -> DirEntry | FileEntry | None:
    try:
        s = path.stat()
        key = fuid(s)
        assert key, repr(key)
        mtime = int(s.st_mtime)
        if path.is_file():
            return FileEntry(key, s.st_size, mtime)

        tree = {
            p.name: v
            for p in path.iterdir()
            if not p.name.startswith(".")
            if (v := walk(p)) is not None
        }
        if tree:
            size = sum(v.size for v in tree.values())
            mtime = max(mtime, *(v.mtime for v in tree.values()))
        else:
            size = 0
        return DirEntry(key, size, mtime, tree)
    except FileNotFoundError:
        return None
    except OSError as e:
        print("OS error walking path", path, e)
        return None


def update(relpath: PurePosixPath, loop):
    """Called by inotify updates, check the filesystem and broadcast any changes."""
    if rootpath is None or relpath is None:
        print("ERROR", rootpath, relpath)
    new = walk(rootpath / relpath)
    with tree_lock:
        update = update_internal(relpath, new)
        if not update:
            return  # No changes
        msg = msgspec.json.encode({"update": update}).decode()
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)


def update_internal(
    relpath: PurePosixPath,
    new: DirEntry | FileEntry | None,
) -> list[UpdateEntry]:
    path = "", *relpath.parts
    old = tree
    elems = []
    for name in path:
        if name not in old:
            # File or folder created
            old = None
            elems.append((name, None))
            if len(elems) < len(path):
                # We got a notify for an item whose parent is not in tree
                print("Tree out of sync DEBUG", relpath)
                print(elems)
                print("Current tree:")
                print(tree[""])
                print("Walking all:")
                print(walk(rootpath))
                raise ValueError("Tree out of sync")
            break
        old = old[name]
        elems.append((name, old))
    if old == new:
        return []
    mt = new.mtime if new else 0
    szdiff = (new.size if new else 0) - (old.size if old else 0)
    # Update parents
    update = []
    for name, entry in elems[:-1]:
        u = UpdateEntry(name, entry.key)
        if szdiff:
            entry.size += szdiff
            u.size = entry.size
        if mt > entry.mtime:
            u.mtime = entry.mtime = mt
        update.append(u)
    # The last element is the one that changed
    name, entry = elems[-1]
    parent = elems[-2][1] if len(elems) > 1 else tree
    u = UpdateEntry(name, new.key if new else entry.key)
    if new:
        parent[name] = new
        if u.size != new.size:
            u.size = new.size
        if u.mtime != new.mtime:
            u.mtime = new.mtime
        if isinstance(new, DirEntry) and u.dir != new.dir:
            u.dir = new.dir
    else:
        del parent[name]
        u.deleted = True
    update.append(u)
    return update


async def broadcast(msg):
    try:
        for queue in pubsub.values():
            queue.put_nowait(msg)
    except Exception:
        # Log because asyncio would silently eat the error
        logging.exception("Broadcast error")



async def start(app, loop):
    config.load_config()
    app.ctx.watcher = threading.Thread(
        target=watcher_thread if sys.platform == "linux" else watcher_thread_poll,
        args=[loop],
    )
    app.ctx.watcher.start()


async def stop(app, loop):
    global quit
    quit = True
    app.ctx.watcher.join()
