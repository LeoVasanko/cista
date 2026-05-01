import asyncio
import contextlib
import gc
import io
import mimetypes
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path, PurePosixPath
from time import perf_counter
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import av
import fitz  # PyMuPDF
import msgspec
import numpy as np
import pyvips
from blake3 import blake3
from sanic import Blueprint, empty, raw, redirect
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import auth, config, onlyoffice, sharefs
from cista.preview_worker import PreviewRequest, PreviewResponse
from cista.util.filename import sanitize


bp = Blueprint("preview", url_prefix="/preview")


@dataclass(slots=True)
class CachedPreview:
    """Cached preview with headers and body."""

    headers: dict[str, str]
    body: bytes


class PreviewCache:
    """Thread-safe LRU cache for preview responses."""

    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self._cache: OrderedDict[str, CachedPreview] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> CachedPreview | None:
        """Get cached preview, moving it to end (most recently used)."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def set(self, key: str, value: CachedPreview) -> None:
        """Cache preview, evicting oldest if at capacity."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.capacity:
                    self._cache.popitem(last=False)
                self._cache[key] = value

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


# Global preview cache instance
_preview_cache = PreviewCache(capacity=500)

PREVIEW_TIMEOUT = 10.0  # seconds until preview subprocess is killed
PREVIEW_WORKERS = max(2, min(8, cpu_count()))
_active_procs: set[asyncio.subprocess.Process] = set()
_preview_pool = None
_preview_pool_lock = asyncio.Lock()
AVIF_FAST_EFFORT = 0
WORKER_CHECKSUM_BYTES = 32
WORKER_MAX_JSON_BYTES = 1_000_000


class WorkerChecksumError(Exception):
    """Raised when worker response checksum does not match the packet."""


class WorkerProtocolError(Exception):
    """Raised when worker response packet is malformed."""


class _PreviewWorker:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc

    async def request(
        self, filepath, quality: int, maxsize: int, maxzoom: float, data: bytes | None = None
    ):
        if self.proc.returncode is not None:
            raise WorkerProtocolError("worker already exited")
        if self.proc.stdin is None or self.proc.stdout is None:
            raise WorkerProtocolError("worker streams not available")

        meta = msgspec.json.encode(
            PreviewRequest(
                path=str(filepath),
                quality=quality,
                maxsize=maxsize,
                maxzoom=maxzoom,
            )
        )
        payload = data or b""
        packet = struct.pack("<II", len(meta), len(payload)) + meta + payload
        self.proc.stdin.write(packet)
        await self.proc.stdin.drain()

        checksum = await self.proc.stdout.readexactly(WORKER_CHECKSUM_BYTES)
        header = await self.proc.stdout.readexactly(8)
        json_size, data_size = struct.unpack("<II", header)
        if json_size > WORKER_MAX_JSON_BYTES:
            raise WorkerProtocolError(f"worker JSON too large: {json_size}")
        meta_raw = await self.proc.stdout.readexactly(json_size)
        payload = await self.proc.stdout.readexactly(data_size)
        packet = header + meta_raw + payload
        if blake3(packet).digest() != checksum:
            raise WorkerChecksumError("worker checksum mismatch")

        resp = msgspec.json.decode(meta_raw, type=PreviewResponse)
        if not resp.ok:
            raise PreviewError(
                resp.error or "preview worker error",
                stderr=resp.stderr,
                backend=resp.backend,
            )
        return payload or None, resp

    async def kill(self) -> None:
        if self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()
            await self.proc.wait()
        _active_procs.discard(self.proc)


