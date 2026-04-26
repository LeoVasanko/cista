import secrets
from time import time

# In-memory session store: token -> {"username": str, "exp": int}
_sessions: dict[str, dict] = {}

max_age = 365 * 86400  # Seconds since last login


def _token() -> str:
    return secrets.token_urlsafe(8)


def _purge_expired() -> None:
    now = time()
    expired = [t for t, s in _sessions.items() if s["exp"] <= now]
    for t in expired:
        del _sessions[t]


def get(request):
    token = request.cookies.get("s")
    if token is None:
        return None
    s = _sessions.get(token)
    if s is None:
        return False  # Cookie present but session not found / expired
    if s["exp"] <= time():
        del _sessions[token]
        return False
    return s


def create(res, username, *, secure: bool = True, **kwargs):
    _purge_expired()
    token = _token()
    _sessions[token] = {"exp": int(time()) + max_age, "username": username, **kwargs}
    res.cookies.add_cookie("s", token, httponly=True, max_age=max_age, secure=secure)


def delete(res):
    res.cookies.delete_cookie("s")


def flash(res, message: str | None):
    if message is None:
        res.cookies.delete_cookie("message")
    else:
        res.cookies.add_cookie("message", message, max_age=5)
