import asyncio
from importlib.resources import files
from pathlib import Path

import msgspec
from sanic import Sanic
from sanic.log import logger
from sanic.response import html
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import watching
from .fileio import ROOT, FileServer
from .protocol import ErrorMsg, FileRange, StatusMsg

app = Sanic("cista")
fileserver = FileServer()

def asend(ws, msg):
    return ws.send(msg if isinstance(msg, bytes) else msgspec.json.encode(msg).decode())

@app.before_server_start
async def start_fileserver(app, _):
    await fileserver.start()

@app.after_server_stop
async def stop_fileserver(app, _):
    await fileserver.stop()

@app.before_server_start
async def start_watcher(app, _):
    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            watching.update(Path(event.src_path).relative_to(ROOT))
    app.ctx.observer = Observer()
    app.ctx.observer.schedule(Handler(), str(ROOT), recursive=True)
    app.ctx.observer.start()

@app.after_server_stop
async def stop_watcher(app, _):
    app.ctx.observer.stop()
    app.ctx.observer.join()



@app.get("/")
async def index_page(request):
    index = files("cista").joinpath("static", "index.html").read_text()
    return html(index)

app.static("/files", ROOT, use_content_range=True, stream_large_files=True, directory_view=True)

@app.websocket('/api/watch')
async def watch(request, ws):
    try:
        q = watching.pubsub[ws] = asyncio.Queue()
        await asend(ws, {"root": watching.tree})
        while True:
            await asend(ws, await q.get())
    finally:
        del watching.pubsub[ws]

@app.websocket('/api/upload')
async def upload(request, ws):
    alink = fileserver.alink
    url = request.url_for("upload")
    while True:
        req = None
        try:
            text = await ws.recv()
            if not isinstance(text, str):
                raise ValueError(f"Expected JSON control, got binary len(data) = {len(text)}")
            req = msgspec.json.decode(text, type=FileRange)
            pos = req.start
            while pos < req.end and (data := await ws.recv()) and isinstance(data, bytes):
                pos += await alink(("upload", req.name, pos, data, req.size))
            if pos != req.end:
                d = f"{len(data)} bytes" if isinstance(data, bytes) else data
                raise ValueError(f"Expected {req.end - pos} more bytes, got {d}")
            # Report success
            res = StatusMsg(status="upload", url=url, req=req)
            await asend(ws, res)
            print(res)

        except Exception as e:
            res = ErrorMsg(error=str(e), url=url, req=req)
            await asend(ws, res)
            logger.exception(repr(res), e)
            return


@app.websocket('/api/download')
async def download(request, ws):
    alink = fileserver.alink
    url = request.url_for("download")
    while True:
        req = None
        try:
            text = await ws.recv()
            if not isinstance(text, str):
                raise ValueError(f"Expected JSON control, got binary len(data) = {len(text)}")
            req = msgspec.json.decode(text, type=FileRange)
            print("download", req)
            pos = req.start
            while pos < req.end:
                end = min(req.end, pos + (1<<20))
                data = await alink(("download", req.name, pos, end))
                await asend(ws, data)
                pos += len(data)
            # Report success
            res = StatusMsg(status="download", url=url, req=req)
            await asend(ws, res)
            print(res)

        except Exception as e:
            res = ErrorMsg(error=str(e), url=url, req=req)
            await asend(ws, res)
            logger.exception(repr(res), e)
            return
