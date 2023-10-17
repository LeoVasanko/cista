import asyncio
from importlib.resources import files

import msgspec
from sanic import Sanic
from sanic.log import logger
from sanic.response import html

from . import watching
from .fileio import ROOT, FileServer
from .protocol import ErrorMsg, FileRange, StatusMsg

app = Sanic("cista")
fileserver = FileServer()
watching.register(app, "/api/watch")

def asend(ws, msg):
    return ws.send(msg if isinstance(msg, bytes) else msgspec.json.encode(msg).decode())

@app.before_server_start
async def start_fileserver(app, _):
    await fileserver.start()

@app.after_server_stop
async def stop_fileserver(app, _):
    await fileserver.stop()

@app.get("/")
async def index_page(request):
    index = files("cista").joinpath("static", "index.html").read_text()
    return html(index)

app.static("/files", ROOT, use_content_range=True, stream_large_files=True, directory_view=True)

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
            res = StatusMsg(status="ack", req=req)
            await asend(ws, res)
            await ws.drain()
        except Exception as e:
            res = ErrorMsg(error=str(e), req=req)
            await asend(ws, res)
            logger.exception(repr(res), e)
            return

@app.websocket("/ws")
async def ws(request, ws):
    while True:
        data = await ws.recv()
        await ws.send(data)

@app.websocket('/api/download')
async def download(request, ws):
    alink = fileserver.alink
    while True:
        req = None
        try:
            print("Waiting for download command")
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
            res = StatusMsg(status="ack", req=req)
            await asend(ws, res)
            print(ws, dir(ws))
            await ws.drain()
            print(res)

        except Exception as e:
            res = ErrorMsg(error=str(e), req=req)
            await asend(ws, res)
            logger.exception(repr(res), e)
            return
