from __future__ import annotations

import secrets
from functools import wraps
from hashlib import sha256
from pathlib import Path, PurePath
from time import time

import msgspec


class Config(msgspec.Struct):
    path: Path = Path.cwd()
    secret: str = secrets.token_hex(12)
    public: bool = False
    users: dict[str, User] = {}
    links: dict[str, Link] = {}

class User(msgspec.Struct, omit_defaults=True):
    privileged: bool = False
    hash: str = ""
    lastSeen: int = 0

class Link(msgspec.Struct, omit_defaults=True):
    location: str
    creator: str = ""
    expires: int = 0

config = Config()

def derived_secret(*params, len=8) -> bytes:
    """Used to derive secret keys from the main secret"""
    # Each part is made the same length by hashing first
    combined = b"".join(
        sha256(
            p if isinstance(p, bytes) else f"{p}".encode()
        ).digest()
        for p in [config.secret, *params]
    )
    # Output a bytes of the desired length
    return sha256(combined).digest()[:len]


def enc_hook(obj):
    if isinstance(obj, PurePath):
        return obj.as_posix()
    raise TypeError

def dec_hook(typ, obj):
    if typ is Path:
        return Path(obj)
    raise TypeError

conffile = Path.cwd() / ".cista.toml"

def config_update(modify):
    global config
    tmpname = conffile.with_suffix(".tmp")
    try:
        f = tmpname.open("xb")
    except FileExistsError:
        if tmpname.stat().st_mtime < time() - 1:
            tmpname.unlink()
        return "collision"
    try:
        # Load, modify and save with atomic replace
        try:
            old = conffile.read_bytes()
            c = msgspec.toml.decode(old, type=Config, dec_hook=dec_hook)
        except FileNotFoundError:
            old = b""
            c = Config()  # Initialize with defaults
        c = modify(c)
        new = msgspec.toml.encode(c, enc_hook=enc_hook)
        if old == new:
            f.close()
            tmpname.unlink()
            config = c
            return "read"
        f.write(new)
        f.close()
        tmpname.rename(conffile)  # Atomic replace
    except:
        f.close()
        tmpname.unlink()
        raise
    config = c
    return "modified" if old else "created"

def modifies_config(modify):
    """Decorator for functions that modify the config file"""
    @wraps(modify)
    def wrapper(*args, **kwargs):
        m = lambda c: modify(c, *args, **kwargs)
        # Retry modification in case of write collision
        while (c := config_update(m)) == "collision":
            time.sleep(0.01)
        return c
    return wrapper

@modifies_config
def droppy_import(config: Config) -> Config:
    p = Path.home() / ".droppy/config"
    cf = msgspec.json.decode((p / "config.json").read_bytes())
    db = msgspec.json.decode((p / "db.json").read_bytes())
    return msgspec.convert(cf | db, Config)

# Load/initialize config file
print(conffile, config_update(lambda c: c))
