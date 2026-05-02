import secrets
from time import time

# In-memory session store: token -> {"username": str, "exp": int}
_sessions: dict[str, dict] = {}

SESSION_COOKIE_NAME = "cista"

max_age = 365 * 86400  # Seconds since last login


def _token() -> str:
    return secrets.token_urlsafe(8)


def _purge_expired() -> None:
    now = time()
    expired = [t for t, s in _sessions.items() if s["exp"] <= now]
    for t in expired:
        del _sessions[t]


def get(request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return None
    s = _sessions.get(token)
    if s is None:
        return False  # Cookie present but session not found / expired
    if s["exp"] <= time():
        del _sessions[token]
        return False
    return s


def create(request, res, username, **kwargs):
    _purge_expired()
    token = _token()
    put(token, username, **kwargs)
    secure = request.scheme == "https"
    res.cookies.add_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        max_age=max_age,
        secure=secure,
        host_prefix=secure,
    )


def delete(request, res):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        _sessions.pop(token, None)
    secure = request.scheme == "https"
    res.cookies.delete_cookie(SESSION_COOKIE_NAME, host_prefix=secure)


def put(token: str, username: str, **kwargs) -> None:
    _sessions[token] = {"exp": int(time()) + max_age, "username": username, **kwargs}


def flash(res, message: str | None):
    if message is None:
        res.cookies.delete_cookie("message")
    else:
        res.cookies.add_cookie("message", message, max_age=5)
