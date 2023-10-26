import mimetypes
from importlib.resources import files
from urllib.parse import unquote

from sanic import Blueprint, Sanic, raw
from sanic.exceptions import Forbidden, NotFound

from cista import auth, config, session, watching
from cista.api import bp
from cista.util import filename
from cista.util.apphelpers import handle_sanic_exception

app = Sanic("cista", strict_slashes=True)
app.blueprint(auth.bp)
app.blueprint(bp)
app.exception(Exception)(handle_sanic_exception)


@app.before_server_start
async def main_start(app, loop):
    config.load_config()
    await watching.start(app, loop)


@app.after_server_stop
async def main_stop(app, loop):
    await watching.stop(app, loop)


@app.on_request
async def use_session(req):
    req.ctx.session = session.get(req)
    try:
        req.ctx.user = config.config.users[req.ctx.session["username"]]  # type: ignore
    except (AttributeError, KeyError, TypeError):
        req.ctx.user = None
    # CSRF protection
    if req.method == "GET" and req.headers.upgrade != "websocket":
        return  # Ordinary GET requests are fine
    # Check that origin matches host, for browsers which should all send Origin.
    # Curl doesn't send any Origin header, so we allow it anyway.
    origin = req.headers.origin
    if origin and origin.split("//", 1)[1] != req.host:
        raise Forbidden("Invalid origin: Cross-Site requests not permitted")


@app.before_server_start
def http_fileserver(app, _):
    bp = Blueprint("fileserver")
    bp.on_request(auth.verify)
    bp.static(
        "/files/",
        config.config.path,
        use_content_range=True,
        stream_large_files=True,
        directory_view=True,
    )
    app.blueprint(bp)


@app.get("/<path:path>", static=True)
async def wwwroot(req, path=""):
    """Frontend files only"""
    name = filename.sanitize(unquote(path)) if path else "index.html"
    try:
        index = files("cista").joinpath("wwwroot", name).read_bytes()
    except OSError as e:
        raise NotFound(
            f"File not found: /{path}", extra={"name": name, "exception": repr(e)}
        )
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return raw(index, content_type=mime)
