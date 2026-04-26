from __future__ import annotations

from typing import Any

import msgspec

from cista import config


class ErrorMsg(msgspec.Struct):
    error: dict[str, Any]


## Directory listings


class FileEntry(msgspec.Struct, array_like=True, frozen=True):
    level: int
    name: str
    key: str
    mtime: int
    size: int
    allocated: int
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
    used: int
    storage: int
    allocated: int
