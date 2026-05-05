import errno
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sanic import Sanic

from cista import config, watching
from cista.api import fileserver
from cista.fileserver import bp as fileserver_bp


class Usage(NamedTuple):
    total: int
    used: int
    free: int


def _low_disk_usage(*args, **kwargs):
    return Usage(total=1000, used=900, free=10)


@pytest.fixture
def setup_storage(tmp_path: Path):
    config.config = config.Config(path=tmp_path, listen=":0", public=True)
    watching.state.root = []
    watching.rootpath = tmp_path
    yield tmp_path
    watching.state.root = []


@pytest_asyncio.fixture()
async def client(setup_storage: Path):
    app = Sanic(f"disk-space-test-{uuid4().hex}", strict_slashes=True)
    app.router.ALLOWED_METHODS = (
        *app.router.ALLOWED_METHODS,
        "MKCOL",
        "MOVE",
        "COPY",
        "PROPFIND",
    )
    app.blueprint(fileserver_bp)
    await fileserver.start()
    yield app.asgi_client
    await fileserver.stop()


@pytest.mark.asyncio
async def test_upload_rejected_when_disk_low(client):
    with patch("cista.util.diskspace.shutil.disk_usage", side_effect=_low_disk_usage):
        _, res = await client.put("/files/test.txt", data=b"hello world")
    assert res.status_code == 507


@pytest.mark.asyncio
async def test_upload_rejected_on_enospc(client):
    with patch(
        "cista.fileio.os.write",
        side_effect=OSError(errno.ENOSPC, "No space left on device"),
    ):
        _, res = await client.put("/files/test.txt", data=b"hello world")
    assert res.status_code == 507
