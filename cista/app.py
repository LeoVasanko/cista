import asyncio
import datetime
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePath, PurePosixPath
from stat import S_IFDIR, S_IFREG
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import tracerite
from blake3 import blake3
from sanic import Sanic, empty, raw, redirect
from sanic.exceptions import Forbidden, NotFound
from sanic.log import logger
from setproctitle import setproctitle
from stream_zip import ZIP_AUTO, stream_zip
from zstandard import ZstdCompressor

from cista import (
    auth,
    config,
    fileserver,
    onlyoffice,
    preview,
    session,
    sharefs,
    sso,
    watching,
)
from cista.api import bp
from cista.preview import shutdown_preview_workers, start_preview_workers
from cista.sanic_logging import (
    configure_access_logging,
    configure_main_logging,
    format_access_log,
)
from cista.sanic_logging import logger as access_logger
from cista.util.apphelpers import handle_sanic_exception

tracerite.load()
configure_access_logging()


app = Sanic("cista", strict_slashes=True)
app.router.ALLOWED_METHODS = (
    *app.router.ALLOWED_METHODS,
    "MKCOL",
    "MOVE",
    "COPY",
    "PROPFIND",
)

configure_main_logging()


@app.on_request
async def use_session(req):
    req.ctx.log_start = time.perf_counter()
    req.ctx.auth_flow = ["session: start"]
    auth.hydrate_request_auth_context(req, source="app.on_request")
    # CSRF protection
    if req.method == "GET" and req.headers.upgrade != "websocket":
        return  # Ordinary GET requests are fine
    # Check that origin matches host, for browsers which should all send Origin.
    # Curl doesn't send any Origin header, so we allow it anyway.
    origin = req.headers.origin
    if origin and origin.split("//", 1)[1] != req.host:
        raise Forbidden("Invalid origin: Cross-Site requests not permitted")


@app.on_response
async def log_access(req, res):
    """Log HTTP access in a clean single-line format."""
    if req.headers.get("upgrade", "").lower() == "websocket":
        return res
    start = getattr(req.ctx, "log_start", None)
    duration_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
    client = req.client_ip or "-"
    host = req.host or "-"
    path = req.path
    if req.query_string:
        qs = req.query_string
        if isinstance(qs, bytes):
            qs = qs.decode(errors="replace")
        path = f"{path}?{qs}"
    extra = getattr(req.ctx, "log_extra", None)
    line = format_access_log(
        client, res.status, req.method, host, path, duration_ms, extra=extra
    )
    access_logger.info(line)
    return res


@app.on_response
async def forward_sso_cookies(req, res):
    """Forward Set-Cookie headers from SSO validation to client."""
    if cookies := getattr(req.ctx, "sso_cookies", None):
        for cookie in cookies:
            res.headers.add("set-cookie", cookie)


@app.on_response
async def persist_auth_session(req, res):
    """Persist a session cookie after successful Authorization-based auth."""
    username = getattr(req.ctx, "create_session_username", None)
    if not username or res.status >= 400:
        return
    existing = getattr(req.ctx, "session", None)
    if isinstance(existing, dict) and existing.get("username") == username:
        return
    session.create(req, res, username)


# Register either SSO proxy or built-in auth routes based on PASKIA_BACKEND_URL
if sso.paskia_enabled():
    app.blueprint(sso.bp)  # SSO proxy for /auth/* routes
else:
    app.blueprint(auth.bp)  # Built-in auth routes
app.blueprint(preview.bp)
app.blueprint(bp)
app.blueprint(fileserver.bp)
app.exception(Exception)(handle_sanic_exception)


setproctitle("cista-main")


@app.before_server_start
async def main_start(app):
    config.load_config()
    setproctitle(f"cista {config.config.path.name}")
    app.ctx.threadexec = ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="cista-worker"
    )
    # Larger pool for long-running but low-memory zip operations
    app.ctx.zipexec = ThreadPoolExecutor(max_workers=32, thread_name_prefix="cista-zip")
    await start_preview_workers()
    watching.start(app)


@app.after_server_start
async def main_after_start(app):
    _ = app
    onlyoffice.log_reachable_info()


# Sanic sometimes fails to execute after_server_stop, so we do it before instead (potentially interrupting handlers)
@app.before_server_stop
async def main_stop(app):
    async with asyncio.TaskGroup() as tg:
        tg.create_task(asyncio.to_thread(watching.stop, app))
        tg.create_task(onlyoffice.close_oo_client())
        tg.create_task(shutdown_preview_workers())
        tg.create_task(sso.close_client())

    async with asyncio.TaskGroup() as tg:
        tg.create_task(asyncio.to_thread(app.ctx.threadexec.shutdown))
        tg.create_task(asyncio.to_thread(app.ctx.zipexec.shutdown, cancel_futures=True))

    logger.debug("Cista worker threads all finished")


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
    if not app.debug:
        await load_wwwroot(app)


async def load_wwwroot(app):
    global www
    www = await asyncio.get_event_loop().run_in_executor(
        app.ctx.threadexec, _load_wwwroot, www
    )


@app.route("/<path:path>", methods=["GET", "HEAD"])
async def wwwroot(req, path=""):
    """Frontend files only"""
    if app.debug:
        raise NotFound(
            "Dev mode: frontend-build is not served on backend (you should connect vite)",
            extra={"name": path},
        )
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
    _ = req
    # Browsers keep asking for it when viewing files (not HTML with icon link)
    return redirect("/assets/logo-ctv8tVwU.svg", status=308)


def get_files(req, wanted: set) -> list[tuple[PurePosixPath, Path]]:
    loc = PurePosixPath()
    idx = 0
    ret = []
    level: int | None = None
    parent: PurePosixPath | None = None
    token = auth.request_share_token(req)

    if token is None:
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

    root = sharefs.build_virtual_root(token)
    while idx < len(root):
        f = root[idx]
        loc = PurePosixPath(*loc.parts[: f.level - 1]) / f.name
        if parent is not None and f.level <= level:
            level = parent = None
        if f.key in wanted:
            level, parent = f.level, loc.parent
        if parent is not None:
            wanted.discard(f.key)
            real_path = sharefs.resolve_virtual_rel_to_real(token, loc)
            ret.append((loc.relative_to(parent), real_path))
        idx += 1
    return ret


@app.get("/zip/<keys>/<zipfile:ext=zip>")
async def zip_download(req, keys, zipfile, ext):
    """Download a zip archive of the given keys"""
    await auth.verify(req)

    wanted = set(keys.split("+"))
    files = get_files(req, wanted)

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
        if size != 0:
            raise OSError(f"stream ended early while zipping {name}")

    pending_put = None  # Current queue.put future, can be cancelled

    def worker():
        nonlocal pending_put
        try:
            for chunk in stream_zip(local_files(files)):
                future = asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
                pending_put = future
                future.result()  # Blocks until queue has space
        except asyncio.CancelledError:
            logger.info("ZIP download cancelled by client disconnect")
        except Exception:
            logger.exception("Error streaming ZIP")
            raise
        finally:
            pending_put = None
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    # Don't block the event loop: run in a thread (use larger zip pool)
    queue = asyncio.Queue(maxsize=1)
    loop = asyncio.get_event_loop()
    thread = loop.run_in_executor(app.ctx.zipexec, worker)

    # Stream the response
    res = await req.respond(
        content_type="application/zip",
        headers={"cache-control": "no-store"},
    )
    try:
        while chunk := await queue.get():
            await res.send(chunk)
    finally:
        # Cancel any pending put to unblock and stop the worker
        if pending_put:
            pending_put.cancel()

    await thread  # If it raises, the response will fail download
