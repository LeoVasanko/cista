from tarfile import DEFAULT_FORMAT
from sanic import Sanic
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path, PurePosixPath
from hashlib import sha256
import secrets
import json
import unicodedata
import asyncio
from pathvalidate import sanitize_filepath
import os

ROOT = Path(os.environ.get("STORAGE", Path.cwd()))
secret = secrets.token_bytes(8)

def fuid(stat):
    return sha256((stat.st_dev << 32 | stat.st_ino).to_bytes(8, 'big') + secret).hexdigest()[:16]

def walk(path: Path = ROOT):
    try:
        s = path.stat()
        mtime = int(s.st_mtime)
        if path.is_file():
            return s.st_size, mtime

        tree = {p.name: v for p in path.iterdir() if not p.name.startswith('.') if (v := walk(p)) is not None}
        if tree:
            size = sum(v[0] for v in tree.values())
            mtime = max(v[1] for v in tree.values())
        else:
            size = 0
        return size, mtime, tree
    except OSError as e:
        return None

tree = walk()

def update(relpath: PurePosixPath):
    ptr = tree[2]
    path = ROOT
    name = ""
    for name in relpath.parts[:-1]:
        path /= name
        try:
            ptr = ptr[name][2]
        except KeyError:
            break
    new = walk(path)
    old = ptr.pop(name, None)
    if new is not None:
        ptr[name] = new
    if old == new:
        return
    print("Update", relpath, new)
    # TODO: update parents size/mtime
    msg = json.dumps({"update": {
        "path": relpath.as_posix(),
        "data": new,
    }})
    for queue in watchers.values(): queue.put_nowait(msg)

app = Sanic(__name__)

@app.before_server_start
async def start_watcher(app, _):
    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            update(Path(event.src_path).relative_to(ROOT))
    app.ctx.observer = Observer()
    app.ctx.observer.schedule(Handler(), str(ROOT), recursive=True)
    app.ctx.observer.start()

@app.after_server_stop
async def stop_watcher(app, _):
    app.ctx.observer.stop()
    app.ctx.observer.join()

app.static('/', "index.html", name="indexhtml")
app.static("/files", ROOT, use_content_range=True, stream_large_files=True, directory_view=True)

watchers = {}

@app.websocket('/api/watch')
async def watch(request, ws):
    try:
        q = watchers[ws] = asyncio.Queue()
        await ws.send(json.dumps({"root": tree}))
        while True:
            await ws.send(await q.get())
    finally:
        del watchers[ws]

@app.websocket('/api/upload')
async def upload(request, ws):
    file = None
    filename = None
    left = 0
    msg = {}
    try:
        async for data in ws:
            if isinstance(data, bytes):
                if not file:
                    print(f"No file open, received {len(data)} bytes")
                    break
                if len(data) > left:
                    msg["error"] = "Too much data"
                    ws.send(json.dumps(msg))
                    return
                left -= len(data)
                file.write(data)
                if left == 0:
                    msg["written"] = end - start
                    await ws.send(json.dumps(msg))
                    msg = {}
                continue

            msg = json.loads(data)
            name = str(msg['name'])
            size = int(msg['size'])
            start = int(msg['start'])
            end = int(msg['end'])
            if not 0 <= start < end <= size:
                msg["error"] = "Invalid range"
                ws.send(json.dumps(msg))
                return
            left = end - start
            if filename != name:
                if file:
                    file.close()
                    file, filename = None, None
                file = openfile(name)
                file.truncate(size)
                filename = name
            file.seek(start)

    finally:
        if file:
            file.close()


def openfile(name):
    # Name sanitation & security
    name = unicodedata.normalize("NFC", name).replace("\\", "")
    name = sanitize_filepath(name)
    p = PurePosixPath(name)
    if p.is_absolute() or any(n.startswith(".") for n in p.parts):
        raise ValueError("Invalid filename")
    # Create/open file
    path = ROOT / p
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file = path.open("xb+")  # create new file
    except FileExistsError:
        file = path.open("rb+")  # write to existing file (along with other workers)
    return file
