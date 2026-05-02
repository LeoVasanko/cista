import asyncio
import contextlib
import mimetypes
import os
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote as url_quote
from urllib.parse import unquote, urlparse
from wsgiref.handlers import format_date_time

from sanic import Blueprint, HTTPResponse, empty, json
from sanic.exceptions import BadRequest, NotFound

from cista import auth, config, sharefs, watching
from cista.api import fileserver
from cista.util import filename

bp = Blueprint("fileserver", url_prefix="/files")

_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_FILE_CHUNK_SIZE = 1 << 20

_DAV_NS = "DAV:"
ET.register_namespace("D", _DAV_NS)


def _dav_tag(name: str) -> str:
    return f"{{{_DAV_NS}}}{name}"


@bp.on_request
async def verify_fileserver(request):
    """Verify access to file server routes."""
    await auth.verify(request)


@bp.put("/<name:path>")
async def upload_file_chunk(request, name):
    auth.ensure_write_allowed(request)
    body = request.body
    header = request.headers.get("content-range")
    if header:
        start, end, total = _parse_content_range(header, len(body))
    else:
        start = 0
        end = len(body)
        total = end

    rel, path = _safe_relpath(name, request=request)
    rel_name = rel.as_posix()
    upload_info = await asyncio.to_thread(
        fileserver.upload_info,
        rel_name,
        start,
        body,
        total,
    )
    extras = []
    chunk_len = end - start
    whole_file = start == 0 and end == total
    if not whole_file:
        start_mib = _to_mib_int(start)
        chunk_mib = _to_mib_int(chunk_len)
        # Keep range logs compact for fixed-size upload blocks.
        if chunk_mib == 16:
            extras.append(f"{start_mib}MiB")
        else:
            extras.append(f"{start_mib}+{chunk_mib}MiB")
    if upload_info.get("created"):
        extras.append(f"created {_to_mib_int(total)}MiB")
    size_before = upload_info.get("size_before")
    size_after = upload_info.get("size_after")
    if size_before is not None and size_after is not None and size_before != size_after:
        extras.append("resized")
    request.ctx.log_extra = " ".join(extras) if extras else None
    real_rel = PurePosixPath(path.relative_to(config.config.path.resolve()).as_posix())
    watching.notify_change(real_rel, *real_rel.parents)
    return json(
        {
            "status": "ack",
            "req": {
                "name": rel_name,
                "size": total,
                "start": start,
                "end": end,
            },
        }
    )


@bp.delete("/<name:path>")
async def delete_file(request, name):
    auth.ensure_write_allowed(request)
    rel, path = _safe_relpath(name, request=request)
    if not rel.parts:
        raise BadRequest("Refusing to delete root folder")

    def _delete():
        if not path.exists():
            raise NotFound(f"File not found: {name}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    await asyncio.to_thread(_delete)
    real_rel = PurePosixPath(path.relative_to(config.config.path.resolve()).as_posix())
    watching.notify_change(real_rel, *real_rel.parents)
    return empty(status=204)


@bp.route("/<name:path>", methods=["MKCOL"])
async def create_folder(request, name):
    auth.ensure_write_allowed(request)
    rel, path = _safe_relpath(name, request=request)
    if not rel.parts:
        raise BadRequest("Refusing to create root folder")
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=False)
    real_rel = PurePosixPath(path.relative_to(config.config.path.resolve()).as_posix())
    watching.notify_change(real_rel, *real_rel.parents)
    return empty(status=201)


