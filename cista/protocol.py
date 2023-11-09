from __future__ import annotations

import shutil
from typing import Any

import msgspec
from sanic import BadRequest

from cista import config
from cista.util import filename

## Control commands


class ControlBase(msgspec.Struct, tag_field="op", tag=str.lower):
    def __call__(self):
        raise NotImplementedError


class MkDir(ControlBase):
    path: str

    def __call__(self):
        path = config.config.path / filename.sanitize(self.path)
        path.mkdir(parents=True, exist_ok=False)


class Rename(ControlBase):
    path: str
    to: str

    def __call__(self):
        to = filename.sanitize(self.to)
        if "/" in to:
            raise BadRequest("Rename 'to' name should only contain filename, not path")
        path = config.config.path / filename.sanitize(self.path)
        path.rename(path.with_name(to))


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


class FileEntry(msgspec.Struct):
    key: str
    size: int
    mtime: int


class DirEntry(msgspec.Struct):
    key: str
    size: int
    mtime: int
    dir: DirList

    def __getitem__(self, name):
        return self.dir[name]

    def __setitem__(self, name, value):
        self.dir[name] = value

    def __contains__(self, name):
        return name in self.dir

    def __delitem__(self, name):
        del self.dir[name]

    @property
    def props(self):
        return {k: v for k, v in self.__struct_fields__ if k != "dir"}


DirList = dict[str, FileEntry | DirEntry]


class UpdateEntry(msgspec.Struct, omit_defaults=True):
    """Updates the named entry in the tree. Fields that are set replace old values. A list of entries recurses directories."""

    name: str
    key: str
    deleted: bool = False
    size: int | None = None
    mtime: int | None = None
    dir: DirList | None = None


def make_dir_data(root):
    if len(root) == 3:
        return FileEntry(*root)
    id_, size, mtime, listing = root
    converted = {}
    for name, data in listing.items():
        converted[name] = make_dir_data(data)
    sz = sum(x.size for x in converted.values())
    mt = max(x.mtime for x in converted.values())
    return DirEntry(id_, sz, max(mt, mtime), converted)
