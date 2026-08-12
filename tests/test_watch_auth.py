import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sanic.exceptions import Unauthorized

from cista import auth, config, session, sso
from cista.util.apphelpers import (
    get_watch_user_info,
    run_auth_checked_watch,
)


def _make_request(cookie: str = "", auth_token=None):
    req = SimpleNamespace()
    req.headers = {}
    req.cookies = {}
    if cookie:
        req.headers["cookie"] = cookie
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            req.cookies[k] = v
    req.ctx = SimpleNamespace()
    if auth_token:
        req.ctx.auth_token = auth_token
    return req


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
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
    session._sessions.clear()
    sso._validate_cache.clear()
    monkeypatch.setattr(sso, "PASKIA_BACKEND_URL", "")
    yield
    session._sessions.clear()
    sso._validate_cache.clear()


@pytest.mark.asyncio
async def test_get_watch_user_info_builtin_valid_session():
    token = "valid-token"
    session.put(token, "alice")
    req = _make_request(cookie=f"cista={token}")

    info = await get_watch_user_info(req)

    assert info == {"username": "alice", "privileged": False}


@pytest.mark.asyncio
async def test_get_watch_user_info_builtin_admin():
    token = "admin-token"
    session.put(token, "admin")
    req = _make_request(cookie=f"cista={token}")

    info = await get_watch_user_info(req)

    assert info == {"username": "admin", "privileged": True}


@pytest.mark.asyncio
async def test_get_watch_user_info_builtin_invalid_session_raises():
    req = _make_request(cookie="cista=bad-token")

    with pytest.raises(Unauthorized):
        await get_watch_user_info(req)


@pytest.mark.asyncio
async def test_get_watch_user_info_builtin_public_no_session():
    config.config.public = True
    req = _make_request()

    info = await get_watch_user_info(req)

    assert info is None


@pytest.mark.asyncio
async def test_get_watch_user_info_sso_valid(monkeypatch):
    monkeypatch.setattr(sso, "PASKIA_BACKEND_URL", "http://test-paskia.local")

    async def mock_validate(request, *, renew=True):
        request.ctx.sso_user = {
            "ctx": {
                "user": {"display_name": "alice"},
                "permissions": ["cista:login", "cista:admin"],
            }
        }

    monkeypatch.setattr(sso, "validate_sso_request", mock_validate)
    req = _make_request(cookie="session=abc")

    info = await get_watch_user_info(req)

    assert info == {"username": "alice", "privileged": True}


@pytest.mark.asyncio
async def test_get_watch_user_info_sso_nonpublic_invalid_raises(monkeypatch):
    monkeypatch.setattr(sso, "PASKIA_BACKEND_URL", "http://test-paskia.local")

    async def mock_validate(request, *, renew=True):
        raise Unauthorized("Session expired", quiet=True)

    monkeypatch.setattr(sso, "validate_sso_request", mock_validate)
    req = _make_request(cookie="session=abc")

    with pytest.raises(Unauthorized):
        await get_watch_user_info(req)


@pytest.mark.asyncio
async def test_get_watch_user_info_sso_public_invalid_returns_none(monkeypatch):
    monkeypatch.setattr(sso, "PASKIA_BACKEND_URL", "http://test-paskia.local")
    config.config.public = True

    async def mock_validate(request, *, renew=True):
        raise Unauthorized("Session expired", quiet=True)

    monkeypatch.setattr(sso, "validate_sso_request", mock_validate)
    req = _make_request(cookie="session=abc")

    info = await get_watch_user_info(req)

    assert info is None


@pytest.mark.asyncio
async def test_run_auth_checked_watch_forwards_messages_while_valid():
    token = "valid-token"
    session.put(token, "alice")
    req = _make_request(cookie=f"cista={token}")
    ws = AsyncMock()
    q = asyncio.Queue()

    async def producer():
        await q.put('{"space":{}}')
        await q.put('{"update":[]}')
        # Keep consumer alive briefly, then invalidate.
        await asyncio.sleep(0.05)
        session._sessions.pop(token, None)
        await q.put('{"update":[]}')

    await asyncio.wait_for(
        asyncio.gather(producer(), run_auth_checked_watch(req, ws, q, None)),
        timeout=1.0,
    )

    calls = [c.args[0] for c in ws.send.call_args_list]
    assert calls[0] == '{"space":{}}'
    assert calls[1] == '{"update":[]}'
    assert '"error"' in calls[2]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_get_watch_user_info_token_auth_skips_revalidation():
    """Token-based auth is considered valid without re-checking the token."""
    token_id = "api-token"
    config.config.tokens[token_id] = config.Token(
        key=token_id, username="alice", kind="api", mode="rw"
    )
    req = _make_request(auth_token=config.config.tokens[token_id])

    info = await get_watch_user_info(req)

    assert info is None


@pytest.mark.asyncio
async def test_run_auth_checked_watch_token_auth_does_not_send_errors():
    """Token-based sockets keep forwarding messages without re-validating."""
    token_id = "api-token"
    config.config.tokens[token_id] = config.Token(
        key=token_id, username="alice", kind="api", mode="rw"
    )
    req = _make_request(auth_token=config.config.tokens[token_id])
    ws = AsyncMock()
    q = asyncio.Queue()

    async def producer():
        await q.put('{"space":{}}')
        await q.put('{"update":[]}')
        # Deleting the token should not affect the already-open websocket.
        await asyncio.sleep(0.05)
        del config.config.tokens[token_id]

    runner = asyncio.create_task(run_auth_checked_watch(req, ws, q, None))
    await asyncio.wait_for(producer(), timeout=1.0)
    await asyncio.sleep(0.05)
    runner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await runner

    calls = [c.args[0] for c in ws.send.call_args_list]
    assert calls[0] == '{"space":{}}'
    assert calls[1] == '{"update":[]}'
    assert not any('"error"' in c for c in calls)
