import asyncio
import os

from cista import config
from cista.util import filename
from cista.util.asynclink import AsyncLink
from cista.util.lrucache import LRUCache


def fuid(stat) -> str:
    """Unique file ID. Stays the same on renames and modification."""
    return config.derived_secret("filekey-inode", stat.st_dev, stat.st_ino).hex()


class File:
    def __init__(self, filename):
        self.path = config.config.path / filename
        self.fd = None
        self.writable = False

    def open_ro(self):
        self.close()
        self.fd = os.open(self.path, os.O_RDONLY)

    def open_rw(self):
        self.close()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        self.writable = True

    def write(self, pos, buffer, *, file_size=None):
        if not self.writable:
            # Create/open file
            self.open_rw()
        assert self.fd is not None
        if file_size is not None:
            assert pos + len(buffer) <= file_size
            os.ftruncate(self.fd, file_size)
        if buffer:
            os.lseek(self.fd, pos, os.SEEK_SET)
            os.write(self.fd, buffer)

    def __getitem__(self, slice):
        if self.fd is None:
            self.open_ro()
        assert self.fd is not None
        os.lseek(self.fd, slice.start, os.SEEK_SET)
        size = slice.stop - slice.start
        data = os.read(self.fd, size)
        if len(data) < size:
            raise EOFError("Error reading requested range")
        return data

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = self.writable = None

    def __del__(self):
        self.close()


class FileServer:
    async def start(self):
        self.alink = AsyncLink()
        self.worker = asyncio.get_event_loop().run_in_executor(
            None,
            self.worker_thread,
            self.alink.to_sync,
        )
        self.cache = LRUCache(File, capacity=10, maxage=5.0)

    async def stop(self):
        await self.alink.stop()
        await self.worker

    def worker_thread(self, slink):
        try:
            for req in slink:
                with req as (command, *args):
                    if command == "upload":
                        req.set_result(self.upload(*args))
                    elif command == "download":
                        req.set_result(self.download(*args))
                    else:
                        raise NotImplementedError(f"Unhandled {command=} {args}")
        finally:
            self.cache.close()

    def upload(self, name, pos, data, file_size):
        name = filename.sanitize(name)
        f = self.cache[name]
        f.write(pos, data, file_size=file_size)
        return len(data)

    def download(self, name, start, end):
        name = filename.sanitize(name)
        f = self.cache[name]
        return f[start:end]