class _PreviewWorkerPool:
    def __init__(self, size: int):
        self.size = size
        self._idle: asyncio.Queue[_PreviewWorker] = asyncio.Queue()
        self._pending: asyncio.PriorityQueue[tuple[int, int, asyncio.Future, tuple]] = (
            asyncio.PriorityQueue()
        )
        self._workers: set[_PreviewWorker] = set()
        self._dispatchers: list[asyncio.Task] = []
        self._seq = 0
        self._closed = False

    async def _spawn_worker(self) -> _PreviewWorker:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "cista.preview_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        _active_procs.add(proc)
        try:
            ready = await asyncio.wait_for(
                proc.stdout.readexactly(1), timeout=30.0
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise WorkerProtocolError("preview worker failed to become ready")
        except asyncio.IncompleteReadError:
            raise WorkerProtocolError(
                "preview worker exited before signalling readiness"
            )
        if ready != b"\x01":
            raise WorkerProtocolError(
                f"preview worker ready signal invalid: {ready!r}"
            )
        return _PreviewWorker(proc)

    async def _add_worker(self) -> None:
        worker = await self._spawn_worker()
        self._workers.add(worker)
        await self._idle.put(worker)

    async def _replace_worker(self, worker: _PreviewWorker) -> None:
        self._workers.discard(worker)
        await worker.kill()
        if self._closed:
            return
        try:
            await self._add_worker()
        except Exception:
            logger.exception("Failed to replace preview worker")

    async def _dispatch_loop(self) -> None:
        while True:
            try:
                _priority, _seq, future, args = await self._pending.get()
            except asyncio.CancelledError:
                return

            if future.cancelled():
                continue

            try:
                worker = await asyncio.wait_for(
                    self._idle.get(), timeout=PREVIEW_TIMEOUT
                )
            except TimeoutError:
                logger.warning(
                    "Preview worker unavailable (%ds) for %s",
                    int(PREVIEW_TIMEOUT),
                    args[0].name,
                )
                if not future.done():
                    future.set_exception(PreviewTimeoutError(args[0].name))
                continue

            filepath = args[0]
            replace = False
            try:
                out, resp = await asyncio.wait_for(
                    worker.request(*args),
                    timeout=PREVIEW_TIMEOUT,
                )
                if not future.done():
                    future.set_result((out, resp))
            except TimeoutError:
                replace = True
                logger.warning(
                    "Preview timeout (%ds) for %s", int(PREVIEW_TIMEOUT), filepath.name
                )
                if not future.done():
                    future.set_exception(PreviewTimeoutError(filepath.name))
            except WorkerChecksumError:
                replace = True
                logger.error("Preview checksum mismatch for %s", filepath.name)
                if not future.done():
                    future.set_exception(
                        PreviewError(f"worker checksum mismatch for {filepath.name}")
                    )
            except PreviewError as e:
                if not future.done():
                    future.set_exception(e)
            except (
                WorkerProtocolError,
                asyncio.IncompleteReadError,
                BrokenPipeError,
                ConnectionResetError,
                OSError,
                ValueError,
                msgspec.json.DecodeError,
            ) as e:
                replace = True
                logger.warning(
                    "Preview worker protocol failure for %s: %s", filepath.name, e
                )
                if not future.done():
                    future.set_exception(
                        PreviewError(
                            f"worker protocol failure for {filepath.name}: {e}"
                        )
                    )
            except Exception:
                replace = True
                logger.exception(
                    "Unexpected preview worker error for %s", filepath.name
                )
                if not future.done():
                    future.set_exception(
                        PreviewError(
                            f"unexpected worker error for {filepath.name}"
                        )
                    )
            finally:
                if replace:
                    await self._replace_worker(worker)
                elif worker.proc.returncode is None:
                    await self._idle.put(worker)
                else:
                    await self._replace_worker(worker)

    async def start(self) -> None:
        workers = await asyncio.gather(
            *(self._spawn_worker() for _ in range(self.size))
        )
        for worker in workers:
            self._workers.add(worker)
            await self._idle.put(worker)
        for _ in range(self.size):
            self._dispatchers.append(asyncio.create_task(self._dispatch_loop()))

    async def run(
        self, filepath, quality: int, maxsize: int, maxzoom: float, data: bytes | None = None
    ):
        if self._closed:
            raise PreviewError("preview worker pool closed")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._seq += 1
        await self._pending.put(
            (
                _preview_job_priority(filepath),
                self._seq,
                future,
                (filepath, quality, maxsize, maxzoom, data),
            )
        )
        return await future

    async def close(self) -> None:
        self._closed = True
        for task in self._dispatchers:
            task.cancel()
        if self._dispatchers:
            await asyncio.gather(*self._dispatchers, return_exceptions=True)
        self._dispatchers.clear()
        workers = list(self._workers)
        self._workers.clear()
        while not self._pending.empty():
            try:
                _priority, _seq, future, _args = self._pending.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not future.done():
                future.set_exception(PreviewError("preview worker pool closed"))
        while not self._idle.empty():
            try:
                self._idle.get_nowait()
            except asyncio.QueueEmpty:
                break
        await asyncio.gather(
            *(worker.kill() for worker in workers), return_exceptions=True
        )


async def start_preview_workers() -> None:
    """Warm up persistent preview workers during server startup."""
    global _preview_pool
    if _preview_pool is not None:
        return
    async with _preview_pool_lock:
        if _preview_pool is not None:
            return
        pool = _PreviewWorkerPool(PREVIEW_WORKERS)
        await pool.start()
        _preview_pool = pool
        logger.info("Started %d persistent preview workers", PREVIEW_WORKERS)


async def shutdown_preview_workers() -> None:
    """Kill persistent preview workers (called during server shutdown)."""
    global _preview_pool
    async with _preview_pool_lock:
        pool = _preview_pool
        _preview_pool = None
    if pool is not None:
        await pool.close()
    if not _active_procs:
        return
    for proc in list(_active_procs):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    await asyncio.gather(
        *(proc.wait() for proc in list(_active_procs)), return_exceptions=True
    )
    _active_procs.clear()


@bp.on_request
async def verify_preview(request):
    """Verify access to preview routes."""
    await auth.verify(request)


class PreviewTimeoutError(Exception):
    """Raised when the preview subprocess exceeds PREVIEW_TIMEOUT."""


class OnlyOfficeUnavailableError(Exception):
    """Raised when the OnlyOffice Document Server is not reachable."""


class PreviewError(Exception):
    """Raised when the preview subprocess exits with a non-zero status."""

    def __init__(
        self,
        message: str,
        *,
        stderr: str | None = None,
        backend: str | None = None,
    ):
        super().__init__(message)
        self.stderr = stderr
        self.backend = backend


# Max concurrent OnlyOffice conversion requests. OO has its own queue;
# we must not flood it. This is intentionally small.
OO_MAX_CONCURRENT = 2


class OOConversionManager:
    """Manages async OnlyOffice conversions with deduplication and concurrency limits."""

    def __init__(self, max_concurrent: int = OO_MAX_CONCURRENT):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_flight: dict[str, asyncio.Future[bytes]] = {}
        self._lock = asyncio.Lock()

    async def convert(self, filepath: Path) -> bytes:
        """Return PNG bytes for *filepath*, deduplicating concurrent requests."""
        stat = filepath.stat()
        key = f"{filepath}:{stat.st_mtime_ns}"

        async with self._lock:
            if key in self._in_flight:
                future = self._in_flight[key]
            else:
                future = asyncio.get_running_loop().create_future()
                self._in_flight[key] = future
                asyncio.create_task(self._do_convert(filepath, key, future))

        return await future

    async def _do_convert(
        self, filepath: Path, key: str, future: asyncio.Future[bytes]
    ) -> None:
        try:
            async with self._semaphore:
                png_bytes = await onlyoffice.convert_to_png_async(filepath, timeout=5.0)
        except Exception as e:
            future.set_exception(e)
            async with self._lock:
                self._in_flight.pop(key, None)
        else:
            future.set_result(png_bytes)
            async with self._lock:
                self._in_flight.pop(key, None)


_oo_manager: OOConversionManager | None = None


def get_oo_manager() -> OOConversionManager:
    """Return the singleton OOConversionManager."""
    global _oo_manager
    if _oo_manager is None:
        _oo_manager = OOConversionManager(max_concurrent=OO_MAX_CONCURRENT)
    return _oo_manager


async def _generate_office_preview(
    filepath: Path, quality: int, maxsize: int, maxzoom: float
) -> tuple[bytes | None, PreviewResponse | None]:
    """Generate a preview for an office file using OnlyOffice + worker AVIF conversion."""
    if not await onlyoffice.is_available_async():
        raise OnlyOfficeUnavailableError("OnlyOffice Document Server is not reachable")

    manager = get_oo_manager()
    t_oo_start = perf_counter()
    png_bytes = await manager.convert(filepath)
    t_oo_end = perf_counter()

    img, resp = await _run_preview_process(
        filepath, quality, maxsize, maxzoom, data=png_bytes
    )

    if resp is not None:
        resp.backend = "onlyoffice+" + (resp.backend or "pyvips")
        if resp.timings:
            resp.timings = [round((t_oo_end - t_oo_start) * 1000, 1), *resp.timings]
    return img, resp


async def _run_preview_process(
    filepath, quality: int, maxsize: int, maxzoom: float, data: bytes | None = None
) -> tuple[bytes | None, PreviewResponse | None]:
    """Run preview request in a persistent worker process."""
    await start_preview_workers()
    if _preview_pool is None:
        raise PreviewError(f"preview worker pool unavailable for {filepath.name}")
    return await _preview_pool.run(filepath, quality, maxsize, maxzoom, data)


DOC_PREVIEW_SUFFIXES = {".pdf", ".xps", ".epub", ".mobi"}

OFFICE_PREVIEW_SUFFIXES = {
    ".doc",
    ".dot",
    ".docx",
    ".docm",
    ".dotx",
    ".dotm",
    ".rtf",
    ".odt",
    ".ott",
    ".txt",
    ".md",
    ".mhtml",
    ".mht",
    ".html",
    ".htm",
    ".xml",
    ".wps",
    ".wri",
    # Spreadsheets
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".xltx",
    ".xltm",
    ".ods",
    ".ots",
    ".csv",
    # Presentations
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".pot",
    ".potx",
    ".odp",
    ".otp",
}


def _preview_job_priority(path) -> int:
    """Return priority for preview job (lower=higher priority).

    Priority order: images (0) < video (1) < PDF (2) < office (3) < unknown (4)
    """
    suffix = path.suffix.lower()
    if suffix in DOC_PREVIEW_SUFFIXES:
        return 2
    if suffix in OFFICE_PREVIEW_SUFFIXES:
        return 3
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type and mime_type.startswith("image/"):
        return 0
    if mime_type and mime_type.startswith("video/"):
        return 1
    return 4


def is_previewable_path(path) -> bool:
    suffix = path.suffix.lower()
    if suffix in DOC_PREVIEW_SUFFIXES or suffix in OFFICE_PREVIEW_SUFFIXES:
        return True
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        return False
    return mime_type.startswith(("image/", "video/"))


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

    # Generate preview
    try:
        if filepath.suffix.lower() in OFFICE_PREVIEW_SUFFIXES:
            img, preview_resp = await asyncio.wait_for(
                _generate_office_preview(filepath, quality, maxsize, maxzoom),
                timeout=PREVIEW_TIMEOUT,
            )
        else:
            img, preview_resp = await asyncio.wait_for(
                _run_preview_process(filepath, quality, maxsize, maxzoom),
                timeout=PREVIEW_TIMEOUT,
            )
    except asyncio.TimeoutError:
        logger.warning("Preview timeout for %s", filepath)
        return empty(503)
    except PreviewTimeoutError:
        logger.warning("Preview worker timeout for %s", filepath)
        return empty(503)
    except OnlyOfficeUnavailableError:
        logger.warning("OnlyOffice unavailable for %s", filepath)
        return empty(503)
    except PreviewError as e:
        if e.backend:
            req.ctx._log_extra = e.backend
        detail = str(e)
        if detail == "preview worker error" and e.stderr:
            captured = e.stderr.strip()
            if captured:
                detail = captured.splitlines()[0]
        logger.error("%s preview: %s", filepath, detail)
        return empty(422)
    except Exception:
        logger.exception("Unhandled preview error for %s", filepath)
        return empty(500)
    if preview_resp and preview_resp.backend:
        if preview_resp.timings:
            timing_detail = "/".join(
                str(round(value)) for value in preview_resp.timings
            )
            req.ctx._log_extra = f"{preview_resp.backend} {timing_detail} ➛"
        else:
            req.ctx._log_extra = preview_resp.backend
    if not img:
        # Preview generation failed, redirect to the file itself
        return redirect(f"/files/{path}", status=303)

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


def dispatch(path, quality, maxsize, maxzoom, data=None):
    backend = "unknown"
    try:
        if data:
            backend = "pyvips"
            return process_image_buffer(data, quality=quality, maxsize=maxsize, maxzoom=maxzoom)
        suffix = path.suffix.lower()
        if suffix in DOC_PREVIEW_SUFFIXES:
            backend = "pdf"
            return process_pdf(path, quality=quality, maxsize=maxsize, maxzoom=maxzoom)
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type and mime_type.startswith("video/"):
            backend = "video"
            return process_video(path, quality=quality, maxsize=maxsize)
        if mime_type and mime_type.startswith("image/"):
            backend = "pyvips"
            return process_image(path, quality=quality, maxsize=maxsize)
    except ValueError as e:
        return None, PreviewResponse(ok=False, backend=backend, error=str(e))
    except Exception as e:
        logger.exception("Preview dispatch failed for %s", path)
        return None, PreviewResponse(ok=False, backend=backend, error=str(e))
    return None, PreviewResponse(ok=False, backend=backend, error="preview unsupported")


def process_image(path, *, maxsize, quality):
    return process_image_pyvips(path, maxsize=maxsize, quality=quality)


def _get_image_dimensions(path: Path) -> tuple[int, int] | None:
    """Probe image dimensions.

    pyvips can read the header of most formats (including HEIC) without
    fully decoding the image.
    """
    try:
        img = pyvips.Image.new_from_file(str(path))
        return img.width, img.height
    except pyvips.error.Error:
        return None


def _image_via_ffmpeg(path: Path, maxsize: int, quality: int) -> bytes:
    """Convert any image to AVIF using ffmpeg CLI.

    ffmpeg handles HEIC tile assembly, EXIF rotation, HDR metadata and
    ICC profile embedding automatically.
    """
    dims = _get_image_dimensions(path)
    crf = int(63 * (1 - quality / 100) ** 2)
    with tempfile.NamedTemporaryFile(suffix=".avif", delete=False) as tmp_f:
        tmp_path = tmp_f.name
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-c:v",
        "av1",
        "-crf",
        str(crf),
        "-cpu-used",
        "8",
        tmp_path,
    ]
    if dims is not None:
        w, h = dims
        if max(w, h) > maxsize:
            scale = min(maxsize / w, maxsize / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            # insert -s <wxh> right after the input file
            cmd.insert(4, "-s")
            cmd.insert(5, f"{new_w}x{new_h}")
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def process_image_pyvips(path, *, maxsize, quality):
    t_start = perf_counter()
    suffix = path.suffix.lower()

    # HEIC/HEIF: ffmpeg handles tile assembly and HDR correctly;
    # skip pyvips entirely.
    if suffix in (".heic", ".heif"):
        ret = _image_via_ffmpeg(path, maxsize, quality)
        t_end = perf_counter()
        return ret, PreviewResponse(
            ok=True,
            mime="image/avif",
            backend="ffmpeg",
            timings=[round((t_end - t_start) * 1000, 1)],
        )

    # Other image formats: pyvips first, ffmpeg fallback.
    load_opts = {"access": "sequential"}
    try:
        img = pyvips.Image.new_from_file(str(path), **load_opts)
        img = img.autorot()
        scale = min(maxsize / img.width, maxsize / img.height, 1.0)
        if scale < 1.0:
            img = img.resize(scale)
        ret = img.write_to_buffer(
            ".avif",
            Q=quality,
            effort=AVIF_FAST_EFFORT,
            strip=True,
        )
        backend = "pyvips"
    except pyvips.error.Error:
        ret = _image_via_ffmpeg(path, maxsize, quality)
        backend = "ffmpeg"
    t_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend=backend,
        timings=[round((t_end - t_start) * 1000, 1)],
    )


