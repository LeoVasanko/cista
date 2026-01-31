import hmac
import re
from time import time
from unicodedata import normalize

import argon2
import msgspec
from html5tagger import Document
from sanic import Blueprint, html, json, redirect
from sanic.exceptions import BadRequest, Forbidden, Unauthorized

from cista import config, session
from cista.util import pwgen

_LOGIN_PAGE_CSS = """\
/* ===========================================
   LOGIN PAGE STYLES
   Must match ModalDialog.vue global styles.
   =========================================== */
* { box-sizing: border-box; }
body {
    font-family: 'Roboto', system-ui, -apple-system, sans-serif;
    font-size: 1rem;
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
}
.login-card {
    background: #ddd;
    color: #000;
    border-radius: 0.5rem;
    box-shadow: 0 0 1rem #0008;
    width: 100%;
    max-width: 320px;
}
h1 {
    background: #146;
    color: #fff;
    margin: 0;
    padding: 0.5rem 1rem;
    font-size: 1.2rem;
    font-weight: normal;
    border-radius: 0.5rem 0.5rem 0 0;
}
.content {
    padding: 1rem;
}
.message {
    color: #444;
    margin: 0 0 0.5rem 0;
    font-size: 0.875rem;
}
form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5rem 1rem;
    align-items: center;
}
label {
    font-size: 1rem;
}
input[type="text"],
input[type="password"] {
    font: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    border: 2px solid #888;
    border-radius: 0.25rem;
    background: #fff;
    color: #000;
    min-width: 0;
}
input:focus {
    outline: none;
    border-color: #f80;
}
.button-row {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    margin-top: 0.5rem;
}
button {
    font: inherit;
    font-size: 1rem;
    padding: 0.5rem 1rem;
    background: #146;
    color: #fff;
    border: none;
    border-radius: 0.25rem;
    cursor: pointer;
}
button:hover { background: #f80; }
button:disabled {
    background: #888;
    cursor: not-allowed;
}
.error {
    grid-column: 1 / -1;
    color: #c00;
    font-size: 0.875rem;
    min-height: 1.2em;
    margin: 0;
}
"""

_LOGIN_PAGE_JS = """\
const form = document.getElementById('loginForm');
const error = document.getElementById('error');
const submitBtn = document.getElementById('submitBtn');
const usernameField = document.getElementById('username');
const passwordField = document.getElementById('password');
const isInIframe = window.parent !== window;

// Focus username field on load
usernameField.focus();

const showError = (msg) => {
    error.textContent = msg;
    submitBtn.disabled = false;
    submitBtn.textContent = 'Log in';
    // Focus and select the relevant field
    if (msg.toLowerCase().includes('password')) {
        passwordField.focus();
        passwordField.select();
    } else {
        usernameField.focus();
        usernameField.select();
    }
};

form.onsubmit = async (e) => {
    e.preventDefault();
    error.textContent = '';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Logging in...';

    try {
        const res = await fetch('/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                username: usernameField.value,
                password: passwordField.value
            })
        });

        if (res.ok) {
            if (isInIframe) {
                window.parent.postMessage({type: 'auth-success'}, '*');
            } else {
                window.location.href = '/';
            }
        } else {
            const data = await res.json();
            showError(data.message || data.detail || 'Login failed');
        }
    } catch (err) {
        showError('Connection error. Please try again.');
    }
};
"""

# Import for SSO validation (lazily loaded to avoid circular imports)
_sso_module = None


def _get_sso():
    global _sso_module
    if _sso_module is None:
        from cista import sso

        _sso_module = sso
    return _sso_module


_argon = argon2.PasswordHasher()
_droppyhash = re.compile(r"^([a-f0-9]{64})\$([a-f0-9]{8})$")


def _pwnorm(password):
    return normalize("NFC", password).strip().encode()


def login(username: str, password: str):
    un = _pwnorm(username)
    pw = _pwnorm(password)
    try:
        u = config.config.users[un.decode()]
    except KeyError:
        raise ValueError("Invalid username") from None
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
            raise ValueError("Invalid password") from None
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


async def verify(request, *, privileged=False):
    """Verify that the request is authorized.

    For paskia mode (PASKIA_BACKEND_URL set), validates against the SSO backend.
    For built-in mode, checks session-based authentication.
    For public mode (config.public=True), skips auth unless privileged is required.

    Args:
        request: The Sanic request object
        privileged: If True, requires admin privileges (always enforced even in public mode)

    Raises:
        Unauthorized: If authentication is required
        Forbidden: If access is denied
    """
    # Public mode: skip auth unless privileged access is required
    if config.config.public and not privileged:
        return

    sso = _get_sso()
    if sso.paskia_enabled():
        perm = "cista:admin" if privileged else "cista:login"
        await sso.validate_sso_request(request, perm=perm)
        return

    user = getattr(request.ctx, "user", None)
    if privileged:
        if user and user.privileged:
            return
        raise Forbidden(
            "Access Forbidden: Only for privileged users",
            quiet=True,
        )
    if user:
        return
    raise Unauthorized(
        f"Login required for {request.path}",
        "cookie",
        context={"auth": {"iframe": "/auth/restricted"}},
        quiet=True,
    )


# Blueprint for built-in auth (only registered when paskia is NOT enabled)
bp = Blueprint("auth", url_prefix="/auth")


