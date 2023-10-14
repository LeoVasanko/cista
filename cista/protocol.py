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
    url: str

class StatusMsg(msgspec.Struct):
    status: str
    url: str
    req: FileRange


## Directory listings

class FileEntry(msgspec.Struct):
    size: int
    mtime: int

class DirEntry(msgspec.Struct):
    size: int
    mtime: int
    dir: Dict[str, Union[FileEntry, DirEntry]]

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
