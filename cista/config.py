from __future__ import annotations

import os
import secrets
import sys
from contextlib import suppress
from functools import wraps
from hashlib import sha256
from pathlib import Path, PurePath
from time import time

import msgspec


class Config(msgspec.Struct):
    path: Path
    listen: str
    secret: str = secrets.token_hex(12)
    public: bool = False
    name: str = ""
    users: dict[str, User] = {}
    links: dict[str, Link] = {}


class User(msgspec.Struct, omit_defaults=True):
    privileged: bool = False
    hash: str = ""
    lastSeen: int = 0  # noqa: N815


class Link(msgspec.Struct, omit_defaults=True):
    location: str
    creator: str = ""
    expires: int = 0


config = None
conffile = None


def init_confdir():
    if p := os.environ.get("CISTA_HOME"):
        home = Path(p)
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        home = (
            Path(xdg).expanduser() / "cista" if xdg else Path.home() / ".config/cista"
        )
    if not home.is_dir():
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o700)

    global conffile
    conffile = home / "db.toml"


def derived_secret(*params, len=8) -> bytes:
    """Used to derive secret keys from the main secret"""
    # Each part is made the same length by hashing first
    combined = b"".join(
        sha256(p if isinstance(p, bytes) else f"{p}".encode()).digest()
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


def config_update(modify):
    global config
    if conffile is None:
        init_confdir()
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
            c = None
        c = modify(c)
        new = msgspec.toml.encode(c, enc_hook=enc_hook)
        if old == new:
            f.close()
            tmpname.unlink()
            config = c
            return "read"
        f.write(new)
        f.close()
        if sys.platform == "win32":
            # Windows doesn't support atomic replace
            with suppress(FileNotFoundError):
                conffile.unlink()
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
        def m(c):
            return modify(c, *args, **kwargs)

        # Retry modification in case of write collision
        while (c := config_update(m)) == "collision":
            time.sleep(0.01)
        return c

    return wrapper


def load_config():
    global config
    if conffile is None:
        init_confdir()
    config = msgspec.toml.decode(conffile.read_bytes(), type=Config, dec_hook=dec_hook)


@modifies_config
def update_config(conf: Config, changes: dict) -> Config:
    """Create/update the config with new values, respecting changes done by others."""
    # Encode into dict, update values with new, convert to Config
    settings = {} if conf is None else msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings.update(changes)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def update_user(conf: Config, name: str, changes: dict) -> Config:
    """Create/update a user with new values, respecting changes done by others."""
    # Encode into dict, update values with new, convert to Config
    try:
        u = conf.users[name].__copy__()
    except (KeyError, AttributeError):
        u = User()
    if "password" in changes:
        from . import auth

        auth.set_password(u, changes["password"])
        del changes["password"]
    udict = msgspec.to_builtins(u, enc_hook=enc_hook)
    udict.update(changes)
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook) if conf else {"users": {}}
    settings["users"][name] = msgspec.convert(udict, User, dec_hook=dec_hook)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def del_user(conf: Config, name: str) -> Config:
    """Delete named user account."""
    ret = conf.__copy__()
    ret.users.pop(name)
    return ret