@bp.post("/", name="post_root", strict_slashes=False)
@bp.post("/<name:path>", name="post_path")
async def copy_or_move(request, name=""):
    auth.ensure_write_allowed(request)
    provided_args = set(request.args.keys())
    if not provided_args:
        raise BadRequest("No query arguments passed")

    allowed_args = {"cp", "mv"}
    unknown_args = sorted(provided_args - allowed_args)
    if unknown_args:
        raise BadRequest(f"Unknown query parameter(s): {', '.join(unknown_args)}")

    mv_vals = request.args.getlist("mv")
    cp_vals = request.args.getlist("cp")

    mv_keys: list[str] = []
    for value in mv_vals:
        mv_keys.extend(k for k in value.split() if k)

    cp_keys: list[str] = []
    for value in cp_vals:
        cp_keys.extend(k for k in value.split() if k)

    if not mv_keys and not cp_keys:
        raise BadRequest("No keys given")

    dst_rel, dst_abs = _safe_relpath(name, request=request)

    dst_exists = dst_abs.exists()
    dst_is_dir = dst_exists and dst_abs.is_dir()

    ordered_keys = cp_keys + mv_keys
    key_paths = _get_key_paths(request, set(ordered_keys))
    missing = [key for key in ordered_keys if key not in key_paths]
    if missing:
        raise NotFound("Files not found", context={"missing": missing})

    # Validate target shape/type before mutating anything.
    for _op_name, op_keys in (("cp", cp_keys), ("mv", mv_keys)):
        if len(op_keys) > 1 and not dst_is_dir:
            raise BadRequest(
                "Destination must be an existing directory for multiple keys"
            )
        if not op_keys:
            continue
        if not dst_is_dir:
            if not dst_rel.parts:
                raise BadRequest("Destination file path is required")
            parent_abs = dst_abs.parent
            if not parent_abs.is_dir():
                raise BadRequest("Destination parent folder does not exist")
            if dst_exists and dst_abs.is_file():
                for key in op_keys:
                    src_abs = _resolve_from_relpath(key_paths[key])
                    if src_abs.is_dir():
                        raise BadRequest(
                            "Cannot move/copy a directory to an existing file"
                        )

    changed: set[PurePosixPath] = set()
    completed: list[dict[str, str]] = []

    class _FileOpError(Exception):
        def __init__(self, op_name: str, key: str, error: Exception):
            self.op_name = op_name
            self.key = key
            self.error = error
            super().__init__(str(error))

    def _apply():
        for op_name, op_keys in (("cp", cp_keys), ("mv", mv_keys)):
            for key in op_keys:
                try:
                    src_rel = key_paths[key]
                    src_abs = _resolve_from_relpath(src_rel, request=request)

                    if dst_is_dir:
                        dst_item_rel = (
                            dst_rel / src_rel.name
                            if dst_rel.parts
                            else PurePosixPath(src_rel.name)
                        )
                    else:
                        dst_item_rel = dst_rel

                    dst_item_abs = _resolve_from_relpath(dst_item_rel, request=request)

                    if op_name == "mv":
                        # A no-op rename should still return success.
                        if src_abs != dst_item_abs:
                            shutil.move(src_abs, dst_item_abs)
                        changed.add(src_rel)
                        changed.add(src_rel.parent)
                    elif src_abs.is_dir():
                        shutil.copytree(
                            src_abs,
                            dst_item_abs,
                            dirs_exist_ok=True,
                            ignore_dangling_symlinks=True,
                        )
                    else:
                        shutil.copy2(src_abs, dst_item_abs)

                    changed.add(dst_item_rel)
                    changed.add(dst_item_rel.parent)
                    completed.append({"op": op_name, "key": key})
                except Exception as e:
                    raise _FileOpError(op_name, key, e) from e

    try:
        await asyncio.to_thread(_apply)
    except _FileOpError as e:
        raise BadRequest(
            "File operation failed after partial progress",
            context={
                "failed_op": e.op_name,
                "failed_key": e.key,
                "error": str(e.error),
                "completed": completed,
            },
        ) from e

    notify_paths = [p for p in changed if p.parts]
    if notify_paths:
        real_notify_paths: list[PurePosixPath] = []
        for p in notify_paths:
            real_abs = _resolve_from_relpath(p, request=request)
            real_notify_paths.append(
                PurePosixPath(
                    real_abs.relative_to(config.config.path.resolve()).as_posix()
                )
            )
        watching.notify_change(*real_notify_paths)

    return json(
        {
            "status": "ack",
            "counts": {"cp": len(cp_keys), "mv": len(mv_keys)},
        }
    )


@bp.get("/<name:path>")
async def get_file(request, name=""):
    return await _send_static_file(request, name, head_only=False)


@bp.head("/<name:path>")
async def head_file(request, name=""):
    return await _send_static_file(request, name, head_only=True)


@bp.route("/", methods=["OPTIONS"], name="options_root", strict_slashes=False)
@bp.route("/<name:path>", methods=["OPTIONS"], name="options_path")
async def dav_options(request, name=""):
    return HTTPResponse(
        status=200,
        headers={
            "Allow": "OPTIONS, GET, HEAD, PUT, DELETE, MKCOL, COPY, MOVE, PROPFIND, POST",
            "DAV": "1",
            "MS-Author-Via": "DAV",
        },
    )


