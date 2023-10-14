import secrets
from hashlib import sha256
from pathlib import Path, PurePosixPath

import msgspec

from .fileio import ROOT
from .protocol import DirEntry, FileEntry

secret = secrets.token_bytes(8)
pubsub = {}

def fuid(stat):
    return sha256((stat.st_dev << 32 | stat.st_ino).to_bytes(8, 'big') + secret).hexdigest()[:16]

def walk(path: Path = ROOT):
    try:
        s = path.stat()
        mtime = int(s.st_mtime)
        if path.is_file():
            return FileEntry(s.st_size, mtime)

        tree = {p.name: v for p in path.iterdir() if not p.name.startswith('.') if (v := walk(p)) is not None}
        if tree:
            size = sum(v.size for v in tree.values())
            mtime = max(mtime, max(v.mtime for v in tree.values()))
        else:
            size = 0
        return DirEntry(size, mtime, tree)
    except OSError as e:
        print("OS error walking path", path, e)
        return None

tree = walk()

def update(relpath: PurePosixPath):
    ptr = tree.dir
    path = ROOT
    name = ""
    for name in relpath.parts[:-1]:
        path /= name
        try:
            ptr = ptr[name].dir
        except KeyError:
            break
    new = walk(path)
    old = ptr.pop(name, None)
    if new is not None:
        ptr[name] = new
    if old == new:
        return
    print("Update", relpath)
    # TODO: update parents size/mtime
    msg = msgspec.json.encode({"update": {
        "path": relpath.as_posix(),
        "data": new,
    }})
    for queue in pubsub.values(): queue.put_nowait(msg)
