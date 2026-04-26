from __future__ import annotations

from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG
from time import time
from typing import NamedTuple

from natsort import humansorted
from sanic.exceptions import BadRequest, NotFound

from cista import config, watching
from cista.fileio import fuid
from cista.protocol import FileEntry
from cista.util.filename import sanitize


class ShareRootEntry(NamedTuple):
    alias: str
    real_rel: PurePosixPath


def _token_is_share(token: config.Token) -> bool:
    return token.kind == "share" and bool(token.share_paths)


def is_share_token(token: config.Token | None) -> bool:
    return bool(token and _token_is_share(token))


def build_share_roots(token: config.Token) -> list[ShareRootEntry]:
    if not _token_is_share(token):
        return []

    base = config.config.path.resolve()
    roots: list[ShareRootEntry] = []
    used_aliases: set[str] = set()

    for raw_path in token.share_paths:
        try:
            clean = sanitize(raw_path)
        except ValueError:
            continue
        if not clean:
            continue

        rel = PurePosixPath(clean)
        resolved = (base / rel).resolve()
        if not resolved.is_relative_to(base) or not resolved.exists():
            continue

        display = rel.name or config.config.path.name
        alias = display
        suffix = 2
        while alias in used_aliases:
            alias = f"{display} ({suffix})"
            suffix += 1
        used_aliases.add(alias)
        roots.append(ShareRootEntry(alias=alias, real_rel=rel))

    return roots


def resolve_virtual_path(
    token: config.Token,
    raw_path: str,
) -> tuple[PurePosixPath, PurePosixPath, Path, bool]:
    """Resolve a share-virtual path to real path.

    Returns (virtual_rel, real_rel, real_abs, is_virtual_root).
    """
    base = config.config.path.resolve()
    if raw_path.strip("/") == "":
        return PurePosixPath(), PurePosixPath(), base, True

    try:
        clean = sanitize(raw_path)
    except ValueError as e:
        raise BadRequest(f"Invalid path: {e}") from e

    if not clean:
        return PurePosixPath(), PurePosixPath(), base, True

    virtual_rel = PurePosixPath(clean)
    roots = build_share_roots(token)
    if not roots:
        raise NotFound("Share token has no visible files")

    root_by_alias = {r.alias: r.real_rel for r in roots}
    first = virtual_rel.parts[0]
    real_root = root_by_alias.get(first)
    if real_root is None:
        raise NotFound(f"Not found: {raw_path}")

    rest = virtual_rel.parts[1:]
    real_rel = real_root.joinpath(*rest) if rest else real_root
    resolved = (base / real_rel).resolve()
    if not resolved.is_relative_to(base):
        raise BadRequest("Invalid path")
    return virtual_rel, real_rel, resolved, False


def real_to_virtual_aliases(token: config.Token) -> dict[PurePosixPath, str]:
    return {entry.real_rel: entry.alias for entry in build_share_roots(token)}


def _walk_virtual_entry(path: Path, name: str, level: int) -> list[FileEntry]:
    st = path.lstat()
    is_dir = S_ISDIR(st.st_mode)
    is_file = S_ISREG(st.st_mode)
    if not is_dir and not is_file:
        return []

    if is_file:
        try:
            allocated = watching.get_allocated_size(path, st)
        except Exception:
            allocated = st.st_size
        return [
            FileEntry(
                level=level,
                name=name,
                key=fuid(st),
                mtime=int(st.st_mtime),
                size=st.st_size,
                allocated=allocated,
                isfile=1,
            )
        ]

    children: list[tuple[int, str, object]] = []
    for child in path.iterdir():
        if child.name.startswith("."):
            continue
        try:
            cst = child.lstat()
        except FileNotFoundError:
            continue
        c_is_file = S_ISREG(cst.st_mode)
        c_is_dir = S_ISDIR(cst.st_mode)
        if not c_is_file and not c_is_dir:
            continue
        children.append((int(c_is_file), child.name, cst))

    entries: list[FileEntry] = []
    agg_mtime = int(st.st_mtime)
    agg_size = 0
    agg_alloc = 0

    for _, child_name, _ in humansorted(children):
        child_path = path / child_name
        child_entries = _walk_virtual_entry(child_path, child_name, level + 1)
        if not child_entries:
            continue
        head = child_entries[0]
        agg_mtime = max(agg_mtime, head.mtime)
        agg_size += head.size
        agg_alloc += head.allocated
        entries.extend(child_entries)

    head = FileEntry(
        level=level,
        name=name,
        key=fuid(st),
        mtime=agg_mtime,
        size=agg_size,
        allocated=agg_alloc,
        isfile=0,
    )
    return [head, *entries]


def build_virtual_root(token: config.Token) -> list[FileEntry]:
    roots = build_share_roots(token)
    now = int(time())
    root_key = config.derived_secret("share-root", token.key or "", token.created).hex()

    entries: list[FileEntry] = []
    total_size = 0
    total_alloc = 0
    root_mtime = 0

    base = config.config.path.resolve()
    for entry in roots:
        real_abs = (base / entry.real_rel).resolve()
        if not real_abs.is_relative_to(base) or not real_abs.exists():
            continue
        try:
            subtree = _walk_virtual_entry(real_abs, entry.alias, 1)
        except OSError:
            continue
        if not subtree:
            continue
        head = subtree[0]
        total_size += head.size
        total_alloc += head.allocated
        root_mtime = max(root_mtime, head.mtime)
        entries.extend(subtree)

    root = FileEntry(
        level=0,
        name="",
        key=root_key,
        mtime=root_mtime or now,
        size=total_size,
        allocated=total_alloc,
        isfile=0,
    )
    return [root, *entries]


def key_paths_for_token(
    token: config.Token, wanted: set[str]
) -> dict[str, PurePosixPath]:
    ret: dict[str, PurePosixPath] = {}
    loc = PurePosixPath()
    root = build_virtual_root(token)
    for f in root:
        loc = PurePosixPath(*loc.parts[: f.level - 1]) / f.name
        if f.key in wanted and f.key not in ret:
            ret[f.key] = loc
            if len(ret) == len(wanted):
                break
    return ret


def resolve_virtual_rel_to_real(token: config.Token, rel: PurePosixPath) -> Path:
    _vrel, _rrel, real_abs, is_root = resolve_virtual_path(token, rel.as_posix())
    if is_root:
        raise BadRequest("Virtual root is not a writable filesystem path")
    return real_abs
