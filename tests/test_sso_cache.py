from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sanic.exceptions import Unauthorized

from cista import sso


def _make_request(cookie: str = "", authorization: str = ""):
    req = SimpleNamespace()
    req.headers = {}
    if cookie:
        req.headers["cookie"] = cookie
    if authorization:
        req.headers["authorization"] = authorization
    req.client_ip = "127.0.0.1"
    req.host = "test.local"
    req.scheme = "http"
    req.ctx = SimpleNamespace()
    return req


@pytest.fixture(autouse=True)
def _reset_sso_cache_and_client(monkeypatch):
    """Clear the SSO validation cache and shared client between tests."""
    sso._validate_cache.clear()
    sso._client = None
    monkeypatch.setenv("PASKIA_BACKEND_URL", "http://test-paskia.local")
    monkeypatch.setattr(sso, "PASKIA_BACKEND_URL", "http://test-paskia.local")
    yield
    sso._validate_cache.clear()


@pytest.fixture
def mock_client(monkeypatch):
    client = AsyncMock()
    client.is_closed = False
    client.headers = {}
    monkeypatch.setattr(sso, "_client", client)
    return client


@pytest.mark.asyncio
async def test_validate_sso_request_caches_successful_responses(mock_client):
    req = _make_request(cookie="session=abc123")
    mock_client.post.return_value = httpx.Response(200, json={"user": "alice"})

    data1 = await sso.validate_sso_request(req)
    data2 = await sso.validate_sso_request(req)

    assert data1 == {"user": "alice"}
    assert data2 == data1
    assert mock_client.post.call_count == 1
    assert req.ctx.sso_user == {"user": "alice"}


@pytest.mark.asyncio
async def test_validate_sso_request_does_not_cache_errors(mock_client):
    req = _make_request(cookie="session=bad")
    mock_client.post.return_value = httpx.Response(401, json={"detail": "nope"})

    with pytest.raises(Unauthorized):
        await sso.validate_sso_request(req)
    with pytest.raises(Unauthorized):
        await sso.validate_sso_request(req)

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_validate_sso_request_cache_is_per_credential(mock_client):
    req_alice = _make_request(cookie="session=alice")
    req_bob = _make_request(cookie="session=bob")
    responses = {
        "alice": httpx.Response(200, json={"user": "alice"}),
        "bob": httpx.Response(200, json={"user": "bob"}),
    }

    def side_effect(*args, **kwargs):
        cookie = kwargs.get("headers", {}).get("cookie", "")
        if "alice" in cookie:
            return responses["alice"]
        return responses["bob"]

    mock_client.post.side_effect = side_effect

    assert await sso.validate_sso_request(req_alice) == {"user": "alice"}
    assert await sso.validate_sso_request(req_bob) == {"user": "bob"}
    assert await sso.validate_sso_request(req_alice) == {"user": "alice"}

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_validate_sso_request_cache_is_per_permission(mock_client):
    req = _make_request(cookie="session=abc123")
    mock_client.post.return_value = httpx.Response(200, json={"user": "alice"})

    await sso.validate_sso_request(req, perm="cista:login")
    await sso.validate_sso_request(req, perm="cista:admin")

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_validation_cache_forces_backend_call(mock_client):
    req = _make_request(cookie="session=abc123")
    mock_client.post.return_value = httpx.Response(200, json={"user": "alice"})

    await sso.validate_sso_request(req)
    sso.invalidate_validation_cache(req)
    await sso.validate_sso_request(req)

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_validation_cache_only_affects_same_credentials(mock_client):
    alice = _make_request(cookie="session=alice")
    bob = _make_request(cookie="session=bob")
    responses = {
        "alice": httpx.Response(200, json={"user": "alice"}),
        "bob": httpx.Response(200, json={"user": "bob"}),
    }

    def side_effect(*args, **kwargs):
        cookie = kwargs.get("headers", {}).get("cookie", "")
        return responses["alice"] if "alice" in cookie else responses["bob"]

    mock_client.post.side_effect = side_effect

    await sso.validate_sso_request(alice)
    await sso.validate_sso_request(bob)
    sso.invalidate_validation_cache(alice)

    assert await sso.validate_sso_request(alice) == {"user": "alice"}
    assert await sso.validate_sso_request(bob) == {"user": "bob"}

    # Alice is re-fetched; bob is still cached.
    assert mock_client.post.call_count == 3