def process_image_buffer(data: bytes, *, quality, maxsize, maxzoom):
    t_start = perf_counter()
    img = pyvips.Image.new_from_buffer(data, "")
    img = img.autorot()
    scale = min(maxsize / img.width, maxsize / img.height, 1.0)
    if scale < 1.0:
        img = img.resize(scale)
    ret = img.write_to_buffer(
        ".avif",
        Q=quality,
        effort=AVIF_FAST_EFFORT,
        strip=True,
    )
    t_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend="pyvips",
        timings=[round((t_end - t_start) * 1000, 1)],
    )


def process_pdf(path, *, maxsize, maxzoom, quality, page_number=0):
    t_load_start = perf_counter()
    pdf = fitz.open(path)
    page = pdf.load_page(page_number)
    w, h = page.rect[2:4]
    zoom = min(maxsize / w, maxsize / h, maxzoom)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    t_load_end = perf_counter()

    t_save_start = perf_counter()
    img = pyvips.Image.new_from_memory(
        pix.samples_mv, pix.width, pix.height, pix.n, "uchar"
    )
    ret = img.write_to_buffer(".avif", Q=quality, effort=AVIF_FAST_EFFORT, strip=True)
    backend = "pdf+pyvips"
    t_save_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend=backend,
        timings=[
            round((t_load_end - t_load_start) * 1000, 1),
            round((t_save_end - t_save_start) * 1000, 1),
        ],
    )