@bp.route("/", methods=["PROPFIND"], name="propfind_root", strict_slashes=False)
@bp.route("/<name:path>", methods=["PROPFIND"], name="propfind_path")
async def dav_propfind(request, name=""):
    rel, path = _safe_relpath(name, request=request)
    token = auth.request_share_token(request)
    if token is not None and not rel.parts:
        base = config.config.path.resolve()
        entries = [_propfind_entry(PurePosixPath(), base)]
        depth = request.headers.get("depth", "1").strip()
        if depth == "infinity":
            return HTTPResponse(status=403)
        if depth == "1":
            for root in sharefs.build_share_roots(token):
                child_abs = (base / root.real_rel).resolve()
                if not child_abs.exists() or not child_abs.is_relative_to(base):
                    continue
                with contextlib.suppress(OSError):
                    entries.append(
                        _propfind_entry(PurePosixPath(root.alias), child_abs)
                    )
        return HTTPResponse(
            body=_build_propfind_xml(entries),
            status=207,
            content_type='application/xml; charset="utf-8"',
        )

    if not path.exists():
        raise NotFound(f"Not found: {name}")
    depth = request.headers.get("depth", "1").strip()
    if depth == "infinity":
        return HTTPResponse(status=403)
    entries = await asyncio.to_thread(_collect_propfind_entries, rel, path, depth)
    return HTTPResponse(
        body=_build_propfind_xml(entries),
        status=207,
        content_type='application/xml; charset="utf-8"',
    )