@bp.get("/restricted")
async def login_page(request):
    """Login page that works both standalone and in paskia iframe."""
    s = session.get(request)

    # Check if already logged in
    if s:
        # Already authenticated - signal success if in iframe
        return html(_login_success_page(s["username"]))

    doc = Document("Cista - Login")
    # Add paskia-compatible styling and scripts
    doc.style(_LOGIN_PAGE_CSS)
    with doc.div(class_="login-card"):
        doc.h1("Authentication Required")
        with doc.div(class_="content"):
            with doc.form(method="POST", id="loginForm", autocomplete="on"):
                doc.label("Username:", for_="username")
                doc.input(
                    type="text",
                    id="username",
                    name="username",
                    autocomplete="username webauthn",
                    required=True,
                )
                doc.label("Password:", for_="password")
                doc.input(
                    type="password",
                    id="password",
                    name="password",
                    autocomplete="current-password webauthn",
                    required=True,
                )
                with doc.div(class_="button-row"):
                    doc.button("Log in", type="submit", id="submitBtn")
                doc.p("", class_="error", id="error")

    # JavaScript for AJAX login and postMessage communication
    doc.script_(_LOGIN_PAGE_JS)

    res = html(doc)
    if s is False:
        session.delete(res)
    return res


def _login_success_page(username: str) -> str:
    """Minimal page that signals auth-success to parent iframe."""
    return str(
        Document().script_("window.parent.postMessage({type:'auth-success'},'*')")
    )


@bp.post("/login")
async def login_post(request):
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            password = request.json["password"]
        else:
            username = request.form["username"][0]
            password = request.form["password"][0]
        if not username or not password:
            raise KeyError
    except KeyError:
        raise BadRequest(
            "Missing username or password",
            context={"redirect": "/login"},
        ) from None
    try:
        user = login(username, password)
    except ValueError as e:
        raise Forbidden(str(e), context={"redirect": "/login"}) from e

    if "text/html" in request.headers.accept:
        res = redirect("/")
        session.flash(res, "Logged in")
    else:
        res = json({"data": {"username": username, "privileged": user.privileged}})
    session.create(res, username)
    return res


@bp.post("/api/logout")
async def logout_post(request):
    s = request.ctx.session
    msg = "Logged out" if s else "Not logged in"
    if "text/html" in request.headers.accept:
        res = redirect("/login")
        res.cookies.add_cookie("flash", msg, max_age=5)
    else:
        res = json({"message": msg})
    session.delete(res)
    return res


@bp.post("/password-change")
async def change_password(request):
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            pwchange = request.json["passwordChange"]
            password = request.json["password"]
        else:
            username = request.form["username"][0]
            pwchange = request.form["passwordChange"][0]
            password = request.form["password"][0]
        if not username or not password:
            raise KeyError
    except KeyError:
        raise BadRequest(
            "Missing username, passwordChange or password",
        ) from None
    try:
        user = login(username, password)
        set_password(user, pwchange)
    except ValueError as e:
        raise Forbidden(str(e), context={"redirect": "/login"}) from e

    if "text/html" in request.headers.accept:
        res = redirect("/")
        session.flash(res, "Password updated")
    else:
        res = json({"message": "Password updated"})
    session.create(res, username)
    return res


@bp.get("/users")
async def list_users(request):
    await verify(request, privileged=True)
    users = []
    for name, user in config.config.users.items():
        users.append(
            {
                "username": name,
                "privileged": user.privileged,
                "lastSeen": user.lastSeen,
            }
        )
    return json({"users": users})


@bp.post("/users")
async def create_user(request):
    await verify(request, privileged=True)
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            password = request.json.get("password")
            privileged = request.json.get("privileged", False)
        else:
            username = request.form["username"][0]
            password = request.form.get("password", [None])[0]
            privileged = request.form.get("privileged", ["false"])[0].lower() == "true"
        if not username or not username.isidentifier():
            raise ValueError("Invalid username")
    except (KeyError, ValueError) as e:
        raise BadRequest(str(e)) from e
    if username in config.config.users:
        raise BadRequest("User already exists")
    if not password:
        password = pwgen.generate()
    changes = {"privileged": privileged}
    changes["hash"] = _argon.hash(_pwnorm(password))
    try:
        config.update_user(username, changes)
    except Exception as e:
        raise BadRequest(str(e)) from e
    return json({"message": f"User {username} created", "password": password})


@bp.put("/users/<username>")
async def update_user(request, username):
    await verify(request, privileged=True)
    try:
        if request.headers.content_type == "application/json":
            changes = request.json
        else:
            changes = {}
            if "password" in request.form:
                changes["password"] = request.form["password"][0]
            if "privileged" in request.form:
                changes["privileged"] = request.form["privileged"][0].lower() == "true"
    except KeyError as e:
        raise BadRequest("Missing fields") from e
    password_response = None
    if "password" in changes:
        if changes["password"] == "":
            changes["password"] = pwgen.generate()
        password_response = changes["password"]
        changes["hash"] = _argon.hash(_pwnorm(changes["password"]))
        del changes["password"]
    if not changes:
        return json({"message": "No changes"})
    try:
        config.update_user(username, changes)
    except Exception as e:
        raise BadRequest(str(e)) from e
    response = {"message": f"User {username} updated"}
    if password_response:
        response["password"] = password_response
    return json(response)


@bp.delete("/users/<username>")
async def delete_user(request, username):
    await verify(request, privileged=True)
    if username not in config.config.users:
        raise BadRequest("User does not exist")
    try:
        config.del_user(username)
    except Exception as e:
        raise BadRequest(str(e)) from e
    return json({"message": f"User {username} deleted"})
