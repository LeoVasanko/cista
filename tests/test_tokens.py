from pathlib import Path, PurePath
from uuid import uuid4

import msgspec
import pytest
import pytest_asyncio
from sanic import Sanic

from cista import auth, config, watching
from cista.api import bp as api_bp
from cista.auth import bp as auth_bp


def _persist_config():
    def enc_hook(obj):
        if isinstance(obj, PurePath):
            return obj.as_posix()
        raise TypeError

    raw = msgspec.to_builtins(config.config, enc_hook=enc_hook)
    config.conffile.write_bytes(msgspec.toml.encode(raw))


@pytest.fixture
def setup_storage(tmp_path: Path):
    config.init_confdir(tmp_path)
    user = config.User()
    auth.set_password(user, "secret")
    admin = config.User(privileged=True)
    auth.set_password(admin, "secret")
    config.config = config.Config(
        path=tmp_path,
        listen=":0",
        public=False,
        users={"alice": user, "admin": admin},
    )
    _persist_config()
    watching.state.root = []
    watching.rootpath = tmp_path
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("A", encoding="utf-8")
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"token-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (
        *app.router.ALLOWED_METHODS,
        "MKCOL",
        "MOVE",
        "COPY",
        "PROPFIND",
    )
    app.blueprint(auth_bp)
    app.blueprint(api_bp)
    yield app.asgi_client


def _basic_auth(username: str, password: str) -> str:
    return f"Basic {__import__('base64').b64encode(f'{username}:{password}'.encode()).decode()}"


@pytest.mark.asyncio
async def test_token_crud(client):
    # Admin creates a token without specifying username (auto-assigned)
    _, res = await client.post(
        "/auth/tokens",
        json={"name": "test"},
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200
    data = res.json
    assert "id" in data
    assert "key" in data
    assert data["username"] == "admin"
    assert data["name"] == "test"
    token_id = data["id"]
    token_key = data["key"]

    # List tokens - admin sees only their own
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200
    tokens = res.json["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["id"] == token_id
    assert tokens[0]["username"] == "admin"

    # Use token via Basic auth (token:<secret>)
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("token", token_key)},
    )
    assert res.status_code == 200

    # Delete token
    _, res = await client.delete(
        f"/auth/tokens/{token_id}",
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200

    # List should be empty
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200
    assert len(res.json["tokens"]) == 0


@pytest.mark.asyncio
async def test_token_user_scoped(client):
    # Alice creates a token for herself (no username specified)
    _, res = await client.post(
        "/auth/tokens",
        json={"name": "alice-token"},
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 200
    alice_token_id = res.json["id"]
    alice_token_key = res.json["key"]

    # Admin creates a token for themselves
    _, res = await client.post(
        "/auth/tokens",
        json={"name": "admin-token"},
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200
    admin_token_id = res.json["id"]

    # Alice lists tokens - sees only her own
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 200
    tokens = res.json["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["id"] == alice_token_id
    assert tokens[0]["username"] == "alice"

    # Admin lists tokens - sees only their own
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("admin", "secret")},
    )
    assert res.status_code == 200
    tokens = res.json["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["id"] == admin_token_id
    assert tokens[0]["username"] == "admin"

    # Alice cannot create a token for admin
    _, res = await client.post(
        "/auth/tokens",
        json={"username": "admin", "name": "impersonation"},
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 403

    # Alice cannot delete admin's token
    _, res = await client.delete(
        f"/auth/tokens/{admin_token_id}",
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 403

    # Alice can delete her own token
    _, res = await client.delete(
        f"/auth/tokens/{alice_token_id}",
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 200

    # Alice's token auth still works until deletion is processed
    # Verify token auth worked during the test
    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("token", alice_token_key)},
    )
    # Token was deleted above, so this should now be unauthenticated
    # Actually the token key lookup will fail, and since there's no session fallback...
    # With auth header present but invalid, it should return 401
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_share_token(client):
    _, res = await client.post(
        "/api/share-tokens",
        json={"paths": ["hello.txt", "docs"], "mode": "ro", "name": "selection"},
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 200
    data = res.json
    assert data["kind"] == "share"
    assert data["mode"] == "ro"
    assert data["paths"] == ["hello.txt", "docs"]
    assert "token:" in data["url"]

    _, res = await client.get(
        "/auth/tokens",
        headers={"Authorization": _basic_auth("alice", "secret")},
    )
    assert res.status_code == 200
    share_tokens = [t for t in res.json["tokens"] if t.get("kind") == "share"]
    assert len(share_tokens) == 1
    assert share_tokens[0]["mode"] == "ro"
