import asyncio
import gc
import io
import mimetypes
import urllib.parse
from pathlib import PurePosixPath
from urllib.parse import unquote
from wsgiref.handlers import format_date_time

import av
import av.datasets
import fitz  # PyMuPDF
from PIL import Image
from sanic import Blueprint, empty, raw
from sanic.exceptions import NotFound
from sanic.log import logger

from cista import config
from cista.util.filename import sanitize

DISPLAYMATRIX = av.stream.SideData.DISPLAYMATRIX

bp = Blueprint("preview", url_prefix="/preview")


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    maxsize = int(req.args.get("px", 1024))
    maxzoom = float(req.args.get("zoom", 2.0))
    quality = int(req.args.get("q", 40))
    rel = PurePosixPath(sanitize(unquote(path)))
    path = config.config.path / rel
    stat = path.lstat()
    etag = config.derived_secret(
        "preview", rel, stat.st_mtime_ns, quality, maxsize, maxzoom
    ).hex()
    savename = PurePosixPath(path.name).with_suffix(".webp")
    headers = {
        "etag": etag,
        "last-modified": format_date_time(stat.st_mtime),
        "cache-control": "max-age=604800, immutable"
        + ("" if config.config.public else ", private"),
        "content-type": "image/webp",
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
    if mimetypes.guess_type(path.name)[0].startswith("video/"):
        return process_video(path, quality=quality, maxsize=maxsize)
    return process_image(path, quality=quality, maxsize=maxsize)


def process_image(path, *, maxsize, quality):
    img = Image.open(path)
    w, h = img.size
    img.thumbnail((min(w, maxsize), min(h, maxsize)))
    # Fix rotation based on EXIF data
    try:
        rotate_values = {3: 180, 6: 270, 8: 90}
        orientation = img._getexif().get(274)
        if orientation in rotate_values:
            logger.debug(f"Rotating preview {path} by {rotate_values[orientation]}")
            img = img.rotate(rotate_values[orientation], expand=True)
    except AttributeError:
        ...
    except Exception as e:
        logger.error(f"Error rotating preview image: {e}")
    # Save as webp
    imgdata = io.BytesIO()
    img.save(imgdata, format="webp", quality=quality, method=4)
    return imgdata.getvalue()


def process_pdf(path, *, maxsize, maxzoom, quality, page_number=0):
    pdf = fitz.open(path)
    page = pdf.load_page(page_number)
    w, h = page.rect[2:4]
    zoom = min(maxsize / w, maxsize / h, maxzoom)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return pix.pil_tobytes(format="webp", quality=quality, method=4)


def process_video(path, *, maxsize, quality):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        rot = stream.side_data and stream.side_data.get(DISPLAYMATRIX) or 0
        container.seek(container.duration // 8)
        img = next(container.decode(stream)).to_image()
        del stream

    img.thumbnail((maxsize, maxsize))
    imgdata = io.BytesIO()
    if rot:
        img = img.rotate(rot, expand=True)
    img.save(imgdata, format="webp", quality=quality, method=4)
    del img
    ret = imgdata.getvalue()
    del imgdata
    gc.collect()
    return ret
