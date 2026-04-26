"""WebDAV protocol tests: OPTIONS, PROPFIND, PROPPATCH, COPY, MOVE, LOCK, UNLOCK."""
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import config, watching
from cista.fileserver import bp as fileserver_bp
from cista.protocol import FileEntry

_DAV_NS = "DAV:"
_METHODS = ("MKCOL", "MOVE", "COPY", "PROPFIND")


@pytest.fixture()
def setup_storage(tmp_path: Path):
    config.config = config.Config(path=tmp_path, listen=":0", public=True)
    watching.state.root = []
    watching.rootpath = tmp_path
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"files-dav-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (*app.router.ALLOWED_METHODS, *_METHODS)
    app.blueprint(fileserver_bp)
    yield app.asgi_client


def _dav(tag: str) -> str:
    return f"{{{_DAV_NS}}}{tag}"


def _parse_multistatus(body: bytes) -> list[ET.Element]:
    root = ET.fromstring(body)
    assert root.tag == _dav("multistatus")
    return root.findall(_dav("response"))


# ---------------------------------------------------------------------------
# OPTIONS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_advertises_dav_class(client):
    _, res = await client.options("/files/")

    assert res.status_code == 200
    assert "1" in res.headers.get("dav", "")
    assert "PROPFIND" in res.headers.get("allow", "")
    assert "COPY" in res.headers.get("allow", "")
    assert "MOVE" in res.headers.get("allow", "")


@pytest.mark.asyncio
async def test_options_without_trailing_slash(client):
    """WebDAV clients (e.g. Windows) send OPTIONS /files without trailing slash."""
    _, res = await client.options("/files")

    assert res.status_code == 200
    assert "1" in res.headers.get("dav", "")


# ---------------------------------------------------------------------------
# PROPFIND
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propfind_root_depth0(client, setup_storage: Path):
    _, res = await client.request("PROPFIND", "/files/", headers={"Depth": "0"})

    assert res.status_code == 207
    responses = _parse_multistatus(res.body)
    assert len(responses) == 1
    href = responses[0].findtext(_dav("href"))
    assert href == "/files/"
    rt = responses[0].find(f".//{_dav('resourcetype')}/{_dav('collection')}")
    assert rt is not None, "Root should be a collection"


@pytest.mark.asyncio
async def test_propfind_root_depth1_lists_children(client, setup_storage: Path):
    (setup_storage / "alpha.txt").write_text("a", encoding="utf-8")
    (setup_storage / "beta").mkdir()

    _, res = await client.request("PROPFIND", "/files/", headers={"Depth": "1"})

    assert res.status_code == 207
    responses = _parse_multistatus(res.body)
    hrefs = [r.findtext(_dav("href")) for r in responses]
    assert "/files/" in hrefs
    assert "/files/alpha.txt" in hrefs
    assert "/files/beta/" in hrefs


@pytest.mark.asyncio
async def test_propfind_file_has_content_length(client, setup_storage: Path):
    (setup_storage / "data.txt").write_text("hello", encoding="utf-8")

    _, res = await client.request("PROPFIND", "/files/data.txt", headers={"Depth": "0"})

    assert res.status_code == 207
    responses = _parse_multistatus(res.body)
    cl = responses[0].findtext(f".//{_dav('getcontentlength')}")
    assert cl == "5"


@pytest.mark.asyncio
async def test_propfind_depth_infinity_rejected(client, setup_storage: Path):
    _, res = await client.request(
        "PROPFIND", "/files/", headers={"Depth": "infinity"}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_propfind_missing_resource_returns_404(client):
    _, res = await client.request("PROPFIND", "/files/no-such-file.txt")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# COPY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_file_to_new_path(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("copy me", encoding="utf-8")

    _, res = await client.request(
        "COPY",
        "/files/src.txt",
        headers={"Destination": "http://localhost/files/dst.txt"},
    )

    assert res.status_code == 201
    assert (setup_storage / "src.txt").is_file()
    assert (setup_storage / "dst.txt").read_text() == "copy me"


@pytest.mark.asyncio
async def test_copy_overwrites_existing_by_default(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("new", encoding="utf-8")
    (setup_storage / "dst.txt").write_text("old", encoding="utf-8")

    _, res = await client.request(
        "COPY",
        "/files/src.txt",
        headers={"Destination": "http://localhost/files/dst.txt"},
    )

    assert res.status_code == 204
    assert (setup_storage / "dst.txt").read_text() == "new"


@pytest.mark.asyncio
async def test_copy_overwrite_false_returns_412(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("x", encoding="utf-8")
    (setup_storage / "dst.txt").write_text("y", encoding="utf-8")

    _, res = await client.request(
        "COPY",
        "/files/src.txt",
        headers={
            "Destination": "http://localhost/files/dst.txt",
            "Overwrite": "F",
        },
    )

    assert res.status_code == 412
    assert (setup_storage / "dst.txt").read_text() == "y"


@pytest.mark.asyncio
async def test_copy_directory_recursively(client, setup_storage: Path):
    (setup_storage / "src").mkdir()
    (setup_storage / "src" / "child.txt").write_text("child", encoding="utf-8")

    _, res = await client.request(
        "COPY",
        "/files/src",
        headers={"Destination": "http://localhost/files/dst"},
    )

    assert res.status_code == 201
    assert (setup_storage / "dst" / "child.txt").read_text() == "child"
    assert (setup_storage / "src" / "child.txt").is_file()


@pytest.mark.asyncio
async def test_copy_missing_parent_returns_409(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("x", encoding="utf-8")

    _, res = await client.request(
        "COPY",
        "/files/src.txt",
        headers={"Destination": "http://localhost/files/nodir/dst.txt"},
    )

    assert res.status_code == 409


# ---------------------------------------------------------------------------
# MOVE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_renames_file(client, setup_storage: Path):
    (setup_storage / "old.txt").write_text("data", encoding="utf-8")

    _, res = await client.request(
        "MOVE",
        "/files/old.txt",
        headers={"Destination": "http://localhost/files/new.txt"},
    )

    assert res.status_code == 201
    assert not (setup_storage / "old.txt").exists()
    assert (setup_storage / "new.txt").read_text() == "data"


@pytest.mark.asyncio
async def test_move_overwrites_existing(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("src", encoding="utf-8")
    (setup_storage / "dst.txt").write_text("dst", encoding="utf-8")

    _, res = await client.request(
        "MOVE",
        "/files/src.txt",
        headers={"Destination": "http://localhost/files/dst.txt"},
    )

    assert res.status_code == 204
    assert not (setup_storage / "src.txt").exists()
    assert (setup_storage / "dst.txt").read_text() == "src"


@pytest.mark.asyncio
async def test_move_overwrite_false_returns_412(client, setup_storage: Path):
    (setup_storage / "src.txt").write_text("src", encoding="utf-8")
    (setup_storage / "dst.txt").write_text("dst", encoding="utf-8")

    _, res = await client.request(
        "MOVE",
        "/files/src.txt",
        headers={
            "Destination": "http://localhost/files/dst.txt",
            "Overwrite": "F",
        },
    )

    assert res.status_code == 412
    assert (setup_storage / "src.txt").is_file()


@pytest.mark.asyncio
async def test_move_same_source_and_dest_is_noop(client, setup_storage: Path):
    (setup_storage / "file.txt").write_text("x", encoding="utf-8")

    _, res = await client.request(
        "MOVE",
        "/files/file.txt",
        headers={"Destination": "http://localhost/files/file.txt"},
    )

    assert res.status_code == 204
    assert (setup_storage / "file.txt").is_file()
