from time import time

import jwt

from cista.config import derived_secret


def session_secret():
    return derived_secret("session")


max_age = 365 * 86400  # Seconds since last login


def get(request):
    try:
        return jwt.decode(request.cookies.s, session_secret(), algorithms=["HS256"])
    except Exception:
        return False if "s" in request.cookies else None


def create(res, username, **kwargs):
    data = {
        "exp": int(time()) + max_age,
        "username": username,
        **kwargs,
    }
    s = jwt.encode(data, session_secret())
    res.cookies.add_cookie("s", s, httponly=True, max_age=max_age)


def update(res, s, **kwargs):
    s.update(kwargs)
    s = jwt.encode(s, session_secret())
    max_age = max(1, s["exp"] - int(time()))  # type: ignore
    res.cookies.add_cookie("s", s, httponly=True, max_age=max_age)


def delete(res):
    res.cookies.delete_cookie("s")


def flash(res, message: str | None):
    if message is None:
        res.cookies.delete_cookie("message")
    else:
        res.cookies.add_cookie("message", message, max_age=5)
