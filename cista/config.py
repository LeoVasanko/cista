from __future__ import annotations

import hmac
import re
import secrets
from functools import wraps
from hashlib import sha256
from pathlib import Path, PurePath
from time import time
from unicodedata import normalize

import argon2
import msgspec

_argon = argon2.PasswordHasher()
_droppyhash = re.compile(r'^([a-f0-9]{64})\$([a-f0-9]{8})$')

class Config(msgspec.Struct):
    path: Path = Path.cwd()
    secret: str = secrets.token_hex(12)
    public: bool = False
    users: dict[str, User] = {}
    sessions: dict[str, Session] = {}
    links: dict[str, Link] = {}

class User(msgspec.Struct, omit_defaults=True):
    privileged: bool = False
    hash: str = ""
    lastSeen: int = 0

    def set_password(self, password: str):
        self.hash = _argon.hash(_pwnorm(password))

class Session(msgspec.Struct):
    username: str
    lastSeen: int

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

def _pwnorm(password):
    return normalize('NFC', password).strip().encode()

def login(username: str, password: str):
    un = _pwnorm(username)
    pw = _pwnorm(password)
    try:
        u = config.users[un.decode()]
    except KeyError:
        raise ValueError("Invalid username")
    # Verify password
    if not u.hash:
        raise ValueError("Account disabled")
    if (m := _droppyhash.match(u.hash)) is not None:
        h, s = m.groups()
        h2 = hmac.digest(pw + s.encode() + un, b"", "sha256").hex()
        if not hmac.compare_digest(h, h2):
            raise ValueError("Invalid password")
        # Droppy hashes are weak, do a hash update
        u.set_password(password)
    else:
        try:
            _argon.verify(u.hash, pw)
        except Exception:
            raise ValueError("Invalid password")
        if _argon.check_needs_rehash(u.hash):
            u.set_password(password)
    # Login successful
    now = int(time())
    u.lastSeen = now
    sid = secrets.token_urlsafe(12)
    config.sessions[sid] = Session(username, now)
    return u, sid

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
