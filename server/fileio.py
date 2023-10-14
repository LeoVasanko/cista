import asyncio
import os

from asynclink import AsyncLink
from lrucache import LRUCache

class File:
    def __init__(self, filename):
        self.filename = filename
        self.fd = None
        self.writable = False

    def open_ro(self):
        self.close()
        self.fd = os.open(self.filename, os.O_RDONLY)

    def open_rw(self):
        self.close()
        self.fd = os.open(self.filename, os.O_RDWR | os.O_CREAT)
        self.writable = True

    def write(self, pos, buffer, *, file_size=None):
        if not self.writable:
            self.open_rw()
        if file_size is not None:
            os.ftruncate(self.fd, file_size)
        os.lseek(self.fd, pos, os.SEEK_SET)
        os.write(self.fd, buffer)

    def __getitem__(self, slice):
        if self.fd is None:
            self.open_ro()
        os.lseek(self.fd, slice.start, os.SEEK_SET)
        l = slice.stop - slice.start
        data = os.read(self.fd, l)
        if len(data) < l: raise EOFError("Error reading requested range")
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
        self.worker = asyncio.get_event_loop().run_in_executor(None, self.worker_thread, alink.to_sync)

    async def stop(self):
        await self.alink.stop()
        await self.worker

    def worker_thread(self, slink):
        cache = LRUCache(File, capacity=10, maxage=5.0)
        for req in slink:
            with req as (command, msg, data):
                if command == "upload":
                    req.set_result(self.upload(msg, data))
                else:
                    raise NotImplementedError(f"Unhandled {command=} {msg}")


    def upload(self, msg, data):
        name = str(msg['name'])
        size = int(msg['size'])
        start = int(msg['start'])
        end = int(msg['end'])

        if not 0 <= start < end <= size:
            raise OverflowError("Invalid range")
        if end - start > 1<<20:
            raise OverflowError("Too much data, max 1 MiB.")
        if end - start != len(data):
            raise ValueError("Data length does not match range")
        f = self.cache[name]
        f.write(start, data, file_size=size)

        return {"written": len(data), **msg}
