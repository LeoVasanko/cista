import asyncio
from importlib.resources import files

import msgspec
from html5tagger import E
from sanic import Forbidden, Sanic, SanicException, errorpages
from sanic.log import logger
from sanic.response import html, json, redirect

from . import config, session, watching
from .auth import authbp
from .fileio import FileServer
from .protocol import ControlBase, ErrorMsg, FileRange, StatusMsg


app = Sanic("cista")
fileserver = FileServer()
watching.register(app, "/api/watch")
app.blueprint(authbp)

@app.on_request
async def use_session(request):
    request.ctx.session = session.get(request)
    # CSRF protection
    if request.method == "GET" and request.headers.upgrade != "websocket":
        return  # Ordinary GET requests are fine
    if request.headers.origin.split("//", 1)[1] != request.host:
        raise Forbidden("Invalid origin: Cross-Site requests not permitted")

@app.exception(Exception)
async def handle_sanic_exception(request, e):
    context, code, message = {}, 500, str(e) or "Internal Server Error"
    if isinstance(e, SanicException):
        context = e.context or {}
        code = e.status_code
    message = f"⚠️ {message}"
    # Non-browsers get JSON errors
    if "text/html" not in request.headers.accept:
        return json({"error": {"code": code, "message": message, **context}}, status=code)
    # Redirections flash the error message via cookies
    if "redirect" in context:
        res = redirect(context["redirect"])
        res.cookies.add_cookie("message", message, max_age=5)
        return res
    # Otherwise use Sanic's default error page
    return errorpages.HTMLRenderer(request, e, debug=app.debug).full()

@app.on_response
async def resphandler(request, response):
    print("In response handler", request.path, response)

def asend(ws, msg):
    return ws.send(msg if isinstance(msg, bytes) else msgspec.json.encode(msg).decode())

@app.before_server_start
async def start_fileserver(app, _):
    config.load_config()  # Main process may have loaded it but we haven't
    app.static("/files", config.config.path, use_content_range=True, stream_large_files=True, directory_view=True)

    await fileserver.start()

@app.after_server_stop
async def stop_fileserver(app, _):
    await fileserver.stop()

@app.get("/")
async def index_page(request):
    s = config.config.public or session.get(request)
    if not s:
        return redirect("/login")
    index = files("cista").joinpath("static", "index.html").read_text()
    flash = request.cookies.message
    if flash:
        index += str(E.dialog(flash, id="flash", open=True, style="position: fixed; top: 0; left: 0; width: 100%; opacity: .8"))
        res = html(index)
        session.flash(res, None)
        return res
    return html(index)

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

@app.websocket("/api/control")
async def control(request, websocket):
    cmd = msgspec.json.decode(await websocket.recv(), type=ControlBase)
    await asyncio.to_thread(cmd)
    await asend(websocket, StatusMsg(status="ack", req=cmd))
