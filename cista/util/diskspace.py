import shutil
import threading
import time
from pathlib import Path

MIN_FREE_BYTES = 128 * 1024 * 1024
_CHECK_CACHE_TTL = 1.0


class InsufficientStorageError(Exception):
    """Raised when there is not enough disk space for an operation."""


_cache: dict[Path, tuple[float, int]] = {}
_lock = threading.Lock()


def check_free_space(path: Path) -> None:
    """Raise InsufficientStorageError if free space on the filesystem containing *path*

    is below MIN_FREE_BYTES. Results are cached per directory for 1 second.
    """
    check_path = path.parent if path.parent.exists() else path
    check_path = check_path.resolve()

    now = time.monotonic()
    with _lock:
        ts, free = _cache.get(check_path, (0, 0))
        if now - ts < _CHECK_CACHE_TTL:
            if free < MIN_FREE_BYTES:
                raise InsufficientStorageError(
                    f"Insufficient storage: {free} bytes free, "
                    f"need at least {MIN_FREE_BYTES} bytes"
                )
            return

    try:
        free = shutil.disk_usage(check_path).free
    except OSError as e:
        raise InsufficientStorageError(f"Cannot check disk usage: {e}") from e

    with _lock:
        _cache[check_path] = (now, free)

    if free < MIN_FREE_BYTES:
        raise InsufficientStorageError(
            f"Insufficient storage: {free} bytes free, "
            f"need at least {MIN_FREE_BYTES} bytes"
        )
