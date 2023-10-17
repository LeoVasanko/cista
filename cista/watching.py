import asyncio
import secrets
import threading
from pathlib import Path, PurePosixPath

import msgspec
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import config
from .fileio import ROOT
from .protocol import DirEntry, FileEntry, UpdateEntry

secret = secrets.token_bytes(8)
pubsub = {}

def walk(path: Path = ROOT) -> DirEntry | FileEntry | None:
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

tree = {"": walk()}
tree_lock = threading.Lock()

def refresh():
    root = tree[""]
    return msgspec.json.encode({"update": [
        UpdateEntry(size=root.size, mtime=root.mtime, dir=root.dir)
    ]}).decode()

def update(relpath: PurePosixPath, loop):
    new = walk(ROOT / relpath)
    with tree_lock:
        msg = update_internal(relpath, new)
        print(msg)
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)

def update_internal(relpath: PurePosixPath, new: DirEntry | FileEntry | None):
    path = "", *relpath.parts
    old = tree
    elems = []
    for name in path:
        if name not in old:
            # File or folder created
            old = None
            elems.append((name, None))
            if len(elems) < len(path):
                raise ValueError("Tree out of sync")
            break
        old = old[name]
        elems.append((name, old))
    if old == new:
        return  # No changes
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
    print([e[0] for e in elems])
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
    return msgspec.json.encode({"update": update}).decode()

async def broadcast(msg):
    for queue in pubsub.values():
        await queue.put_nowait(msg)

def register(app, url):
    @app.before_server_start
    async def start_watcher(app, loop):
        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                update(Path(event.src_path).relative_to(ROOT), loop)
        app.ctx.observer = Observer()
        app.ctx.observer.schedule(Handler(), str(ROOT), recursive=True)
        app.ctx.observer.start()

    @app.after_server_stop
    async def stop_watcher(app, _):
        app.ctx.observer.stop()
        app.ctx.observer.join()

    @app.websocket(url)
    async def watch(request, ws):
        try:
            with tree_lock:
                q = pubsub[ws] = asyncio.Queue()
                await ws.send(refresh())
            while True:
                await ws.send(await q.get())
        finally:
            del pubsub[ws]
