"""Path traversal and percent-encoding security tests for the fileserver."""
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import config, watching
from cista.fileserver import bp as fileserver_bp


@pytest.fixture
def setup_storage(tmp_path: Path):
    config.config = config.Config(path=tmp_path, listen=":0", public=True)
    watching.state.root = []
    watching.rootpath = tmp_path
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"files-path-sec-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (*app.router.ALLOWED_METHODS, "MKCOL", "MOVE", "COPY", "PROPFIND")
    app.blueprint(fileserver_bp)
    yield app.asgi_client


# ---------------------------------------------------------------------------
# %2F — encoded slash should be decoded as a path separator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_percent2f_decoded_as_path_separator(client, setup_storage: Path):
    """%2F in the URL path is decoded to '/' and treated as a path separator."""
    (setup_storage / "sub").mkdir()
    (setup_storage / "sub" / "file.txt").write_text("hello", encoding="utf-8")

    _, res = await client.get("/files/sub%2Ffile.txt")

    assert res.status_code == 200
    assert res.text == "hello"


@pytest.mark.asyncio
async def test_mkcol_percent2f_creates_nested_directory(client, setup_storage: Path):
    """%2F in MKCOL path is decoded as a separator, creating nested dirs."""
    _, res = await client.request("MKCOL", "/files/parent%2Fchild")

    assert res.status_code == 201
    assert (setup_storage / "parent" / "child").is_dir()


# ---------------------------------------------------------------------------
# %20 — encoded space in filename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_percent20_in_filename(client, setup_storage: Path):
    (setup_storage / "my file.txt").write_text("spaced", encoding="utf-8")

    _, res = await client.get("/files/my%20file.txt")

    assert res.status_code == 200
    assert res.text == "spaced"


@pytest.mark.asyncio
async def test_mkcol_percent20_in_folder_name(client, setup_storage: Path):
    _, res = await client.request("MKCOL", "/files/my%20folder")

    assert res.status_code == 201
    assert (setup_storage / "my folder").is_dir()


# ---------------------------------------------------------------------------
# Path traversal — .. and encoded variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dotdot_rejected(client):
    """.. is path-normalised by the router before reaching the handler."""
    _, res = await client.get("/files/..")
    assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_get_dotdot_segment_rejected(client):
    """Traversal via sub/../.. is path-normalised by the router."""
    _, res = await client.get("/files/sub/../..")
    assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_get_encoded_dotdot_rejected(client):
    """%2E%2E (encoded ..) must be rejected."""
    _, res = await client.get("/files/%2E%2E")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_get_encoded_dotdot_segment_rejected(client):
    """%2E%2E used as a segment in a longer path must be rejected."""
    _, res = await client.get("/files/sub%2F%2E%2E%2F..%2Fetc%2Fpasswd")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_mkcol_dotdot_rejected(client):
    _, res = await client.request("MKCOL", "/files/..")
    assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_delete_dotdot_rejected(client):
    _, res = await client.delete("/files/..")
    assert res.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Dot-prefixed filenames (.hidden, ...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hidden_file_rejected(client):
    """Names starting with '.' are not allowed."""
    _, res = await client.get("/files/.hidden")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_mkcol_hidden_folder_rejected(client):
    _, res = await client.request("MKCOL", "/files/.secret")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Windows-style drive paths (c:/) — safe on Linux, stays inside storage root
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mkcol_windows_drive_path_stays_within_root(client, setup_storage: Path):
    """A Windows-style drive path like 'c:/foo' is treated as a relative path
    on Linux and resolves safely inside the storage root."""
    _, res = await client.request("MKCOL", "/files/c:/secret")

    # Either created inside the storage root (201) or sanitised away (400/404).
    # The important assertion: nothing was created outside the storage root.
    assert not (Path("/c:") / "secret").exists()
    assert not (Path("c:/secret")).exists()
    if res.status_code == 201:
        # Created safely inside tmp storage
        assert (setup_storage / "c:" / "secret").is_dir()


@pytest.mark.asyncio
async def test_mkcol_backslash_in_path_sanitised(client, setup_storage: Path):
    """Backslashes are replaced with dashes, not treated as path separators."""
    _, res = await client.request("MKCOL", "/files/foo\\..\\bar")

    assert res.status_code in (201, 400)
    # Must not escape storage root
    assert not (setup_storage.parent / "bar").exists()