@bp.route("/", methods=["COPY"], name="copy_root", strict_slashes=False)
@bp.route("/<name:path>", methods=["COPY"], name="copy_path")
async def dav_copy(request, name=""):
    auth.ensure_write_allowed(request)
    dest_header = request.headers.get("destination")
    if not dest_header:
        raise BadRequest("Missing Destination header")
    overwrite = request.headers.get("overwrite", "T").strip().upper() != "F"
    _src_rel, src_abs = _safe_relpath(name, request=request)
    dst_rel, dst_abs = _parse_webdav_destination(dest_header, request=request)
    if auth.request_share_token(request) is not None and not dst_rel.parts:
        raise BadRequest("Destination cannot be virtual root")
    request.ctx.log_extra = f"→ {dst_rel}"
    if not src_abs.exists():
        raise NotFound(f"Source not found: {name}")
    if src_abs == dst_abs:
        raise BadRequest("Source and destination are the same")
    dst_existed = dst_abs.exists()
    if dst_existed and not overwrite:
        return HTTPResponse(status=412)
    if not dst_abs.parent.is_dir():
        return HTTPResponse(status=409)

    def _do_copy():
        if dst_existed:
            shutil.rmtree(dst_abs) if dst_abs.is_dir() else dst_abs.unlink()
        if src_abs.is_dir():
            shutil.copytree(src_abs, dst_abs, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(src_abs, dst_abs)

    await asyncio.to_thread(_do_copy)
    real_dst_rel = PurePosixPath(
        dst_abs.relative_to(config.config.path.resolve()).as_posix()
    )
    watching.notify_change(real_dst_rel, *real_dst_rel.parents)
    return HTTPResponse(status=201 if not dst_existed else 204)


@bp.route("/", methods=["MOVE"], name="move_root", strict_slashes=False)
@bp.route("/<name:path>", methods=["MOVE"], name="move_path")
async def dav_move(request, name=""):
    auth.ensure_write_allowed(request)
    dest_header = request.headers.get("destination")
    if not dest_header:
        raise BadRequest("Missing Destination header")
    overwrite = request.headers.get("overwrite", "T").strip().upper() != "F"
    _src_rel, src_abs = _safe_relpath(name, request=request)
    dst_rel, dst_abs = _parse_webdav_destination(dest_header, request=request)
    if auth.request_share_token(request) is not None and not dst_rel.parts:
        raise BadRequest("Destination cannot be virtual root")
    request.ctx.log_extra = f"→ {dst_rel}"
    if not src_abs.exists():
        raise NotFound(f"Source not found: {name}")
    if src_abs == dst_abs:
        return HTTPResponse(status=204)
    dst_existed = dst_abs.exists()
    if dst_existed and not overwrite:
        return HTTPResponse(status=412)
    if not dst_abs.parent.is_dir():
        return HTTPResponse(status=409)

    def _do_move():
        if dst_existed:
            shutil.rmtree(dst_abs) if dst_abs.is_dir() else dst_abs.unlink()
        shutil.move(src_abs, dst_abs)

    await asyncio.to_thread(_do_move)
    real_src_rel = PurePosixPath(
        src_abs.relative_to(config.config.path.resolve()).as_posix()
    )
    real_dst_rel = PurePosixPath(
        dst_abs.relative_to(config.config.path.resolve()).as_posix()
    )
    watching.notify_change(
        real_src_rel, *real_src_rel.parents, real_dst_rel, *real_dst_rel.parents
    )
    return HTTPResponse(status=201 if not dst_existed else 204)


def _parse_content_range(header: str, body_len: int) -> tuple[int, int, int]:
    m = _CONTENT_RANGE_RE.fullmatch(header.strip())
    if m is None:
        raise BadRequest("Invalid Content-Range format")
    start, end_inclusive, total = (int(v) for v in m.groups())
    if total <= 0:
        raise BadRequest("Invalid Content-Range total size")
    if start > end_inclusive:
        raise BadRequest("Invalid Content-Range range")
    if end_inclusive >= total:
        raise BadRequest("Content-Range exceeds total size")
    expected_len = end_inclusive - start + 1
    if expected_len != body_len:
        raise BadRequest(
            f"Content length mismatch for range: expected {expected_len}, got {body_len}"
        )
    return start, end_inclusive + 1, total


def _to_mib_int(value_bytes: int) -> int:
    return round(value_bytes / (1 << 20))


def _safe_relpath(path: str, *, request=None) -> tuple[PurePosixPath, Path]:
    """Resolve a user path under storage root and enforce containment."""
    token = auth.request_share_token(request) if request is not None else None
    if token is not None:
        vrel, _rrel, resolved, is_root = sharefs.resolve_virtual_path(token, path)
        if is_root:
            return vrel, config.config.path.resolve()
        return vrel, resolved

    base = config.config.path.resolve()
    try:
        sanitized = filename.sanitize(unquote(path))
    except ValueError as e:
        raise BadRequest(f"Invalid path: {e}") from e
    resolved = (base / sanitized).resolve()
    if not resolved.is_relative_to(base):
        raise BadRequest("Invalid path")
    rel = PurePosixPath(resolved.relative_to(base).as_posix())
    return rel, resolved


def _resolve_from_relpath(rel: PurePosixPath, *, request=None) -> Path:
    """Resolve a relative path under storage root and enforce containment."""
    token = auth.request_share_token(request) if request is not None else None
    if token is not None:
        return sharefs.resolve_virtual_rel_to_real(token, rel)

    base = config.config.path.resolve()
    resolved = (base / rel).resolve()
    if not resolved.is_relative_to(base):
        raise BadRequest("Invalid path")
    return resolved


async def _send_static_file(request, name: str, *, head_only: bool):
    _, path = _safe_relpath(name, request=request)

    try:
        st = await asyncio.to_thread(path.stat)
    except FileNotFoundError:
        raise NotFound(f"File not found: {name}") from None
    if path.is_dir():
        raise NotFound(f"Not a file: {name}")

    size = st.st_size
    start = 0
    end_excl = size
    status = 200

    range_header = request.headers.get("range")
    if range_header is not None:
        parsed = _parse_range_header(range_header, size)
        if parsed is None:
            return empty(
                status=416,
                headers={
                    "accept-ranges": "bytes",
                    "content-range": f"bytes */{size}",
                },
            )
        start, end_excl = parsed
        status = 206

    length = end_excl - start
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        "accept-ranges": "bytes",
        "cache-control": "no-cache",
        "content-length": str(length),
        "content-type": mime,
        "last-modified": format_date_time(st.st_mtime),
    }
    if status == 206:
        headers["content-range"] = f"bytes {start}-{end_excl - 1}/{size}"

    if head_only:
        return empty(status=status, headers=headers)

    res = await request.respond(status=status, headers=headers)
    fd = await asyncio.to_thread(os.open, path, os.O_RDONLY)
    try:
        pos = start
        while pos < end_excl:
            chunk = await asyncio.to_thread(
                os.pread,
                fd,
                min(_FILE_CHUNK_SIZE, end_excl - pos),
                pos,
            )
            if not chunk:
                break
            pos += len(chunk)
            await res.send(chunk)
    finally:
        await asyncio.to_thread(os.close, fd)


def _parse_range_header(header: str, size: int) -> tuple[int, int] | None:
    value = header.strip()
    if "," in value:
        return None
    m = _RANGE_RE.fullmatch(value)
    if m is None:
        return None

    start_s, end_s = m.groups()
    if not start_s and not end_s:
        return None

    if start_s:
        start = int(start_s)
        if start >= size:
            return None
        end_inclusive = int(end_s) if end_s else (size - 1)
        if end_inclusive < start:
            return None
        end_inclusive = min(end_inclusive, size - 1)
        return start, end_inclusive + 1

    suffix_len = int(end_s)
    if suffix_len <= 0:
        return None
    if suffix_len >= size:
        return 0, size
    start = size - suffix_len
    return start, size


