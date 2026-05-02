import base64
import hashlib
import hmac
import struct
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from Crypto.Hash import MD4
from sanic import Sanic

from cista import auth, config, session, watching
from cista.app import use_session
from cista.fileserver import bp as fileserver_bp


def _basic_auth(username: str, password: str) -> dict[str, str]:
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def _ntlm_type1() -> dict[str, str]:
    msg = b"NTLMSSP\x00" + struct.pack("<I", 1) + struct.pack("<I", 0x20080205)
    return {"Authorization": f"NTLM {base64.b64encode(msg).decode()}"}


def _ntlm_type3(
    username: str, password: str, domain: str, challenge: bytes
) -> dict[str, str]:
    """Build an NTLMv2 Type 3 message for testing."""
    # NT hash
    nt_hash = MD4.new(password.encode("utf-16le")).digest()
    # NTLMv2 hash
    ntlmv2_hash = hmac.new(
        nt_hash, (username.upper() + domain).encode("utf-16le"), hashlib.md5
    ).digest()

    # Build a minimal blob
    timestamp = struct.pack("<Q", 0)
    client_nonce = b"\x01" * 8
    blob = (
        b"\x01\x01\x00\x00\x00\x00\x00\x00"
        + timestamp
        + client_nonce
        + b"\x00\x00\x00\x00"
    )

    # NT proof
    nt_proof = hmac.new(ntlmv2_hash, challenge + blob, hashlib.md5).digest()
    nt_response = nt_proof + blob

    domain_enc = domain.encode("utf-16le")
    username_enc = username.encode("utf-16le")
    workstation_enc = b""

    lm_response = b""  # Empty for NTLMv2

    # Build Type 3 message
    msg = bytearray()
    msg.extend(b"NTLMSSP\x00")
    msg.extend(struct.pack("<I", 3))

    # Security buffers offsets will be calculated
    payload_start = 64
    payloads = []

    def add_buf(data: bytes):
        offset = payload_start + sum(len(p) for p in payloads)
        payloads.append(data)
        return struct.pack("<HHI", len(data), len(data), offset)

    lm_buf = add_buf(lm_response)
    nt_buf = add_buf(nt_response)
    domain_buf = add_buf(domain_enc)
    user_buf = add_buf(username_enc)
    ws_buf = add_buf(workstation_enc)
    session_buf = add_buf(b"")

    msg.extend(lm_buf)
    msg.extend(nt_buf)
    msg.extend(domain_buf)
    msg.extend(user_buf)
    msg.extend(ws_buf)
    msg.extend(session_buf)
    msg.extend(struct.pack("<I", 0x20080205))
    for p in payloads:
        msg.extend(p)

    return {"Authorization": f"NTLM {base64.b64encode(bytes(msg)).decode()}"}


def _session_cookie_header(username: str) -> dict[str, str]:
    token = "test-" + username
    session.put(token, username)
    return {"Cookie": f"cista={token}"}


@pytest.fixture
def setup_storage(tmp_path: Path):
    user = config.User()
    auth.set_password(user, "secret")
    token = config.Token(key="test_token_123", username="alice")
    share_ro = config.Token(
        key="share_ro_123",
        username="alice",
        kind="share",
        mode="ro",
        share_paths=["hello.txt", "docs"],
    )
    share_rw = config.Token(
        key="share_rw_123",
        username="alice",
        kind="share",
        mode="rw",
        share_paths=["docs"],
    )
    config.config = config.Config(
        path=tmp_path,
        listen=":0",
        public=False,
        users={"alice": user},
        tokens={
            "test_token_123": token,
            "share_ro_123": share_ro,
            "share_rw_123": share_rw,
        },
    )
    watching.state.root = []
    watching.rootpath = tmp_path
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "docs" / "b.txt").write_text("B", encoding="utf-8")
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"files-auth-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (
        *app.router.ALLOWED_METHODS,
        "MKCOL",
        "MOVE",
        "COPY",
        "PROPFIND",
    )

    @app.on_request
    async def load_auth_context(request):
        await use_session(request)

    app.blueprint(fileserver_bp)
    yield app.asgi_client


