import asyncio
import gc
import io
import mimetypes
import os
import struct
import sys
import threading
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import PurePosixPath
from time import perf_counter
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import msgspec

import av
import fitz  # PyMuPDF
import numpy as np
import pillow_heif
from blake3 import blake3
from PIL import Image
from sanic import Blueprint, empty, raw, redirect
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import auth, config
from cista.preview_worker import PreviewRequest, PreviewResponse
from cista.util.filename import sanitize

pillow_heif.register_heif_opener()

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

PREVIEW_TIMEOUT = 3.0  # seconds until preview subprocess is killed
PREVIEW_WORKERS = max(2, min(8, cpu_count()))
_active_procs: set[asyncio.subprocess.Process] = set()
_preview_pool = None
_preview_pool_lock = asyncio.Lock()
AVIF_FAST_EFFORT = 0
FORCE_PIL = os.environ.get("CISTA_PIL") == "1"
WORKER_CHECKSUM_BYTES = 32
WORKER_MAX_JSON_BYTES = 1_000_000


class WorkerChecksumError(Exception):
    """Raised when worker response checksum does not match the packet."""


class WorkerProtocolError(Exception):
    """Raised when worker response packet is malformed."""


class _PreviewWorker:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc

    async def request(self, filepath, quality: int, maxsize: int, maxzoom: float):
        if self.proc.returncode is not None:
            raise WorkerProtocolError("worker already exited")
        if self.proc.stdin is None or self.proc.stdout is None:
            raise WorkerProtocolError("worker streams not available")

        line = msgspec.json.encode(
            PreviewRequest(path=str(filepath), quality=quality, maxsize=maxsize, maxzoom=maxzoom)
        ) + b"\n"
        self.proc.stdin.write(line)
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
            raise PreviewError(resp.error or "preview worker error")
        return payload or None, resp

    async def kill(self) -> None:
        if self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            await self.proc.wait()
        _active_procs.discard(self.proc)


class _PreviewWorkerPool:
    def __init__(self, size: int):
        self.size = size
        self._idle: asyncio.Queue[_PreviewWorker] = asyncio.Queue()
        self._workers: set[_PreviewWorker] = set()
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

    async def start(self) -> None:
        for _ in range(self.size):
            await self._add_worker()

    async def run(self, filepath, quality: int, maxsize: int, maxzoom: float):
        if self._closed:
            raise PreviewError("preview worker pool closed")
        worker = await self._idle.get()
        replace = False
        try:
            out, resp = await asyncio.wait_for(
                worker.request(filepath, quality, maxsize, maxzoom),
                timeout=PREVIEW_TIMEOUT,
            )
            return out, resp
        except asyncio.TimeoutError:
            replace = True
            logger.warning(
                "Preview timeout (%ds) for %s", int(PREVIEW_TIMEOUT), filepath.name
            )
            raise PreviewTimeout(filepath.name)
        except WorkerChecksumError:
            replace = True
            logger.error("Preview checksum mismatch for %s", filepath.name)
            raise PreviewError(filepath.name)
        except PreviewError:
            raise
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
            logger.warning("Preview worker protocol failure for %s: %s", filepath.name, e)
            raise PreviewError(filepath.name)
        finally:
            if replace:
                await self._replace_worker(worker)
            else:
                if worker.proc.returncode is None:
                    await self._idle.put(worker)
                else:
                    await self._replace_worker(worker)

    async def close(self) -> None:
        self._closed = True
        workers = list(self._workers)
        self._workers.clear()
        while not self._idle.empty():
            try:
                self._idle.get_nowait()
            except asyncio.QueueEmpty:
                break
        await asyncio.gather(*(worker.kill() for worker in workers), return_exceptions=True)


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
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await asyncio.gather(*(proc.wait() for proc in list(_active_procs)), return_exceptions=True)
    _active_procs.clear()


@bp.on_request
async def verify_preview(request):
    """Verify access to preview routes."""
    await auth.verify(request)


class PreviewTimeout(Exception):
    """Raised when the preview subprocess exceeds PREVIEW_TIMEOUT."""


class PreviewError(Exception):
    """Raised when the preview subprocess exits with a non-zero status."""


async def _run_preview_process(
    filepath, quality: int, maxsize: int, maxzoom: float
) -> tuple[bytes | None, PreviewResponse | None]:
    """Run preview request in a persistent worker process."""
    await start_preview_workers()
    if _preview_pool is None:
        raise PreviewError(filepath.name)
    return await _preview_pool.run(filepath, quality, maxsize, maxzoom)


# Map EXIF Orientation value to a corresponding PIL transpose
EXIF_ORI = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


DOC_PREVIEW_SUFFIXES = {".pdf", ".xps", ".epub", ".mobi"}


