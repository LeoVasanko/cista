import asyncio
import threading
import time
from pathlib import Path, PurePosixPath

import inotify.adapters
import msgspec

from cista import config
from cista.protocol import DirEntry, FileEntry, UpdateEntry
from cista.util.apphelpers import websocket_wrapper

pubsub = {}
tree = {"": None}
tree_lock = threading.Lock()
rootpath = None
quit = False
modified_flags = "IN_CREATE", "IN_DELETE", "IN_DELETE_SELF", "IN_MODIFY", "IN_MOVE_SELF", "IN_MOVED_FROM", "IN_MOVED_TO"

def watcher_thread(loop):
    while True:
        i = inotify.adapters.InotifyTree(rootpath.as_posix())
        old = refresh() if tree[""] else None
        with tree_lock:
            # Initialize the tree from filesystem
            tree[""] = walk(rootpath)
        msg = refresh()
        if msg != old:
            asyncio.run_coroutine_threadsafe(broadcast(msg), loop)

        # The watching is not entirely reliable, so do a full refresh every minute
        refreshdl = time.monotonic() + 60.0

        for event in i.event_gen():
            if quit: return
            if time.monotonic() > refreshdl: break
            if event is None: continue
            _, flags, path, filename = event
            if not any(f in modified_flags for f in flags):
                continue
            path = PurePosixPath(path) / filename
            #print(path, flags)
            update(path.relative_to(rootpath), loop)
        i = None  # Free the inotify object

def walk(path: Path) -> DirEntry | FileEntry | None:
    try:
        s = path.stat()
        mtime = int(s.st_mtime)
        if path.is_file():
            return FileEntry(s.st_size, mtime)

        tree = {p.name: v for p in path.iterdir() if not p.name.startswith('.') if (v := walk(p)) is not None}
        if tree:
            size = sum(v.size for v in tree.values())
            mtime = max(mtime, max(v.mtime for v in tree.values()))
        else:
            size = 0
        return DirEntry(size, mtime, tree)
    except FileNotFoundError:
        return None
    except OSError as e:
        print("OS error walking path", path, e)
        return None

def refresh():
    root = tree[""]
    return msgspec.json.encode({"update": [
        UpdateEntry(size=root.size, mtime=root.mtime, dir=root.dir)
    ]}).decode()

def update(relpath: Path, loop):
    """Called by inotify updates, check the filesystem and broadcast any changes."""
    new = walk(rootpath / relpath)
    with tree_lock:
        update = update_internal(relpath, new)
        if not update: return  # No changes
        msg = msgspec.json.encode({"update": update}).decode()
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)

def update_internal(relpath: PurePosixPath, new: DirEntry | FileEntry | None) -> list[UpdateEntry]:
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
        u = UpdateEntry(name)
        if szdiff:
            entry.size += szdiff
            u.size = entry.size
        if mt > entry.mtime:
            u.mtime = entry.mtime = mt
        update.append(u)
    # The last element is the one that changed
    name, entry = elems[-1]
    parent = elems[-2][1] if len(elems) > 1 else tree
    u = UpdateEntry(name)
    if new:
        parent[name] = new
        if u.size != new.size: u.size = new.size
        if u.mtime != new.mtime: u.mtime = new.mtime
        if isinstance(new, DirEntry):
            if u.dir == new.dir: u.dir = new.dir
    else:
        del parent[name]
        u.deleted = True
    update.append(u)
    return update

async def broadcast(msg):
    for queue in pubsub.values():
        await queue.put_nowait(msg)

async def start(app, loop):
    global rootpath
    config.load_config()
    rootpath = config.config.path
    app.ctx.watcher = threading.Thread(target=watcher_thread, args=[loop])
    app.ctx.watcher.start()

async def stop(app, loop):
    global quit
    quit = True
    app.ctx.watcher.join()
