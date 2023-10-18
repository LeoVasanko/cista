from __future__ import annotations

from typing import Dict, Tuple, Union

import msgspec

## File uploads and downloads

class FileRange(msgspec.Struct):
    name: str
    size: int
    start: int
    end: int

class ErrorMsg(msgspec.Struct):
    error: str
    req: FileRange

class StatusMsg(msgspec.Struct):
    status: str
    req: FileRange


## Directory listings

class FileEntry(msgspec.Struct):
    size: int
    mtime: int

class DirEntry(msgspec.Struct):
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
        return {
            k: v
            for k, v in self.__struct_fields__
            if k != "dir"
        }

DirList = dict[str, Union[FileEntry, DirEntry]]


class UpdateEntry(msgspec.Struct, omit_defaults=True):
    """Updates the named entry in the tree. Fields that are set replace old values. A list of entries recurses directories."""
    name: str = ""
    deleted: bool = False
    size: int | None = None
    mtime: int | None = None
    dir: DirList | None = None

def make_dir_data(root):
    if len(root) == 2:
        return FileEntry(*root)
    size, mtime, listing = root
    converted = {}
    for name, data in listing.items():
        converted[name] = make_dir_data(data)
    sz = sum(x.size for x in converted.values())
    mt = max(x.mtime for x in converted.values())
    return DirEntry(sz, max(mt, mtime), converted)
