from http.cookies import SimpleCookie
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import auth, config
from cista.app import use_session
from cista.auth import bp as auth_bp


def _set_cookie_headers(response) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def _cookie_header(response, name: str = "cista") -> dict[str, str]:
    for header in _set_cookie_headers(response):
        cookie = SimpleCookie()
        cookie.load(header)
        morsel = cookie.get(name)
        if morsel is not None and morsel.value:
            return {"Cookie": f"{name}={morsel.value}"}
    raise AssertionError(f"response did not set cookie {name!r}")


@pytest.fixture
def setup_auth_config(tmp_path: Path):
    alice = config.User()
    auth.set_password(alice, "secret")
    admin = config.User(privileged=True)
    auth.set_password(admin, "admin-secret")
    config.config = config.Config(
        path=tmp_path,
        listen=":0",
        public=False,
        users={"alice": alice, "admin": admin},
    )
    return tmp_path


@pytest_asyncio.fixture()
async def client(setup_auth_config: Path):
    app = Sanic(f"auth-builtins-test-{uuid4().hex}", strict_slashes=True)

    @app.on_request
    async def load_auth_context(request):
        await use_session(request)

    app.blueprint(auth_bp)
    yield app.asgi_client


@pytest.mark.asyncio
async def test_restricted_page_renders_login_form_when_logged_out(client):
    _, res = await client.get("/auth/restricted/")

    assert res.status_code == 200
    assert "Authentication Required" in res.text
    assert "Username:" in res.text
    assert "Password:" in res.text
    assert "/auth/login" in res.text


@pytest.mark.asyncio
async def test_restricted_page_with_invalid_session_clears_cookie(client):
    _, res = await client.get(
        "/auth/restricted/",
        headers={"Cookie": "cista=missing-session"},
    )

    assert res.status_code == 200
    assert "Authentication Required" in res.text
    assert any("cista=" in header.lower() for header in _set_cookie_headers(res))


@pytest.mark.asyncio
async def test_json_login_sets_session_cookie_and_allows_session_authenticated_api_access(
    client,
):
    _, res = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "secret"},
    )

    assert res.status_code == 200
    assert res.json == {"data": {"username": "alice", "privileged": False}}

    session_cookie = _cookie_header(res)

    _, tokens_res = await client.get("/auth/tokens", headers=session_cookie)
    assert tokens_res.status_code == 200
    assert tokens_res.json == {"tokens": []}

    _, restricted_res = await client.get("/auth/restricted/", headers=session_cookie)
    assert restricted_res.status_code == 200
    assert "auth-success" in restricted_res.text


@pytest.mark.asyncio
async def test_json_login_rejects_missing_fields(client):
    _, res = await client.post(
        "/auth/login",
        json={"username": "alice"},
    )

    assert res.status_code == 400
    assert "Missing username or password" in res.json["message"]


@pytest.mark.asyncio
async def test_json_login_rejects_invalid_password(client):
    _, res = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "wrong"},
    )

    assert res.status_code == 403
    assert "Invalid password" in res.json["message"]


@pytest.mark.asyncio
async def test_html_login_redirects_and_sets_flash_and_session_cookies(client):
    _, res = await client.post(
        "/auth/login",
        data={"username": "alice", "password": "secret"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 302
    assert res.headers["location"] == "/"
    headers = _set_cookie_headers(res)
    assert any("cista=" in header.lower() for header in headers)
    assert any("message=" in header.lower() for header in headers)


@pytest.mark.asyncio
async def test_logout_json_revokes_the_existing_session(client):
    _, login_res = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "secret"},
    )
    session_cookie = _cookie_header(login_res)

    _, logout_res = await client.post("/auth/api/logout", headers=session_cookie)

    assert logout_res.status_code == 200
    assert logout_res.json == {"message": "Logged out"}
    assert any("cista=" in header.lower() for header in _set_cookie_headers(logout_res))

    _, retry_res = await client.get("/auth/tokens", headers=session_cookie)
    assert retry_res.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_session_reports_not_logged_in(client):
    _, res = await client.post("/auth/api/logout")

    assert res.status_code == 200
    assert res.json == {"message": "Not logged in"}


@pytest.mark.asyncio
async def test_password_change_updates_credentials_and_reissues_session(client):
    _, change_res = await client.post(
        "/auth/password-change",
        json={
            "username": "alice",
            "password": "secret",
            "passwordChange": "fresh-secret",
        },
    )

    assert change_res.status_code == 200
    assert change_res.json == {"message": "Password updated"}

    session_cookie = _cookie_header(change_res)
    _, tokens_res = await client.get("/auth/tokens", headers=session_cookie)
    assert tokens_res.status_code == 200

    _, old_login_res = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "secret"},
    )
    assert old_login_res.status_code == 403

    _, new_login_res = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "fresh-secret"},
    )
    assert new_login_res.status_code == 200
    assert new_login_res.json == {"data": {"username": "alice", "privileged": False}}


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_current_password(client):
    _, res = await client.post(
        "/auth/password-change",
        json={
            "username": "alice",
            "password": "wrong",
            "passwordChange": "fresh-secret",
        },
    )

    assert res.status_code == 403
    assert "Invalid password" in res.json["message"]


@pytest.mark.asyncio
async def test_password_change_rejects_missing_fields(client):
    _, res = await client.post(
        "/auth/password-change",
        json={"username": "alice", "password": "secret"},
    )

    assert res.status_code == 400
    assert "Missing username, passwordChange or password" in res.json["message"]
