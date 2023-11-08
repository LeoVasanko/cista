import asyncio
from contextlib import suppress


class AsyncLink:
    """Facilitate two-way connection between asyncio and a worker thread."""

    def __init__(self):
        """Initialize; must be called from async context."""
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=1)

    async def __call__(self, command) -> asyncio.Future:
        """Run command in worker thread; awaitable.

        Args:
            command: Command to run in worker thread.
        """
        fut = self.loop.create_future()
        await self.queue.put((command, fut))
        return await fut

    @property
    def to_sync(self):
        """Yield SyncRequests from async caller when called from worker thread."""
        while (req := self._await(self._get())) is not None:
            yield SyncRequest(self, req)

    async def _get(self):
        """Retrieve an item from the queue; handle cancellation."""
        with suppress(asyncio.CancelledError):
            ret = await self.queue.get()
            self.queue.task_done()
            return ret

    def _await(self, coro):
        """Run coroutine in main thread and return result; called from worker."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    async def stop(self):
        """Stop worker and clean up."""
        while not self.queue.empty():
            command, future = self.queue.get_nowait()
            if not future.done():
                future.set_exception(Exception("AsyncLink stopped"))
            self.queue.task_done()
        await self.queue.put(None)


async def set_result(fut: asyncio.Future, value=None, exception=None):
    """Set result or exception on an asyncio.Future object.

    Args:
        fut (asyncio.Future): Future to set result or exception on.
        value: Result to set on the future.
        exception: Exception to set on the future.
    """
    with suppress(asyncio.InvalidStateError):
        if exception is None:
            fut.set_result(value)
        else:
            fut.set_exception(exception)


class SyncRequest:
    """Handle values from sync thread in main asyncio event loop."""

    def __init__(self, alink: AsyncLink, req):
        """Initialize SyncRequest with AsyncLink and request."""
        self.alink = alink
        self.command, self.future = req
        self.done = False

    def __enter__(self):
        """Provide command to with-block and handle exceptions."""
        return self.command

    def __exit__(self, exc_type, exc, traceback):
        """Set result or exception on exit; suppress exceptions in with-block."""
        if exc:
            self.set_exception(exc)
            return True
        if not self.done:
            self.set_result(None)
        return None

    def set_result(self, value):
        """Set result value; mark as done."""
        self.done = True
        self.alink._await(set_result(self.future, value))

    def set_exception(self, exc):
        """Set exception; mark as done."""
        self.done = True
        self.alink._await(set_result(self.future, exception=exc))
