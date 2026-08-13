"""Preview HTTP blueprint: routing, caching and response building.

All conversion work is delegated to the mediapreview package (worker pool,
OnlyOffice integration, classification); this module only wires it into
Sanic with auth, etag negotiation and the in-memory response cache.
"""

import asyncio
import urllib.parse
from pathlib import PurePosixPath
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

from mediapreview import CachedPreview, PreviewCache, is_previewable_path
from mediapreview.exceptions import (
    PreviewBackendError,
    PreviewCancelledError,
    PreviewError,
)
from mediapreview.formats import OFFICE_PREVIEW_SUFFIXES
from mediapreview.formats import expected_backend as _expected_preview_backend
from mediapreview.pool import (
    PREVIEW_TIMEOUT,
    generate_office_preview,
    run_preview,
)
from sanic import Blueprint, empty, raw, redirect
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import auth, config, sharefs, watching
from cista.fileio import fuid
from cista.util.filename import sanitize

bp = Blueprint("preview", url_prefix="/preview")

# Global preview cache instance
_preview_cache = PreviewCache(capacity=500)


@bp.on_request
async def verify_preview(request):
    """Verify access to preview routes."""
    await auth.verify(request)


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    maxsize = int(req.args.get("px", 1024))
    maxzoom = float(req.args.get("zoom", 2.0))
    quality = int(req.args.get("q", 60))
    share_token = auth.request_share_token(req)
    if share_token is not None:
        rel, _real_rel, filepath, is_root = sharefs.resolve_virtual_path(
            share_token, path
        )
        if is_root:
            raise NotFound from None
    else:
        rel = PurePosixPath(sanitize(unquote(path)))
        filepath = config.config.path / rel
    try:
        stat = filepath.lstat()
    except FileNotFoundError:
        raise NotFound from None

    if not is_previewable_path(filepath):
        return empty(415)

    etag = config.derived_secret(
        "preview", rel, stat.st_mtime_ns, quality, maxsize, maxzoom
    ).hex()

    if req.headers.if_none_match == etag:
        # The client has it cached, respond 304 Not Modified
        return empty(304, headers={"etag": etag})

    # Check in-memory cache first (includes headers)
    cached = _preview_cache.get(etag)
    if cached is not None:
        logger.debug(f"Preview cache hit: {rel}")
        return raw(cached.body, headers=cached.headers)

    # Generate preview. The outer deadline is strict: pool internals have
    # their own timeouts, but queueing (workers, the OnlyOffice semaphore)
    # must not let a request exceed PREVIEW_TIMEOUT.
    try:
        if filepath.suffix.lower() in OFFICE_PREVIEW_SUFFIXES:
            img, preview_resp = await asyncio.wait_for(
                generate_office_preview(filepath, quality, maxsize, maxzoom),
                timeout=PREVIEW_TIMEOUT,
            )
        else:
            img, preview_resp = await asyncio.wait_for(
                run_preview(filepath, quality, maxsize, maxzoom),
                timeout=PREVIEW_TIMEOUT,
            )
    except TimeoutError:
        req.ctx.log_extra = f"{_expected_preview_backend(filepath)} timeout"
        return empty(503)
    except PreviewError as e:
        # mediapreview is responsible for backend-specific diagnostics; cista only
        # needs the backend name, a short access-log reason, and a response status.
        if isinstance(e, PreviewCancelledError):
            req.ctx.log_extra = e.short or "preview cancelled"
            raise asyncio.CancelledError from e
        status = 422 if isinstance(e, PreviewBackendError) else 503
        req.ctx.log_extra = f"{e.backend}: {e.short}" if e.backend else e.short
        if req.app.debug:
            logger.warning("%s", str(e))
        return empty(status)
    except asyncio.CancelledError:
        # Server shutdown or client disconnect: the connection is being torn
        # down, so responding is impossible — just annotate the access log.
        req.ctx.log_extra = "preview cancelled"
        raise
    except Exception:
        logger.exception("Unhandled preview error for %s", filepath)
        return empty(500)
    if preview_resp and preview_resp.backend:
        if preview_resp.timings:
            timing_detail = "/".join(
                str(round(value)) for value in preview_resp.timings
            )
            req.ctx.log_extra = f"{preview_resp.backend} {timing_detail} ➛"
        else:
            req.ctx.log_extra = preview_resp.backend
    if not img:
        # Preview generation failed, redirect to the file itself
        return redirect(f"/files/{path}", status=303)

    # Store aspect ratio if the worker returned dimensions
    if preview_resp and preview_resp.width and preview_resp.height:
        ar = round(preview_resp.height / preview_resp.width, 2)
        fuid_str = fuid(stat)
        watching.notify_ar(fuid_str, ar)

    # Build headers and cache the full response
    preview_mime = (
        preview_resp.mime
        if preview_resp is not None and preview_resp.mime is not None
        else "image/avif"
    )
    savename = PurePosixPath(filepath.name).with_suffix(".avif")
    headers = {
        "etag": etag,
        "last-modified": format_date_time(stat.st_mtime),
        "cache-control": "max-age=604800, immutable"
        + ("" if config.config.public else ", private"),
        "content-type": preview_mime,
        "content-disposition": f"inline; filename*=UTF-8''{urllib.parse.quote(savename.as_posix())}",
    }
    _preview_cache.set(etag, CachedPreview(headers=headers, body=img))

    return raw(img, headers=headers)
