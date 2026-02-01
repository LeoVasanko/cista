from __future__ import annotations

import shutil
from pathlib import PurePosixPath
from typing import Any

import msgspec
from sanic import BadRequest

from cista import config
from cista.util import filename

## Control commands


class ControlBase(msgspec.Struct, tag_field="op", tag=str.lower):
    def __call__(self):
        raise NotImplementedError

    def affected_paths(self) -> list[str]:
        """Return list of paths affected by this operation for change notification."""
        return []


class MkDir(ControlBase):
    path: str

    def __call__(self):
        path = config.config.path / filename.sanitize(self.path)
        path.mkdir(parents=True, exist_ok=False)

    def affected_paths(self) -> list[str]:
        return [filename.sanitize(self.path)]


class Rename(ControlBase):
    path: str
    to: str

    def __call__(self):
        to = filename.sanitize(self.to)
        if "/" in to:
            raise BadRequest("Rename 'to' name should only contain filename, not path")
        path = config.config.path / filename.sanitize(self.path)
        path.rename(path.with_name(to))

    def affected_paths(self) -> list[str]:
        sanitized = filename.sanitize(self.path)
        new_path = str(PurePosixPath(sanitized).with_name(filename.sanitize(self.to)))
        return [sanitized, new_path]


class Rm(ControlBase):
    sel: list[str]

    def __call__(self):
        root = config.config.path
        sel = [root / filename.sanitize(p) for p in self.sel]
        for p in sel:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()

    def affected_paths(self) -> list[str]:
        return [filename.sanitize(p) for p in self.sel]


class Mv(ControlBase):
    sel: list[str]
    dst: str

    def __call__(self):
        root = config.config.path
        sel = [root / filename.sanitize(p) for p in self.sel]
        dst = root / filename.sanitize(self.dst)
        if not dst.is_dir():
            raise BadRequest("The destination must be a directory")
        for p in sel:
            shutil.move(p, dst)

    def affected_paths(self) -> list[str]:
        dst = filename.sanitize(self.dst)
        paths = [filename.sanitize(p) for p in self.sel]
        # Include new locations in dst
        paths.extend(f"{dst}/{PurePosixPath(p).name}" for p in self.sel)
        return paths


class Cp(ControlBase):
    sel: list[str]
    dst: str

    def __call__(self):
        root = config.config.path
        sel = [root / filename.sanitize(p) for p in self.sel]
        dst = root / filename.sanitize(self.dst)
        if not dst.is_dir():
            raise BadRequest("The destination must be a directory")
        for p in sel:
            if p.is_dir():
                # Note: copies as dst rather than in dst unless name is appended.
                shutil.copytree(
                    p,
                    dst / p.name,
                    dirs_exist_ok=True,
                    ignore_dangling_symlinks=True,
                )
            else:
                shutil.copy2(p, dst)

    def affected_paths(self) -> list[str]:
        dst = filename.sanitize(self.dst)
        # Only destinations are new (sources unchanged)
        return [f"{dst}/{PurePosixPath(filename.sanitize(p)).name}" for p in self.sel]


ControlTypes = MkDir | Rename | Rm | Mv | Cp


## File uploads and downloads


class FileRange(msgspec.Struct):
    name: str
    size: int
    start: int
    end: int


class StatusMsg(msgspec.Struct):
    status: str
    req: FileRange


class ErrorMsg(msgspec.Struct):
    error: dict[str, Any]


## Directory listings


class FileEntry(msgspec.Struct, array_like=True, frozen=True):
    level: int
    name: str
    key: str
    mtime: int
    size: int
    isfile: int

    def __str__(self):
        return self.key or "FileEntry()"

    def __repr__(self):
        return f"{self.name} ({self.size}, {self.mtime})"


class Update(msgspec.Struct, array_like=True): ...


class UpdKeep(Update, tag="k"):
    count: int


class UpdDel(Update, tag="d"):
    count: int


class UpdIns(Update, tag="i"):
    items: list[FileEntry]


class UpdateMessage(msgspec.Struct):
    update: list[UpdKeep | UpdDel | UpdIns]


class Space(msgspec.Struct):
    disk: int
    free: int
    usage: int
    storage: int
