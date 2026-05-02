import hmac
import re
from typing import Protocol
from unicodedata import normalize

import argon2

_argon = argon2.PasswordHasher()
_droppyhash = re.compile(r"^([a-f0-9]{64})\$([a-f0-9]{8})$")


class SupportsHash(Protocol):
    hash: str


def normalize_secret(value: str) -> bytes:
    return normalize("NFC", value).strip().encode()


def verify_hash(user_hash: str, *, username: str, password: str) -> bool:
    """Verify password hash and return whether the stored hash should be upgraded."""
    if not user_hash:
        raise ValueError("Account disabled")

    normalized_username = normalize_secret(username)
    normalized_password = normalize_secret(password)

    if (match := _droppyhash.match(user_hash)) is not None:
        expected_hash, salt = match.groups()
        computed_hash = hmac.digest(
            normalized_password + salt.encode() + normalized_username,
            b"",
            "sha256",
        ).hex()
        if not hmac.compare_digest(expected_hash, computed_hash):
            raise ValueError("Invalid password")
        return True

    try:
        _argon.verify(user_hash, normalized_password)
    except Exception:
        raise ValueError("Invalid password") from None
    return _argon.check_needs_rehash(user_hash)


def set_password(user: SupportsHash, password: str) -> None:
    user.hash = _argon.hash(normalize_secret(password))
