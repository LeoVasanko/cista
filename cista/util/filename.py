import unicodedata
from pathlib import PurePosixPath

from pathvalidate import sanitize_filepath


def sanitize(filename: str) -> str:
    filename = unicodedata.normalize("NFC", filename)
    # UNIX filenames can contain backslashes but for compatibility we replace them with dashes
    filename = filename.replace("\\", "-")
    filename = sanitize_filepath(filename)
    filename = filename.strip("/")
    p = PurePosixPath(filename)
    if any(n.startswith(".") for n in p.parts):
        raise ValueError("Filenames starting with dot are not allowed")
    return p.as_posix()
