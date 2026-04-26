from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import config, watching
from cista.fileserver import bp as fileserver_bp


@pytest.fixture()
def setup_storage(tmp_path: Path):
    config.config = config.Config(path=tmp_path, listen=":0", public=True)
    watching.state.root = []
    watching.rootpath = tmp_path
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"files-static-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (*app.router.ALLOWED_METHODS, "MKCOL", "MOVE", "COPY", "PROPFIND")
    app.blueprint(fileserver_bp)
    yield app.asgi_client


@pytest.mark.asyncio
async def test_get_file_full_content(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.get("/files/hello.txt")

    assert res.status_code == 200
    assert res.body == b"hello world"
    assert res.headers.get("accept-ranges") == "bytes"
    assert res.headers.get("content-length") == "11"


@pytest.mark.asyncio
async def test_head_file_returns_headers_without_body(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.head("/files/hello.txt")

    assert res.status_code == 200
    assert not res.body
    assert res.headers.get("content-length") == "11"


@pytest.mark.asyncio
async def test_get_file_range_start_end(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.get("/files/hello.txt", headers={"Range": "bytes=1-4"})

    assert res.status_code == 206
    assert res.body == b"ello"
    assert res.headers.get("content-range") == "bytes 1-4/11"
    assert res.headers.get("content-length") == "4"


@pytest.mark.asyncio
async def test_get_file_suffix_range(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.get("/files/hello.txt", headers={"Range": "bytes=-5"})

    assert res.status_code == 206
    assert res.body == b"world"
    assert res.headers.get("content-range") == "bytes 6-10/11"


@pytest.mark.asyncio
async def test_head_file_with_range(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.head("/files/hello.txt", headers={"Range": "bytes=0-4"})

    assert res.status_code == 206
    assert not res.body
    assert res.headers.get("content-range") == "bytes 0-4/11"
    assert res.headers.get("content-length") == "5"


@pytest.mark.asyncio
async def test_get_file_unsatisfiable_range_returns_416(client, setup_storage: Path):
    path = setup_storage / "hello.txt"
    path.write_bytes(b"hello world")

    _, res = await client.get("/files/hello.txt", headers={"Range": "bytes=99-100"})

    assert res.status_code == 416
    assert res.headers.get("content-range") == "bytes */11"