@pytest.mark.asyncio
async def test_basic_auth_allows_private_file_access(client):
    _, res = await client.get(
        "/files/hello.txt", headers=_basic_auth("alice", "secret")
    )

    assert res.status_code == 200
    assert res.body == b"hello"
    assert "set-cookie" not in res.headers


@pytest.mark.asyncio
async def test_basic_auth_with_invalid_creds_falls_back_to_session_cookie(client):
    _, res = await client.get(
        "/files/hello.txt",
        headers={**_basic_auth("alice", "wrong"), **_session_cookie_header("alice")},
    )

    assert res.status_code == 200


@pytest.mark.asyncio
async def test_options_unauthenticated_allowed(client):
    _, res = await client.options("/files/")

    assert res.status_code == 200


@pytest.mark.asyncio
async def test_unauthenticated_sends_basic_auth_challenge(client):
    _, res = await client.request("PROPFIND", "/files/")

    assert res.status_code == 401
    assert (
        res.headers.get("www-authenticate", "")
        .lower()
        .startswith('basic realm="cista"')
    )


@pytest.mark.asyncio
async def test_basic_auth_with_token(client):
    _, res = await client.get(
        "/files/hello.txt", headers=_basic_auth("token", "test_token_123")
    )

    assert res.status_code == 200
    assert res.body == b"hello"


@pytest.mark.asyncio
async def test_browser_unauthenticated_sends_cookie_challenge(client):
    _, res = await client.get(
        "/files/", headers={"Accept": "text/html,application/xhtml+xml"}
    )

    assert res.status_code == 401
    assert res.headers.get("www-authenticate", "").lower().startswith("cookie")


@pytest.mark.asyncio
async def test_ntlm_auth_with_token(client):
    # Step 1: request without auth should NOT advertise NTLM
    # (we prefer clients use BASIC; NTLM still works if client initiates it)
    _, res1 = await client.get("/files/hello.txt")
    assert res1.status_code == 401
    assert "ntlm" not in res1.headers.get("www-authenticate", "").lower()

    # Step 2: client proactively sends Type 1, gets Type 2 challenge
    _, res2 = await client.get("/files/hello.txt", headers=_ntlm_type1())
    assert res2.status_code == 401
    auth_hdr = res2.headers.get("www-authenticate", "")
    assert auth_hdr.lower().startswith("ntlm ")
    type2_data = base64.b64decode(auth_hdr.split(" ", 1)[1])
    challenge = type2_data[24:32]

    # Step 3: send Type 3 with token as password
    _, res3 = await client.get(
        "/files/hello.txt",
        headers=_ntlm_type3("anyuser", "test_token_123", "WORKGROUP", challenge),
    )
    assert res3.status_code == 200
    assert res3.body == b"hello"


@pytest.mark.asyncio
async def test_share_token_limits_visible_paths(client):
    _, res = await client.get(
        "/files/docs/a.txt", headers=_basic_auth("token", "share_ro_123")
    )
    assert res.status_code == 200
    assert res.body == b"A"

    _, res = await client.get(
        "/files/hello.txt", headers=_basic_auth("token", "share_ro_123")
    )
    assert res.status_code == 200
    assert res.body == b"hello"

    _, res = await client.get(
        "/files/secret.txt", headers=_basic_auth("token", "share_ro_123")
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_share_token_read_only_blocks_writes(client):
    _, res = await client.delete(
        "/files/hello.txt", headers=_basic_auth("token", "share_ro_123")
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_share_token_rw_allows_writes_in_scope_only(client):
    _, res = await client.delete(
        "/files/docs/a.txt", headers=_basic_auth("token", "share_rw_123")
    )
    assert res.status_code == 204

    _, res = await client.get(
        "/files/docs/a.txt", headers=_basic_auth("token", "share_rw_123")
    )
    assert res.status_code == 404

    _, res = await client.delete(
        "/files/secret.txt", headers=_basic_auth("token", "share_rw_123")
    )
    assert res.status_code == 404
