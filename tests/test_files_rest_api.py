from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import config, watching
from cista.fileserver import bp as fileserver_bp
from cista.protocol import FileEntry


@pytest.fixture
def setup_storage(tmp_path: Path):
    config.config = config.Config(path=tmp_path, listen=":0", public=True)
    watching.state.root = []
    watching.rootpath = tmp_path
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"files-rest-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (
        *app.router.ALLOWED_METHODS,
        "MKCOL",
        "MOVE",
        "COPY",
        "PROPFIND",
    )
    app.blueprint(fileserver_bp)
    yield app.asgi_client


@pytest.mark.asyncio
async def test_mkcol_creates_directory(client, setup_storage: Path):
    _, res = await client.request("MKCOL", "/files/new-folder")

    assert res.status_code == 201
    assert (setup_storage / "new-folder").is_dir()


@pytest.mark.asyncio
async def test_delete_removes_file(client, setup_storage: Path):
    file_path = setup_storage / "delete-me.txt"
    file_path.write_text("hello", encoding="utf-8")

    _, res = await client.delete("/files/delete-me.txt")

    assert res.status_code == 204
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_post_mv_moves_keys_to_target(client, setup_storage: Path):
    (setup_storage / "target").mkdir()
    (setup_storage / "alpha.txt").write_text("alpha", encoding="utf-8")
    (setup_storage / "beta.txt").write_text("beta", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "target", "k-target", 0, 0, 0, 0),
        FileEntry(1, "alpha.txt", "k-alpha", 0, 5, 0, 1),
        FileEntry(1, "beta.txt", "k-beta", 0, 4, 0, 1),
    ]

    _, res = await client.post("/files/target?mv=k-alpha+k-beta")

    assert res.status_code == 200
    assert res.json["status"] == "ack"
    assert not (setup_storage / "alpha.txt").exists()
    assert not (setup_storage / "beta.txt").exists()
    assert (setup_storage / "target" / "alpha.txt").is_file()
    assert (setup_storage / "target" / "beta.txt").is_file()


@pytest.mark.asyncio
async def test_post_cp_copies_keys_to_target(client, setup_storage: Path):
    (setup_storage / "target").mkdir()
    (setup_storage / "copy-me.txt").write_text("copy", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "target", "k-target", 0, 0, 0, 0),
        FileEntry(1, "copy-me.txt", "k-copy", 0, 4, 0, 1),
    ]

    _, res = await client.post("/files/target?cp=k-copy")

    assert res.status_code == 200
    assert res.json["counts"] == {"cp": 1, "mv": 0}
    assert (setup_storage / "copy-me.txt").is_file()
    assert (setup_storage / "target" / "copy-me.txt").is_file()


@pytest.mark.asyncio
async def test_post_cp_repeated_params_and_plus_form_are_equivalent(
    client,
    setup_storage: Path,
):
    (setup_storage / "target").mkdir()
    (setup_storage / "one.txt").write_text("one", encoding="utf-8")
    (setup_storage / "two.txt").write_text("two", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "target", "k-target", 0, 0, 0, 0),
        FileEntry(1, "one.txt", "k-one", 0, 3, 0, 1),
        FileEntry(1, "two.txt", "k-two", 0, 3, 0, 1),
    ]

    _, res1 = await client.post("/files/target?cp=k-one&cp=k-two")

    assert res1.status_code == 200
    assert (setup_storage / "target" / "one.txt").is_file()
    assert (setup_storage / "target" / "two.txt").is_file()

    (setup_storage / "target" / "one.txt").unlink()
    (setup_storage / "target" / "two.txt").unlink()

    _, res2 = await client.post("/files/target?cp=k-one+k-two")

    assert res2.status_code == 200
    assert (setup_storage / "target" / "one.txt").is_file()
    assert (setup_storage / "target" / "two.txt").is_file()


@pytest.mark.asyncio
async def test_post_mv_with_to_renames_single_key(
    client,
    setup_storage: Path,
):
    (setup_storage / "dst").mkdir()
    (setup_storage / "old-name.txt").write_text("x", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "dst", "k-dst", 0, 0, 0, 0),
        FileEntry(1, "old-name.txt", "k-old", 0, 1, 0, 1),
    ]

    _, res = await client.post("/files/dst/new-name.txt?mv=k-old")

    assert res.status_code == 200
    assert not (setup_storage / "old-name.txt").exists()
    assert (setup_storage / "dst" / "new-name.txt").is_file()


