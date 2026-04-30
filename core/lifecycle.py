from __future__ import annotations

import asyncio
import signal


class ShutdownSignal:
    def __init__(self):
        self.event = asyncio.Event()

    def install(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.event.set)
            except NotImplementedError:
                # Windows fallback: Ctrl+C still raises KeyboardInterrupt.
                pass

    async def wait(self) -> None:
        await self.event.wait()
