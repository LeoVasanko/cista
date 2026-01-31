import asyncio
import gc
import io
import mimetypes
import urllib.parse
from pathlib import PurePosixPath
from time import perf_counter
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import av
import fitz  # PyMuPDF
import numpy as np
import pillow_heif
from PIL import Image
from sanic import Blueprint, empty, raw, redirect
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import auth, config
from cista.util.filename import sanitize

pillow_heif.register_heif_opener()

bp = Blueprint("preview", url_prefix="/preview")


@bp.on_request
async def verify_preview(request):
    """Verify access to preview routes."""
    await auth.verify(request)


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


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    maxsize = int(req.args.get("px", 1024))
    maxzoom = float(req.args.get("zoom", 2.0))
    quality = int(req.args.get("q", 60))
    rel = PurePosixPath(sanitize(unquote(path)))
    filepath = config.config.path / rel
    stat = filepath.lstat()
    etag = config.derived_secret(
        "preview", rel, stat.st_mtime_ns, quality, maxsize, maxzoom
    ).hex()
    savename = PurePosixPath(filepath.name).with_suffix(".avif")
    headers = {
        "etag": etag,
        "last-modified": format_date_time(stat.st_mtime),
        "cache-control": "max-age=604800, immutable"
        + ("" if config.config.public else ", private"),
        "content-type": "image/avif",
        "content-disposition": f"inline; filename*=UTF-8''{urllib.parse.quote(savename.as_posix())}",
    }
    if req.headers.if_none_match == etag:
        # The client has it cached, respond 304 Not Modified
        return empty(304, headers=headers)

    if not filepath.is_file():
        raise NotFound("File not found")

    img = await asyncio.get_event_loop().run_in_executor(
        req.app.ctx.threadexec, dispatch, filepath, quality, maxsize, maxzoom
    )
    if not img:
        # Preview generation failed, redirect to the file itself
        return redirect(f"/files/{path}", status=303)
    return raw(img, headers=headers)


def dispatch(path, quality, maxsize, maxzoom):
    try:
        if path.suffix.lower() in (".pdf", ".xps", ".epub", ".mobi"):
            return process_pdf(path, quality=quality, maxsize=maxsize, maxzoom=maxzoom)
        type, _ = mimetypes.guess_type(path.name)
        if type and type.startswith("video/"):
            return process_video(path, quality=quality, maxsize=maxsize)
        return process_image(path, quality=quality, maxsize=maxsize)
    except ValueError as e:
        logger.warning(f"Cannot generate preview for {path.name}: {e}")
    except Exception as e:
        logger.exception(f"Error generating preview for {path.name}: {e}")


def process_image(path, *, maxsize, quality):
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
        img.save(imgdata, format="avif", quality=quality, speed=10, max_threads=1)

    t_end = perf_counter()
    ret = imgdata.getvalue()

    load_ms = (t_proc - t_load) * 1000
    proc_ms = (t_save - t_proc) * 1000
    save_ms = (t_end - t_save) * 1000
    logger.debug(
        "Preview image %s: load=%.1fms process=%.1fms save=%.1fms",
        path.name,
        load_ms,
        proc_ms,
        save_ms,
    )

    return ret


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
    ret = pix.pil_tobytes(format="avif", quality=quality, speed=10, max_threads=1)
    t_save_end = perf_counter()

    logger.debug(
        "Preview pdf %s: load+render=%.1fms save=%.1fms",
        path.name,
        (t_load_end - t_load_start) * 1000,
        (t_save_end - t_save_start) * 1000,
    )
    return ret


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
        av.open(str(path)) as icontainer,
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

    # Capture frame dimensions before cleanup
    ret = imgdata.getvalue()
    logger.debug(
        "Preview video %s: load+decode=%.1fms save=%.1fms",
        path.name,
        (t_load_end - t_load_start) * 1000,
        (t_save_end - t_save_start) * 1000,
    )
    del imgdata, istream, ostream, icc, occ, frame
    gc.collect()
    return ret
