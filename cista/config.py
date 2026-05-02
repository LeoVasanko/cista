from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Callable
from contextlib import suppress
from functools import wraps
from hashlib import sha256
from pathlib import Path, PurePath
from time import sleep, time
from typing import Concatenate, Literal, ParamSpec

import msgspec
import msgspec.toml

from .util import pwhash


class Config(msgspec.Struct):
    path: Path
    listen: str
    secret: str = secrets.token_hex(12)
    public: bool = False
    name: str = ""
    users: dict[str, User] = {}
    links: dict[str, Link] = {}
    tokens: dict[str, Token] = {}


# Typing: arguments for config-modifying functions
P = ParamSpec("P")
ResultStr = Literal["modified", "created", "read"]
RawModifyFunc = Callable[Concatenate[Config, P], Config]
ModifyPublic = Callable[P, ResultStr]


class User(msgspec.Struct, omit_defaults=True):
    privileged: bool = False
    hash: str = ""
    lastSeen: int = 0  # noqa: N815


class Link(msgspec.Struct, omit_defaults=True):
    location: str
    creator: str = ""
    expires: int = 0


class Token(msgspec.Struct, omit_defaults=True):
    key: str = ""  # plain text secret (shown once on creation)
    username: str = ""  # set in built-in mode
    sso_user_id: str = ""  # set in SSO mode
    name: str = ""
    created: int = 0
    kind: str = "api"  # api | share
    mode: str = "rw"  # ro | rw
    share_paths: list[str] = []


# Global variables - initialized during application startup
config: Config
conffile: Path


def init_confdir(confdir: Path | str | None = None) -> None:
    global conffile
    if confdir is not None:
        home = Path(confdir).expanduser()
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        home = (
            Path(xdg).expanduser() / "cista" if xdg else Path.home() / ".config/cista"
        )
    if not home.is_dir():
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o700)
    conffile = home / "db.toml"


def derived_secret(*params, size=8) -> bytes:
    """Used to derive secret keys from the main secret"""
    # Each part is made the same length by hashing first
    combined = b"".join(
        sha256(p if isinstance(p, bytes) else f"{p}".encode()).digest()
        for p in [config.secret, *params]
    )
    # Output a bytes of the desired length
    return sha256(combined).digest()[:size]


def enc_hook(obj):
    if isinstance(obj, PurePath):
        return obj.as_posix()
    raise TypeError


def dec_hook(typ, obj):
    if typ is Path:
        return Path(obj)
    raise TypeError


def config_update(
    modify: RawModifyFunc,
) -> ResultStr | Literal["collision"]:
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
            c = Config(path=Path(), listen="", secret=secrets.token_hex(12))
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


def modifies_config(
    modify: Callable[Concatenate[Config, P], Config],
) -> Callable[P, ResultStr]:
    """Decorator for functions that modify the config file

    The decorated function takes as first arg Config and returns it modified.
    The wrapper handles atomic modification and returns a string indicating the result.
    """

    @wraps(modify)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ResultStr:
        def m(c: Config) -> Config:
            return modify(c, *args, **kwargs)

        # Retry modification in case of write collision
        while (c := config_update(m)) == "collision":
            sleep(0.01)
        return c

    return wrapper


def load_config():
    global config
    init_confdir()
    raw = conffile.read_bytes()
    config = msgspec.toml.decode(raw, type=Config, dec_hook=dec_hook)
    # Migrate from old authentication field if present
    raw_dict = msgspec.toml.decode(raw)
    if "authentication" in raw_dict and "public" not in raw_dict:
        # Old config with authentication mode: migrate to public bool
        new_public = raw_dict["authentication"] == "none"
        config = msgspec.structs.replace(config, public=new_public)
        update_config({})  # Save the migrated config


@modifies_config
def update_config(conf: Config, changes: dict) -> Config:
    """Create/update the config with new values, respecting changes done by others."""
    # Encode into dict, update values with new, convert to Config
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings.update(changes)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def update_user(conf: Config, name: str, changes: dict) -> Config:
    """Create/update a user with new values, respecting changes done by others."""
    # Encode into dict, update values with new, convert to Config
    try:
        # Copy user by converting to dict and back
        u = msgspec.convert(
            msgspec.to_builtins(conf.users[name], enc_hook=enc_hook),
            User,
            dec_hook=dec_hook,
        )
    except KeyError:
        u = User()
    if "password" in changes:
        pwhash.set_password(u, changes["password"])
        del changes["password"]
    udict = msgspec.to_builtins(u, enc_hook=enc_hook)
    udict.update(changes)
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings["users"][name] = msgspec.convert(udict, User, dec_hook=dec_hook)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def del_user(conf: Config, name: str) -> Config:
    """Delete named user account."""
    # Create a copy by converting to dict and back
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings["users"].pop(name)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def update_token(conf: Config, token_id: str, changes: dict) -> Config:
    """Create or update a token."""
    try:
        t = msgspec.convert(
            msgspec.to_builtins(conf.tokens[token_id], enc_hook=enc_hook),
            Token,
            dec_hook=dec_hook,
        )
    except KeyError:
        t = Token()
    tdict = msgspec.to_builtins(t, enc_hook=enc_hook)
    tdict.update(changes)
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings["tokens"][token_id] = msgspec.convert(tdict, Token, dec_hook=dec_hook)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)


@modifies_config
def del_token(conf: Config, token_id: str) -> Config:
    """Delete a token by its stable id."""
    settings = msgspec.to_builtins(conf, enc_hook=enc_hook)
    settings["tokens"].pop(token_id, None)
    return msgspec.convert(settings, Config, dec_hook=dec_hook)