@pytest.mark.asyncio
async def test_post_cp_single_key_to_file_path(client, setup_storage: Path):
    (setup_storage / "dst").mkdir()
    (setup_storage / "src.txt").write_text("copy", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "dst", "k-dst", 0, 0, 0, 0),
        FileEntry(1, "src.txt", "k-src", 0, 4, 0, 1),
    ]

    _, res = await client.post("/files/dst/copied.txt?cp=k-src")

    assert res.status_code == 200
    assert (setup_storage / "src.txt").is_file()
    assert (setup_storage / "dst" / "copied.txt").is_file()


@pytest.mark.asyncio
async def test_post_supports_combined_cp_then_mv(client, setup_storage: Path):
    (setup_storage / "target").mkdir()
    (setup_storage / "copy-me.txt").write_text("copy", encoding="utf-8")
    (setup_storage / "move-me.txt").write_text("move", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "target", "k-target", 0, 0, 0, 0),
        FileEntry(1, "copy-me.txt", "k-copy", 0, 4, 0, 1),
        FileEntry(1, "move-me.txt", "k-move", 0, 4, 0, 1),
    ]

    _, res = await client.post("/files/target?cp=k-copy&mv=k-move")

    assert res.status_code == 200
    assert res.json["counts"] == {"cp": 1, "mv": 1}
    assert (setup_storage / "copy-me.txt").is_file()
    assert not (setup_storage / "move-me.txt").exists()
    assert (setup_storage / "target" / "copy-me.txt").is_file()
    assert (setup_storage / "target" / "move-me.txt").is_file()


@pytest.mark.asyncio
async def test_post_rejects_unknown_query_args(client):
    _, res = await client.post("/files/?cp=k1&wat=1")

    assert res.status_code == 400
    assert "unknown query parameter" in res.json["message"].lower()


@pytest.mark.asyncio
async def test_post_requires_query_args(client):
    _, res = await client.post("/files/")

    assert res.status_code == 400
    assert "no query arguments" in res.json["message"].lower()


@pytest.mark.asyncio
async def test_post_rejects_multiple_keys_to_file_target(client, setup_storage: Path):
    (setup_storage / "a.txt").write_text("a", encoding="utf-8")
    (setup_storage / "b.txt").write_text("b", encoding="utf-8")
    (setup_storage / "target.txt").write_text("x", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "a.txt", "k-a", 0, 1, 0, 1),
        FileEntry(1, "b.txt", "k-b", 0, 1, 0, 1),
        FileEntry(1, "target.txt", "k-target", 0, 1, 0, 1),
    ]

    _, cp_res = await client.post("/files/target.txt?cp=k-a+k-b")
    _, mv_res = await client.post("/files/target.txt?mv=k-a+k-b")

    assert cp_res.status_code == 400
    assert "existing directory" in cp_res.json["message"].lower()
    assert mv_res.status_code == 400
    assert "existing directory" in mv_res.json["message"].lower()


@pytest.mark.asyncio
async def test_post_rejects_directory_to_existing_file_target(
    client, setup_storage: Path
):
    (setup_storage / "folder").mkdir()
    (setup_storage / "folder" / "nested.txt").write_text("n", encoding="utf-8")
    (setup_storage / "existing.txt").write_text("e", encoding="utf-8")

    watching.state.root = [
        FileEntry(1, "folder", "k-folder", 0, 0, 0, 0),
        FileEntry(2, "nested.txt", "k-nested", 0, 1, 0, 1),
        FileEntry(1, "existing.txt", "k-existing", 0, 1, 0, 1),
    ]

    _, cp_res = await client.post("/files/existing.txt?cp=k-folder")
    _, mv_res = await client.post("/files/existing.txt?mv=k-folder")

    assert cp_res.status_code == 400
    assert "directory to an existing file" in cp_res.json["message"].lower()
    assert mv_res.status_code == 400
    assert "directory to an existing file" in mv_res.json["message"].lower()
