"""Pause transfers on their asyncio loop, closing requests and retaining partials."""
import asyncio


class TransferControl:
    def __init__(self, on_state=None):
        self._pause = asyncio.Event()
        self._running = asyncio.Event()
        self._running.set()
        self.on_state = on_state or (lambda state: None)

    def pause(self):
        self._running.clear()
        self._pause.set()
        self.on_state('pausing')

    def resume(self):
        self._pause.clear()
        self._running.set()

    async def run(self, factory):
        while True:
            if self._pause.is_set():
                self.on_state('paused')
            await self._running.wait()
            self.on_state('receiving')
            work = asyncio.create_task(factory())
            requested = asyncio.create_task(self._pause.wait())
            try:
                await asyncio.wait((work, requested), return_when=asyncio.FIRST_COMPLETED)
                if not self._pause.is_set():
                    return await work
                if work.done() and not work.cancelled():
                    # Work finished before the pause took effect: hand back the result
                    # (or its exception) now instead of announcing 'paused' and waiting
                    # for a Resume that would stall the finished sync.
                    return await work
                # Await request/worker cleanup before confirming that traffic has stopped.
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                self.on_state('paused')
                await self._running.wait()
                self.on_state('receiving')
                # The existing signed-index and verified-piece resume path is reused.
            finally:
                for task in (work, requested):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(work, requested, return_exceptions=True)
