import hmac
import re
from time import time
from unicodedata import normalize

import argon2
import msgspec
from html5tagger import Document
from sanic import Blueprint, html, json, redirect

from . import config, session

_argon = argon2.PasswordHasher()
_droppyhash = re.compile(r'^([a-f0-9]{64})\$([a-f0-9]{8})$')

def _pwnorm(password):
    return normalize('NFC', password).strip().encode()

def login(username: str, password: str):
    un = _pwnorm(username)
    pw = _pwnorm(password)
    try:
        u = config.config.users[un.decode()]
    except KeyError:
        raise ValueError("Invalid username")
    # Verify password
    need_rehash = False
    if not u.hash:
        raise ValueError("Account disabled")
    if (m := _droppyhash.match(u.hash)) is not None:
        h, s = m.groups()
        h2 = hmac.digest(pw + s.encode() + un, b"", "sha256").hex()
        if not hmac.compare_digest(h, h2):
            raise ValueError("Invalid password")
        # Droppy hashes are weak, do a hash update
        need_rehash = True
    else:
        try:
            _argon.verify(u.hash, pw)
        except Exception:
            raise ValueError("Invalid password")
        if _argon.check_needs_rehash(u.hash):
            need_rehash = True
    # Login successful
    if need_rehash:
        set_password(u, password)
    now = int(time())
    u.lastSeen = now
    return u

def set_password(user: config.User, password: str):
    user.hash = _argon.hash(_pwnorm(password))

class LoginResponse(msgspec.Struct):
    user: str = ""
    privileged: bool = False
    error: str = ""

authbp = Blueprint("auth")

@authbp.get("/login")
async def login_page(request):
    doc = Document("Cista Login")
    with doc.div(id="login"):
        with doc.form(method="POST", autocomplete="on"):
            doc.h1("Login")
            doc.input(name="username", placeholder="Username", autocomplete="username").br
            doc.input(type="password", name="password", placeholder="Password", autocomplete="current-password").br
            doc.input(type="submit", value="Login")
        s = session.get(request)
        if s:
            name = s["username"]
            with doc.form(method="POST", action="/logout"):
                doc.input(type="submit", value=f"Logout {name}")
    flash = request.cookies.flash
    if flash:
        doc.p(flash)
    res = html(doc)
    if flash:
        res.cookies.delete_cookie("flash")
    if s is False:
        session.delete(res)
    return res

@authbp.post("/login")
async def login_post(request):
    json_format = request.headers.content_type == "application/json"
    if json_format:
        username = request.json["username"]
        password = request.json["password"]
    else:
        username = request.form["username"][0]
        password = request.form["password"][0]
    if not username or not password:
        raise ValueError("Missing username or password")
    user = login(username, password)

    if json_format:
        res = json({
            "status": "authenticated",
            "user": username,
            "privileged": user.privileged,
        })
    else:
        res = redirect("/")
        res.cookies.add_cookie("flash", "Logged in", host_prefix=True, max_age=5)
    session.create(res, username)
    return res

@authbp.post("/logout")
async def logout_post(request):
    res = redirect("/")
    session.delete(res)
    res.cookies.add_cookie("flash", "Logged out", host_prefix=True, max_age=5)
    return res