def process_office(path, *, quality, maxsize, maxzoom):
    t_load_start = perf_counter()
    if not onlyoffice.is_available():
        raise RuntimeError("OnlyOffice Document Server is not reachable")
    png_bytes = onlyoffice.convert_to_png(path)
    t_load_end = perf_counter()

    t_save_start = perf_counter()
    img = pyvips.Image.new_from_buffer(png_bytes, "")
    scale = min(maxsize / img.width, maxsize / img.height, 1.0)
    if scale < 1.0:
        img = img.resize(scale)
    ret = img.write_to_buffer(".avif", Q=quality, effort=AVIF_FAST_EFFORT, strip=True)
    backend = "onlyoffice+pyvips"
    t_save_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend=backend,
        timings=[
            round((t_load_end - t_load_start) * 1000, 1),
            round((t_save_end - t_save_start) * 1000, 1),
        ],
    )


def process_video(path, *, maxsize, quality):
    frame = None
    imgdata = io.BytesIO()
    istream = ostream = icc = occ = frame = None
    t_load_start = perf_counter()
    # Initialize to avoid "possibly unbound" in static analysis when exceptions occur
    t_load_end = t_load_start
    t_save_start = t_load_start
    t_save_end = t_load_start
    with (
        av.open(
            str(path),
            options={
                "analyzeduration": "1000000",  # 1 second (in microseconds)
                "fflags": "fastseek",
            },
        ) as icontainer,
        av.open(imgdata, "w", format="avif") as ocontainer,
    ):
        istream = icontainer.streams.video[0]
        istream.codec_context.skip_frame = "NONKEY"
        icontainer.seek((icontainer.duration or 0) // 8)
        for frame in icontainer.decode(istream):
            if frame.dts is not None:
                break
        else:
            raise RuntimeError("No frames found in video")

        # Resize frame to thumbnail size
        if frame.width > maxsize or frame.height > maxsize:
            scale_factor = min(maxsize / frame.width, maxsize / frame.height)
            new_width = int(frame.width * scale_factor)
            new_height = int(frame.height * scale_factor)
            frame = frame.reformat(width=new_width, height=new_height)

        # Apply EXIF rotation if present
        if frame.rotation:
            # frame.rotation indicates clockwise rotation needed to display correctly
            # np.rot90 rotates counter-clockwise, so we negate k
            k = (frame.rotation // 90) % 4  # Convert to counter-clockwise rotations
            if k == 2:
                # 180° rotation can be done in YUV420p, preserving HDR
                try:
                    fplanes = frame.to_ndarray()
                    # Split into Y, U, V planes of proper dimensions
                    planes = [
                        fplanes[: frame.height],
                        fplanes[
                            frame.height : frame.height + frame.height // 4
                        ].reshape(frame.height // 2, frame.width // 2),
                        fplanes[frame.height + frame.height // 4 :].reshape(
                            frame.height // 2, frame.width // 2
                        ),
                    ]
                    # Rotate each plane by 180°
                    planes = [np.rot90(p, 2) for p in planes]
                    # Restore PyAV format
                    planes = np.hstack([p.flat for p in planes]).reshape(
                        -1, planes[0].shape[1]
                    )
                    frame = av.VideoFrame.from_ndarray(planes, format=frame.format.name)
                    del planes, fplanes
                except Exception as e:
                    logger.exception(f"Error rotating video frame by 180°: {e}")
            elif k in (1, 3):
                # 90° or 270° rotation requires RGB conversion (loses HDR)
                try:
                    rgb = frame.to_ndarray(format="rgb24")
                    rgb = np.rot90(rgb, k)
                    frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
                    frame = frame.reformat(
                        format="yuv420p"
                    )  # Convert back for encoding
                    del rgb
                except Exception as e:
                    logger.exception(
                        f"Error rotating video frame by {frame.rotation}°: {e}"
                    )
        t_load_end = perf_counter()

        t_save_start = perf_counter()
        crf = str(int(63 * (1 - quality / 100) ** 2))  # Closely matching PIL quality-%
        ostream = ocontainer.add_stream(
            "av1",
            options={
                "crf": crf,
                "usage": "realtime",
                "cpu-used": "8",
                "threads": "1",
            },
        )
        if not isinstance(ostream, av.VideoStream):
            raise PreviewError("failed to initialize AV1 video stream")
        ostream.width = frame.width
        ostream.height = frame.height
        ostream.pix_fmt = frame.format.name
        icc = istream.codec_context
        occ = ostream.codec_context

        # Copy HDR metadata from input video stream
        occ.color_primaries = icc.color_primaries
        occ.color_trc = icc.color_trc
        occ.colorspace = icc.colorspace
        occ.color_range = icc.color_range

        ocontainer.mux(ostream.encode(frame))
        ocontainer.mux(ostream.encode(None))  # Flush the stream
        t_save_end = perf_counter()

    # Capture result before cleanup
    ret = imgdata.getvalue()
    resp = PreviewResponse(
        ok=True,
        mime="image/avif",
        backend="video",
        timings=[
            round((t_load_end - t_load_start) * 1000, 1),
            round((t_save_end - t_save_start) * 1000, 1),
        ],
    )
    del imgdata, istream, ostream, icc, occ, frame
    gc.collect()
    return ret, resp
