"""Preview generation worker subprocess and synchronous preview engine.

Two modes are supported:
1) Legacy one-shot mode: argv has path/quality/maxsize/maxzoom.
2) Long-lived mode: read framed requests from stdin and write framed responses.

Framed request format (stdin):
    (uint32 json size)(uint32 data size)(json)(binary data)

Framed response format (stdout):
    (blake3(packet))(uint32 json size)(uint32 payload size)(json)(binary payload)
where packet = (uint32 json size)(uint32 payload size)(json)(binary payload).
"""

import contextlib
import gc
import io
import logging
import mimetypes
import os
import shlex
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

import av
import msgspec
import numpy as np
import pymupdf
import pyvips
from blake3 import blake3

from cista import config
from cista.util.logformat import format_level_prefix

logger = logging.getLogger(__name__)


class _WorkerLogFormatter(logging.Formatter):
    """Emoji level prefix like the main process, tagged with the worker pid."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = format_level_prefix(record.levelno)
        return f"{prefix}worker[{os.getpid()}]: {record.getMessage()}"


AVIF_FAST_EFFORT = 0

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


class PreviewRequest(msgspec.Struct, omit_defaults=True):
    path: str
    quality: int
    maxsize: int
    maxzoom: float


class PreviewResponse(msgspec.Struct, omit_defaults=True):
    ok: bool
    mime: str | None = None
    backend: str | None = None
    timings: list[float] | None = None
    error: str | None = None
    stderr: str | None = None
    width: int | None = None
    height: int | None = None


_enc = msgspec.json.Encoder()
_dec_req = msgspec.json.Decoder(PreviewRequest)


def _read_exactly(f, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _read_request() -> tuple[PreviewRequest, bytes] | None:
    try:
        header = _read_exactly(sys.stdin.buffer, 8)
    except EOFError:
        return None
    json_size, data_size = struct.unpack("<II", header)
    meta_raw = _read_exactly(sys.stdin.buffer, json_size)
    data = b""
    if data_size:
        data = _read_exactly(sys.stdin.buffer, data_size)
    req = _dec_req.decode(meta_raw)
    return req, data


# Raw stdout buffer reserved for the binary protocol once main() redirects
# Python-level stdout to stderr. None means "use sys.stdout.buffer as-is"
# (CLI single-shot mode, where real stdout is wanted).
_protocol_out = None


def _write_response(resp: PreviewResponse, payload: bytes) -> None:
    out = _protocol_out if _protocol_out is not None else sys.stdout.buffer
    meta_bytes = _enc.encode(resp)
    packet = struct.pack("<II", len(meta_bytes), len(payload)) + meta_bytes + payload
    checksum = blake3(packet).digest()
    out.write(checksum)
    out.write(packet)
    out.flush()


def dispatch(path, quality, maxsize, maxzoom, data=None):
    backend = "unknown"
    try:
        if data:
            backend = "pyvips"
            return process_image_buffer(
                data, quality=quality, maxsize=maxsize, maxzoom=maxzoom
            )
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
        img = img.autorot()
    except pyvips.error.Error:
        return None
    else:
        return img.width, img.height


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
        try:
            # stdin=DEVNULL is critical: ffmpeg must not inherit the worker's
            # stdin, which carries the framed request protocol. An inherited
            # stdin lets ffmpeg eat protocol bytes and, if the worker is
            # killed mid-conversion, keeps the orphaned ffmpeg holding the
            # pipe open so the parent's proc.wait() hangs forever.
            subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                check=True,
                shell=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            shell_cmd = shlex.join(cmd)
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            if stderr:
                raise RuntimeError(
                    f"ffmpeg failed (exit {e.returncode}): {shell_cmd}\n{stderr}"
                ) from e
            raise RuntimeError(
                f"ffmpeg failed (exit {e.returncode}): {shell_cmd}"
            ) from e
        with Path(tmp_path).open("rb") as f:
            return f.read()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def process_image_pyvips(path, *, maxsize, quality):
    t_start = perf_counter()
    suffix = path.suffix.lower()

    # HEIC/HEIF: ffmpeg handles tile assembly and HDR correctly;
    # skip pyvips entirely.
    if suffix in (".heic", ".heif"):
        heic_dims = _get_image_dimensions(path)
        width, height = heic_dims or (None, None)
        ret = _image_via_ffmpeg(path, maxsize, quality)
        t_end = perf_counter()
        return ret, PreviewResponse(
            ok=True,
            mime="image/avif",
            backend="ffmpeg",
            timings=[round((t_end - t_start) * 1000, 1)],
            width=width,
            height=height,
        )

    # Other image formats: pyvips first, ffmpeg fallback.
    load_opts = {"access": "sequential"}
    orig_w = orig_h = None
    try:
        img = pyvips.Image.new_from_file(str(path), **load_opts)
        img = img.autorot()
        orig_w, orig_h = img.width, img.height
        scale = min(maxsize / img.width, maxsize / img.height, 1.0)
        if scale < 1.0:
            img = img.resize(scale)
        ret = img.write_to_buffer(
            ".avif",
            Q=quality,
            effort=AVIF_FAST_EFFORT,
            keep="none",
        )
        backend = "pyvips"
    except pyvips.error.Error:
        orig_w, orig_h = None, None
        ret = _image_via_ffmpeg(path, maxsize, quality)
        backend = "ffmpeg"
    t_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend=backend,
        timings=[round((t_end - t_start) * 1000, 1)],
        width=orig_w,
        height=orig_h,
    )


def process_image_buffer(data: bytes, *, quality, maxsize, maxzoom):
    _ = maxzoom
    t_start = perf_counter()
    img = pyvips.Image.new_from_buffer(data, "")
    img = img.autorot()
    orig_w, orig_h = img.width, img.height
    scale = min(maxsize / img.width, maxsize / img.height, 1.0)
    if scale < 1.0:
        img = img.resize(scale)
    ret = img.write_to_buffer(
        ".avif",
        Q=quality,
        effort=AVIF_FAST_EFFORT,
        keep="none",
    )
    t_end = perf_counter()

    return ret, PreviewResponse(
        ok=True,
        mime="image/avif",
        backend="pyvips",
        timings=[round((t_end - t_start) * 1000, 1)],
        width=orig_w,
        height=orig_h,
    )


def process_pdf(path, *, maxsize, maxzoom, quality, page_number=0):
    t_load_start = perf_counter()
    with pymupdf.open(path) as pdf:
        page = pdf.load_page(page_number)
        w, h = page.rect[2:4]
        zoom = min(maxsize / w, maxsize / h, maxzoom)
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        t_load_end = perf_counter()

        t_save_start = perf_counter()
        img = pyvips.Image.new_from_memory(
            pix.samples_mv, pix.width, pix.height, pix.n, "uchar"
        )
    ret = img.write_to_buffer(".avif", Q=quality, effort=AVIF_FAST_EFFORT, keep="none")
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
        width=round(w),
        height=round(h),
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
        # Capture display dimensions before resize (accounting for rotation)
        disp_w = frame.width
        disp_h = frame.height
        if frame.rotation in (90, 270):
            disp_w, disp_h = disp_h, disp_w
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
                except Exception:
                    logger.exception("Error rotating video frame by 180°")
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
                except Exception:
                    logger.exception(
                        "Error rotating video frame by %s°", frame.rotation
                    )

        # libsvtav1 rejects full-range JPEG-style YUV pixel formats such as
        # yuvj420p, so normalize them before opening the encoder.
        if frame.format.name.startswith("yuvj"):
            frame = frame.reformat(format="yuv420p")
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
            raise TypeError("failed to initialize AV1 video stream")
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
        width=disp_w,
        height=disp_h,
    )
    del imgdata, istream, ostream, icc, occ, frame
    gc.collect()
    return ret, resp


def _run_once() -> None:
    if len(sys.argv) != 5:
        sys.stderr.write(f"Usage: {sys.argv[0]} <path> <quality> <maxsize> <maxzoom>\n")
        sys.exit(1)

    path = Path(sys.argv[1])
    quality = int(sys.argv[2])
    maxsize = int(sys.argv[3])
    maxzoom = float(sys.argv[4])
    result, _ = dispatch(path, quality, maxsize, maxzoom)
    if result:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()


def _run_loop() -> None:
    while True:
        result = _read_request()
        if result is None:
            return
        req, data = result
        stderr_capture = io.StringIO()
        handler = logging.StreamHandler(stderr_capture)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            with contextlib.redirect_stderr(stderr_capture):
                result, resp = dispatch(
                    Path(req.path), req.quality, req.maxsize, req.maxzoom, data
                )
            if not resp.ok:
                captured = stderr_capture.getvalue().strip()
                if captured:
                    resp = PreviewResponse(
                        ok=False,
                        backend=resp.backend,
                        error=resp.error,
                        stderr=captured,
                    )
            _write_response(resp, result or b"")
        except Exception as e:
            logger.exception("Preview worker error for %s", req.path)
            captured = stderr_capture.getvalue().strip()
            _write_response(
                PreviewResponse(ok=False, error=str(e), stderr=captured or None), b""
            )
        finally:
            root_logger.removeHandler(handler)
            handler.close()


def main() -> None:
    # Configure all log output to stderr before any imports that may emit
    # logs. stderr is inherited by the parent, so this lands in the server
    # log, formatted like the main process and tagged with the worker pid.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_WorkerLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # pyvips is chatty at INFO ("threadpool completed ..." per operation).
    logging.getLogger("pyvips").setLevel(logging.WARNING)
    try:
        config.load_config()
    except Exception:
        logger.exception("preview-worker failed to load config at startup")
    if len(sys.argv) > 1:
        _run_once()
        return
    # The command channel is a binary protocol on fd 1. Anything printed to
    # stdout by Python code (e.g. a library emitting a warning via print())
    # would corrupt the protocol, so redirect Python-level stdout to stderr
    # (the server log) and keep the raw buffer solely for protocol traffic.
    global _protocol_out
    _protocol_out = sys.stdout.buffer
    sys.stdout = sys.stderr
    # Eagerly import heavy modules before signalling readiness so the parent
    # does not hand us a request while we are still initialising.
    _protocol_out.write(b"\x01")
    _protocol_out.flush()
    _run_loop()


if __name__ == "__main__":
    main()
