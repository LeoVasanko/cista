import unicodedata
from pathlib import PurePosixPath

from pathvalidate import sanitize_filepath


def sanitize(filename: str) -> str:
    filename = unicodedata.normalize("NFC", filename)
    # UNIX filenames can contain backslashes but for compatibility we replace them with dashes
    filename = filename.replace("\\", "-")
    filename = sanitize_filepath(filename)
    filename = filename.strip("/")
    return PurePosixPath(filename).as_posix()
