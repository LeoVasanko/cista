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
from sanic import Blueprint, empty, raw
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import config
from cista.util.filename import sanitize

pillow_heif.register_heif_opener()

bp = Blueprint("preview", url_prefix="/preview")


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    maxsize = int(req.args.get("px", 1024))
    maxzoom = float(req.args.get("zoom", 2.0))
    quality = int(req.args.get("q", 60))
    rel = PurePosixPath(sanitize(unquote(path)))
    path = config.config.path / rel
    stat = path.lstat()
    etag = config.derived_secret(
        "preview", rel, stat.st_mtime_ns, quality, maxsize, maxzoom
    ).hex()
    savename = PurePosixPath(path.name).with_suffix(".avif")
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

    if not path.is_file():
        raise NotFound("File not found")

    img = await asyncio.get_event_loop().run_in_executor(
        req.app.ctx.threadexec, dispatch, path, quality, maxsize, maxzoom
    )
    return raw(img, headers=headers)


def dispatch(path, quality, maxsize, maxzoom):
    if path.suffix.lower() in (".pdf", ".xps", ".epub", ".mobi"):
        return process_pdf(path, quality=quality, maxsize=maxsize, maxzoom=maxzoom)
    type, _ = mimetypes.guess_type(path.name)
    if type and type.startswith("video/"):
        return process_video(path, quality=quality, maxsize=maxsize)
    return process_image(path, quality=quality, maxsize=maxsize)


def process_image(path, *, maxsize, quality):
    t_load_start = perf_counter()
    img = Image.open(path)
    # Force decode to include I/O in load timing
    img.load()
    t_load_end = perf_counter()
    # Resize
    orig_w, orig_h = img.size
    t_proc_start = perf_counter()
    img.thumbnail((min(orig_w, maxsize), min(orig_h, maxsize)))
    t_proc_end = perf_counter()
    # Save as AVIF
    imgdata = io.BytesIO()
    t_save_start = perf_counter()
    img.save(imgdata, format="avif", quality=quality, speed=10, max_threads=1)
    t_save_end = perf_counter()

    ret = imgdata.getvalue()

    load_ms = (t_load_end - t_load_start) * 1000
    proc_ms = (t_proc_end - t_proc_start) * 1000
    save_ms = (t_save_end - t_save_start) * 1000
    logger.debug(
        "Preview image %s: load=%.1fms process=%.1fms save=%.1fms out=%.1fKB",
        path.name,
        load_ms,
        proc_ms,
        save_ms,
        len(ret) / 1024,
    )

    return ret


def process_pdf(path, *, maxsize, maxzoom, quality, page_number=0):
    t_load_start = perf_counter()
    pdf = fitz.open(path)
    page = pdf.load_page(page_number)
    w, h = page.rect[2:4]
    zoom = min(maxsize / w, maxsize / h, maxzoom)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)  # type: ignore[attr-defined]
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

        # Simple rotation detection and logging
        if frame.rotation:
            try:
                fplanes = frame.to_ndarray()
                # Split into Y, U, V planes of proper dimensions
                planes = [
                    fplanes[: frame.height],
                    fplanes[frame.height : frame.height + frame.height // 4].reshape(
                        frame.height // 2, frame.width // 2
                    ),
                    fplanes[frame.height + frame.height // 4 :].reshape(
                        frame.height // 2, frame.width // 2
                    ),
                ]
                # Rotate
                planes = [np.rot90(p, frame.rotation // 90) for p in planes]
                # Restore PyAV format
                planes = np.hstack([p.flat for p in planes]).reshape(
                    -1, planes[0].shape[1]
                )
                frame = av.VideoFrame.from_ndarray(planes, format=frame.format.name)
                del planes, fplanes
            except Exception as e:
                if "not yet supported" in str(e):
                    logger.warning(
                        f"Not rotating {path.name} preview image by {frame.rotation}°:\n  PyAV: {e}"
                    )
                else:
                    logger.exception(f"Error rotating video frame: {e}")
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
