import asyncio
import datetime
import mimetypes
import threading
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path, PurePath, PurePosixPath
from stat import S_IFDIR, S_IFREG
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import sanic.helpers
from blake3 import blake3
from sanic import Blueprint, Sanic, empty, raw, redirect
from sanic.exceptions import Forbidden, NotFound
from sanic.log import logger
from setproctitle import setproctitle
from stream_zip import ZIP_AUTO, stream_zip
from zstandard import ZstdCompressor

from cista import auth, config, preview, session, sso, watching
from cista.api import bp
from cista.util.apphelpers import handle_sanic_exception

# Workaround until Sanic PR #2824 is merged
sanic.helpers._ENTITY_HEADERS = frozenset()

app = Sanic("cista", strict_slashes=True)
# Register either SSO proxy or built-in auth routes based on PASKIA_BACKEND_URL
if sso.paskia_enabled():
    app.blueprint(sso.bp)  # SSO proxy for /auth/* routes
else:
    app.blueprint(auth.bp)  # Built-in auth routes
app.blueprint(preview.bp)
app.blueprint(bp)
app.exception(Exception)(handle_sanic_exception)


setproctitle("cista-main")


@app.before_server_start
async def main_start(app):
    config.load_config()
    setproctitle(f"cista {config.config.path.name}")
    workers = max(2, min(8, cpu_count()))
    app.ctx.threadexec = ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="cista-ioworker"
    )
    watching.start(app)


# Sanic sometimes fails to execute after_server_stop, so we do it before instead (potentially interrupting handlers)
@app.before_server_stop
async def main_stop(app):
    quit.set()
    watching.stop(app)
    app.ctx.threadexec.shutdown()
    await sso.close_client()
    logger.debug("Cista worker threads all finished")


@app.on_request
async def use_session(req):
    req.ctx.session = session.get(req)
    try:
        req.ctx.username = req.ctx.session["username"]  # type: ignore
        req.ctx.user = config.config.users[req.ctx.username]
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


@app.on_response
async def forward_sso_cookies(req, res):
    """Forward Set-Cookie headers from SSO validation to client."""
    if cookies := getattr(req.ctx, "sso_cookies", None):
        for cookie in cookies:
            res.headers.add("set-cookie", cookie)


@app.before_server_start
def http_fileserver(app):
    bp = Blueprint("fileserver")

    @bp.on_request
    async def verify_fileserver(request):
        """Verify access to file server routes."""
        await auth.verify(request)

    bp.static(
        "/files/",
        config.config.path,
        use_content_range=True,
        stream_large_files=True,
        directory_view=True,
    )
    app.blueprint(bp)


www = {}


def _load_wwwroot(www):
    wwwnew = {}
    base = Path(__file__).with_name("frontend-build")
    paths = [PurePath()]
    zstd = ZstdCompressor(level=18)
    while paths:
        path = paths.pop(0)
        current = base / path
        for p in current.iterdir():
            if p.is_dir():
                paths.append(p.relative_to(base))
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
            # Precompress with ZSTD
            zs = zstd.compress(data)
            if len(zs) >= len(data):
                zs = False
            wwwnew[name] = data, zs, headers
    if not wwwnew:
        msg = f"Web frontend missing from {base}\n  Did you forget: hatch build\n"
        if not www:
            logger.warning(msg)
        if not app.debug:
            msg = "Web frontend missing. Cista installation is broken.\n"
        wwwnew[""] = (
            msg.encode(),
            False,
            {
                "etag": "error",
                "content-type": "text/plain",
                "cache-control": "no-store",
            },
        )
    return wwwnew


@app.before_server_start
async def start(app):
    await load_wwwroot(app)
    if app.debug:
        app.add_task(refresh_wwwroot(), name="refresh_wwwroot")


async def load_wwwroot(app):
    global www
    www = await asyncio.get_event_loop().run_in_executor(
        app.ctx.threadexec, _load_wwwroot, www
    )


quit = threading.Event()


async def refresh_wwwroot():
    try:
        while not quit.is_set():
            try:
                wwwold = www
                await load_wwwroot(app)
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
                    logger.info(f"Updated wwwroot:\n{changes}", end="", flush=True)
            except Exception as e:
                logger.error(f"Error loading wwwroot: {e!r}")
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


@app.route("/<path:path>", methods=["GET", "HEAD"])
async def wwwroot(req, path=""):
    """Frontend files only"""
    name = unquote(path)
    if name not in www:
        raise NotFound(f"File not found: /{path}", extra={"name": name})
    data, zs, headers = www[name]
    if req.headers.if_none_match == headers["etag"]:
        # The client has it cached, respond 304 Not Modified
        return empty(304, headers=headers)
    # Zstandard compressed?
    if zs and "zstd" in req.headers.accept_encoding.split(", "):
        headers = {**headers, "content-encoding": "zstd"}
        data = zs
    return raw(data, headers=headers)


@app.route("/favicon.ico", methods=["GET", "HEAD"])
async def favicon(req):
    # Browsers keep asking for it when viewing files (not HTML with icon link)
    return redirect("/assets/logo-ctv8tVwU.svg", status=308)


def get_files(wanted: set) -> list[tuple[PurePosixPath, Path]]:
    loc = PurePosixPath()
    idx = 0
    ret = []
    level: int | None = None
    parent: PurePosixPath | None = None
    with watching.state.lock:
        root = watching.state.root
        while idx < len(root):
            f = root[idx]
            loc = PurePosixPath(*loc.parts[: f.level - 1]) / f.name
            if parent is not None and f.level <= level:
                level = parent = None
            if f.key in wanted:
                level, parent = f.level, loc.parent
            if parent is not None:
                wanted.discard(f.key)
                ret.append((loc.relative_to(parent), watching.rootpath / loc))
            idx += 1
    return ret


@app.get("/zip/<keys>/<zipfile:ext=zip>")
async def zip_download(req, keys, zipfile, ext):
    """Download a zip archive of the given keys"""
    await auth.verify(req)

    wanted = set(keys.split("+"))
    files = get_files(wanted)

    if not files:
        raise NotFound(
            "No files found",
            context={"keys": keys, "zipfile": f"{zipfile}.{ext}", "wanted": wanted},
        )
    if wanted:
        raise NotFound("Files not found", context={"missing": wanted})

    def local_files(files):
        for rel, p in files:
            s = p.stat()
            size = s.st_size
            modified = datetime.datetime.fromtimestamp(s.st_mtime, datetime.UTC)
            name = rel.as_posix()
            if p.is_dir():
                yield f"{name}/", modified, S_IFDIR | 0o755, ZIP_AUTO(size), iter(b"")
            else:
                yield name, modified, S_IFREG | 0o644, ZIP_AUTO(size), contents(p, size)

    def contents(name, size):
        with name.open("rb") as f:
            while size > 0 and (chunk := f.read(min(size, 1 << 20))):
                size -= len(chunk)
                yield chunk
        assert size == 0

    def worker():
        try:
            for chunk in stream_zip(local_files(files)):
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
        except Exception:
            logger.exception("Error streaming ZIP")
            raise
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    # Don't block the event loop: run in a thread
    queue = asyncio.Queue(maxsize=1)
    loop = asyncio.get_event_loop()
    thread = loop.run_in_executor(app.ctx.threadexec, worker)

    # Stream the response
    res = await req.respond(
        content_type="application/zip",
        headers={"cache-control": "no-store"},
    )
    while chunk := await queue.get():
        await res.send(chunk)

    await thread  # If it raises, the response will fail download
