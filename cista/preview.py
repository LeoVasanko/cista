import asyncio
import io
from pathlib import PurePosixPath
from urllib.parse import unquote

from PIL import Image
from sanic import Blueprint, raw
from sanic.exceptions import Forbidden, NotFound
from sanic.log import logger

from cista import config
from cista.util.filename import sanitize

bp = Blueprint("preview", url_prefix="/preview")


@bp.get("/<path:path>")
async def preview(req, path):
    """Preview a file"""
    width = int(req.query_string) if req.query_string else 1024
    rel = PurePosixPath(sanitize(unquote(path)))
    path = config.config.path / rel
    if not path.is_file():
        raise NotFound("File not found")
    size = path.lstat().st_size
    if size > 20 * 10**6:
        raise Forbidden("File too large")
    img = await asyncio.get_event_loop().run_in_executor(
        req.app.ctx.threadexec, process_image, path, width
    )
    return raw(img, content_type="image/webp")


def process_image(path, maxsize):
    img = Image.open(path)
    w, h = img.size
    img.thumbnail((min(w, maxsize), min(h, maxsize)))
    # Fix rotation based on EXIF data
    try:
        rotate_values = {3: 180, 6: 270, 8: 90}
        exif = img._getexif()
        if exif:
            orientation = exif.get(274)
            if orientation in rotate_values:
                logger.debug(f"Rotating preview {path} by {rotate_values[orientation]}")
                img = img.rotate(rotate_values[orientation], expand=True)
    except Exception as e:
        logger.error(f"Error rotating preview image: {e}")
    # Save as webp
    imgdata = io.BytesIO()
    img.save(imgdata, format="webp", quality=70, method=6)
    return imgdata.getvalue()
