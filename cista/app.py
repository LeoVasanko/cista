import asyncio
import datetime
import mimetypes
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from stat import S_IFDIR, S_IFREG
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import brotli
import sanic.helpers
from blake3 import blake3
from natsort import natsorted, ns
from sanic import Blueprint, Sanic, empty, raw
from sanic.exceptions import Forbidden, NotFound
from sanic.log import logging
from stream_zip import ZIP_AUTO, stream_zip

from cista import auth, config, session, watching
from cista.api import bp
from cista.protocol import DirEntry
from cista.util.apphelpers import handle_sanic_exception

# Workaround until Sanic PR #2824 is merged
sanic.helpers._ENTITY_HEADERS = frozenset()

app = Sanic("cista", strict_slashes=True)
app.blueprint(auth.bp)
app.blueprint(bp)
app.exception(Exception)(handle_sanic_exception)


@app.before_server_start
async def main_start(app, loop):
    config.load_config()
    await watching.start(app, loop)
    app.ctx.threadexec = ThreadPoolExecutor(max_workers=8)


@app.after_server_stop
async def main_stop(app, loop):
    await watching.stop(app, loop)
    app.ctx.threadexec.shutdown()


@app.on_request
async def use_session(req):
    req.ctx.session = session.get(req)
    try:
        req.ctx.username = req.ctx.session["username"]
        req.ctx.user = config.config.users[req.ctx.session["username"]]  # type: ignore
    except (AttributeError, KeyError, TypeError):
        req.ctx.username = None
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


www = {}


@app.before_server_start
async def load_wwwroot(*_ignored):
    global www
    www = await asyncio.get_event_loop().run_in_executor(None, _load_wwwroot, www)


def _load_wwwroot(www):
    wwwnew = {}
    base = files("cista") / "wwwroot"
    paths = ["."]
    while paths:
        path = paths.pop(0)
        current = base / path
        for p in current.iterdir():
            if p.is_dir():
                paths.append(current / p.parts[-1])
                continue
            name = p.relative_to(base).as_posix()
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            mtime = p.stat().st_mtime
            data = p.read_bytes()
            etag = blake3(data).hexdigest(length=8)
            if name == "index.html":
                name = ""
            # Use old data if not changed
            if name in www and www[name][2]["etag"] == etag:
                wwwnew[name] = www[name]
                continue
            # Add charset definition
            if mime.startswith("text/"):
                mime = f"{mime}; charset=UTF-8"
            # Asset files names will change whenever the content changes
            cached = name.startswith("assets/")
            headers = {
                "etag": etag,
                "last-modified": format_date_time(mtime),
                "cache-control": "max-age=31536000, immutable"
                if cached
                else "no-cache",
                "content-type": mime,
            }
            # Precompress with Brotli
            br = brotli.compress(data)
            if len(br) >= len(data):
                br = False
            wwwnew[name] = data, br, headers
    return wwwnew


@app.add_task
async def refresh_wwwroot():
    while True:
        try:
            wwwold = www
            await load_wwwroot()
            changes = ""
            for name in sorted(www):
                attr = www[name]
                if wwwold.get(name) == attr:
                    continue
                headers = attr[2]
                changes += f"{headers['last-modified']} {headers['etag']} /{name}\n"
            for name in sorted(set(wwwold) - set(www)):
                changes += f"Deleted /{name}\n"
            if changes:
                print(f"Updated wwwroot:\n{changes}", end="", flush=True)
        except Exception as e:
            print("Error loading wwwroot", e)
        if not app.debug:
            return
        await asyncio.sleep(0.5)


@app.route("/<path:path>", methods=["GET", "HEAD"])
async def wwwroot(req, path=""):
    """Frontend files only"""
    name = unquote(path)
    if name not in www:
        raise NotFound(f"File not found: /{path}", extra={"name": name})
    data, br, headers = www[name]
    if req.headers.if_none_match == headers["etag"]:
        # The client has it cached, respond 304 Not Modified
        return empty(304, headers=headers)
    # Brotli compressed?
    if br and "br" in req.headers.accept_encoding.split(", "):
        headers = {
            **headers,
            "content-encoding": "br",
        }
        data = br
    return raw(data, headers=headers)


@app.get("/zip/<keys>/<zipfile:ext=zip>")
async def zip_download(req, keys, zipfile, ext):
    """Download a zip archive of the given keys"""
    wanted = set(keys.split("+"))
    with watching.tree_lock:
        q = deque([([], None, watching.tree[""].dir)])
        files = []
        while q:
            locpar, relpar, d = q.pop()
            for name, attr in d.items():
                loc = [*locpar, name]
                rel = None
                if relpar or attr.key in wanted:
                    rel = [*relpar, name] if relpar else [name]
                    wanted.discard(attr.key)
                isdir = isinstance(attr, DirEntry)
                if isdir:
                    q.append((loc, rel, attr.dir))
                if rel:
                    files.append(
                        ("/".join(rel), Path(watching.rootpath.joinpath(*loc)))
                    )

    if not files:
        raise NotFound(
            "No files found",
            context={"keys": keys, "zipfile": zipfile, "wanted": wanted},
        )
    if wanted:
        raise NotFound("Files not found", context={"missing": wanted})

    files = natsorted(files, key=lambda f: f[0], alg=ns.IGNORECASE)

    def local_files(files):
        for rel, p in files:
            s = p.stat()
            size = s.st_size
            modified = datetime.datetime.fromtimestamp(s.st_mtime, datetime.UTC)
            if p.is_dir():
                yield rel, modified, S_IFDIR | 0o755, ZIP_AUTO(size), b""
            else:
                yield rel, modified, S_IFREG | 0o644, ZIP_AUTO(size), contents(p)

    def contents(name):
        with name.open("rb") as f:
            while chunk := f.read(65536):
                yield chunk

    def worker():
        try:
            for chunk in stream_zip(local_files(files)):
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
        except Exception:
            logging.exception("Error streaming ZIP")
            raise
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    # Don't block the event loop: run in a thread
    queue = asyncio.Queue(maxsize=1)
    loop = asyncio.get_event_loop()
    thread = loop.run_in_executor(app.ctx.threadexec, worker)

    # Stream the response
    res = await req.respond(content_type="application/zip")
    while chunk := await queue.get():
        await res.send(chunk)

    await thread  # If it raises, the response will fail download
