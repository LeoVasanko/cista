import tempfile
from pathlib import Path

import pytest

from cista import config
from cista.protocol import Cp, MkDir, Mv, Rename, Rm


@pytest.fixture()
def setup_temp_dir():
    with tempfile.TemporaryDirectory() as tmpdirname:
        config.config = config.Config(path=Path(tmpdirname), listen=":0")
        yield Path(tmpdirname)


def test_mkdir(setup_temp_dir):
    cmd = MkDir(path="new_folder")
    cmd()
    assert (setup_temp_dir / "new_folder").is_dir()


def test_rename(setup_temp_dir):
    (setup_temp_dir / "old_name").mkdir()
    cmd = Rename(path="old_name", to="new_name")
    cmd()
    assert not (setup_temp_dir / "old_name").exists()
    assert (setup_temp_dir / "new_name").is_dir()


def test_rm(setup_temp_dir):
    (setup_temp_dir / "folder_to_remove").mkdir()
    cmd = Rm(sel=["folder_to_remove"])
    cmd()
    assert not (setup_temp_dir / "folder_to_remove").exists()


def test_mv(setup_temp_dir):
    (setup_temp_dir / "folder_to_move").mkdir()
    (setup_temp_dir / "destination").mkdir()
    cmd = Mv(sel=["folder_to_move"], dst="destination")
    cmd()
    assert not (setup_temp_dir / "folder_to_move").exists()
    assert (setup_temp_dir / "destination" / "folder_to_move").is_dir()


def test_cp(setup_temp_dir):
    (setup_temp_dir / "folder_to_copy").mkdir()
    (setup_temp_dir / "destination").mkdir()
    cmd = Cp(sel=["folder_to_copy"], dst="destination")
    cmd()
    assert (setup_temp_dir / "folder_to_copy").is_dir()
    assert (setup_temp_dir / "destination" / "folder_to_copy").is_dir()