def is_previewable_path(path) -> bool:
    suffix = path.suffix.lower()
    if suffix in DOC_PREVIEW_SUFFIXES:
        return True
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        return False
    return mime_type.startswith("image/") or mime_type.startswith("video/")


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    maxsize = int(req.args.get("px", 1024))
    maxzoom = float(req.args.get("zoom", 2.0))
    quality = int(req.args.get("q", 60))
    rel = PurePosixPath(sanitize(unquote(path)))
    filepath = config.config.path / rel
    try:
        stat = filepath.lstat()
    except FileNotFoundError:
        raise NotFound() from None

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
        img, preview_resp = await _run_preview_process(filepath, quality, maxsize, maxzoom)
    except PreviewTimeout:
        return empty(504)
    except PreviewError:
        return empty(422)
    if preview_resp and preview_resp.backend:
        if preview_resp.load_ms is not None:
            load_ms = int(round(preview_resp.load_ms))
            process_ms = int(round(preview_resp.process_ms or 0.0))
            save_ms = int(round(preview_resp.save_ms or 0.0))
            timing_detail = f"{load_ms}/{process_ms}/{save_ms}"
        else:
            timing_detail = str(int(round(preview_resp.total_ms or 0.0)))
        req.ctx._log_extra = f"{preview_resp.backend} {timing_detail} ➛"
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


def dispatch(path, quality, maxsize, maxzoom):
    try:
        if path.suffix.lower() in DOC_PREVIEW_SUFFIXES:
            return process_pdf(path, quality=quality, maxsize=maxsize, maxzoom=maxzoom)
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type and mime_type.startswith("video/"):
            return process_video(path, quality=quality, maxsize=maxsize)
        if mime_type and mime_type.startswith("image/"):
            return process_image(path, quality=quality, maxsize=maxsize)
    except ValueError as e:
        logger.warning(f"Cannot generate preview for {path}: {e}")
    except Exception as e:
        logger.exception(f"Error generating preview for {path}: {e}")
    return None, PreviewResponse(ok=False)


def process_image(path, *, maxsize, quality):
    return process_image_with_timing(path, maxsize=maxsize, quality=quality)


def process_image_with_timing(path, *, maxsize, quality):
    if FORCE_PIL:
        return process_image_pillow(path, maxsize=maxsize, quality=quality)
    try:
        return process_image_pyvips(path, maxsize=maxsize, quality=quality)
    except Exception as e:
        logger.debug("Falling back to Pillow preview for %s: %s", path.name, e)
        return process_image_pillow(path, maxsize=maxsize, quality=quality)


def process_image_pyvips(path, *, maxsize, quality):
    import pyvips

    t_start = perf_counter()
    img = pyvips.Image.new_from_file(str(path), access="sequential")
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
        total_ms=round((t_end - t_start) * 1000, 1),
    )


def process_image_pillow(path, *, maxsize, quality):
    t_load = perf_counter()
    with Image.open(path) as img:
        # Force decode to include I/O in load timing
        img.load()
        t_proc = perf_counter()
        # Resize
        w, h = img.size
        img.thumbnail((min(w, maxsize), min(h, maxsize)))
        # Transpose pixels according to EXIF Orientation
        orientation = img.getexif().get(274, 1)
        if orientation in EXIF_ORI:
            img = img.transpose(EXIF_ORI[orientation])
        # Save as AVIF
        imgdata = io.BytesIO()
        t_save = perf_counter()
        img.save(
            imgdata,
            format="avif",
            quality=quality,
            speed=10,
            max_threads=1,
            avif=1,
        )

    t_end = perf_counter()
    ret = imgdata.getvalue()

    load_ms = (t_proc - t_load) * 1000
    proc_ms = (t_save - t_proc) * 1000
    save_ms = (t_end - t_save) * 1000
    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend="pillow",
        load_ms=round(load_ms, 1),
        process_ms=round(proc_ms, 1),
        save_ms=round(save_ms, 1),
        total_ms=round((t_end - t_load) * 1000, 1),
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
    ret = pix.pil_tobytes(
        format="avif", quality=quality, speed=10, max_threads=1, avif=1
    )
    t_save_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend="pdf",
        load_ms=round((t_load_end - t_load_start) * 1000, 1),
        save_ms=round((t_save_end - t_save_start) * 1000, 1),
        total_ms=round((t_save_end - t_load_start) * 1000, 1),
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
        assert isinstance(ostream, av.VideoStream)
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
        load_ms=round((t_load_end - t_load_start) * 1000, 1),
        save_ms=round((t_save_end - t_save_start) * 1000, 1),
        total_ms=round((t_save_end - t_load_start) * 1000, 1),
    )
    del imgdata, istream, ostream, icc, occ, frame
    gc.collect()
    return ret, resp