def _get_key_paths(request, wanted: set[str]) -> dict[str, PurePosixPath]:
    """Map file keys to their current relative filesystem paths."""
    token = auth.request_share_token(request)
    if token is not None:
        return sharefs.key_paths_for_token(token, wanted)

    loc = PurePosixPath()
    ret: dict[str, PurePosixPath] = {}
    with watching.state.lock:
        root = watching.state.root
        for f in root:
            loc = PurePosixPath(*loc.parts[: f.level - 1]) / f.name
            if f.key in wanted and f.key not in ret:
                ret[f.key] = loc
                if len(ret) == len(wanted):
                    break
    return ret


# ---------------------------------------------------------------------------
# WebDAV helpers
# ---------------------------------------------------------------------------


def _parse_webdav_destination(
    dest_header: str, *, request=None
) -> tuple[PurePosixPath, Path]:
    """Parse a WebDAV Destination header and resolve it to a storage path."""
    parsed = urlparse(dest_header)
    raw_path = parsed.path  # still percent-encoded
    prefix = "/files"
    if raw_path in (prefix, prefix + "/"):
        rel_str = ""
    elif raw_path.startswith(prefix + "/"):
        rel_str = raw_path[len(prefix) + 1 :]
    else:
        raise BadRequest("Destination must be within /files")
    return _safe_relpath(rel_str, request=request)


def _rel_to_href(rel: PurePosixPath, *, is_dir: bool) -> str:
    """Build a DAV href from a storage-relative path."""
    parts = rel.parts
    if not parts:
        return "/files/"
    encoded = "/".join(url_quote(p, safe="") for p in parts)
    href = f"/files/{encoded}"
    return href + "/" if is_dir else href


def _dav_xml(element: ET.Element) -> bytes:
    """Serialise an ElementTree element to UTF-8 bytes with XML declaration."""
    return b'<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(
        element, encoding="unicode"
    ).encode("utf-8")


def _collect_propfind_entries(rel: PurePosixPath, path: Path, depth: str) -> list[dict]:
    entries = [_propfind_entry(rel, path)]
    if depth == "1" and path.is_dir():
        for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
            child_rel = rel / child.name if rel.parts else PurePosixPath(child.name)
            with contextlib.suppress(OSError):
                entries.append(_propfind_entry(child_rel, child))
    return entries


def _propfind_entry(rel: PurePosixPath, path: Path) -> dict:
    st = path.stat()
    is_dir = path.is_dir()
    return {
        "href": _rel_to_href(rel, is_dir=is_dir),
        "name": rel.parts[-1] if rel.parts else "",
        "is_dir": is_dir,
        "size": st.st_size,
        "etag": f'"{st.st_mtime:.0f}-{st.st_size}"',
        "content_type": mimetypes.guess_type(path.name)[0]
        or "application/octet-stream",
        "last_modified": format_date_time(st.st_mtime),
        "created": datetime.fromtimestamp(st.st_ctime, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


def _build_propfind_xml(entries: list[dict]) -> bytes:
    multistatus = ET.Element(_dav_tag("multistatus"))
    for e in entries:
        response = ET.SubElement(multistatus, _dav_tag("response"))
        ET.SubElement(response, _dav_tag("href")).text = e["href"]
        propstat = ET.SubElement(response, _dav_tag("propstat"))
        prop = ET.SubElement(propstat, _dav_tag("prop"))
        rt = ET.SubElement(prop, _dav_tag("resourcetype"))
        if e["is_dir"]:
            ET.SubElement(rt, _dav_tag("collection"))
        ET.SubElement(prop, _dav_tag("displayname")).text = e["name"]
        ET.SubElement(prop, _dav_tag("getlastmodified")).text = e["last_modified"]
        ET.SubElement(prop, _dav_tag("creationdate")).text = e["created"]
        if not e["is_dir"]:
            ET.SubElement(prop, _dav_tag("getcontentlength")).text = str(e["size"])
            ET.SubElement(prop, _dav_tag("getcontenttype")).text = e["content_type"]
            ET.SubElement(prop, _dav_tag("getetag")).text = e["etag"]
        ET.SubElement(propstat, _dav_tag("status")).text = "HTTP/1.1 200 OK"
    return _dav_xml(multistatus)
