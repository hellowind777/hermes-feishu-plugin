"""Timer-based throttled flush controller ported from OpenClaw semantics."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

LONG_GAP_THRESHOLD_SECONDS = 2.0
BATCH_AFTER_GAP_SECONDS = 0.3


class FlushController:
    """Guard card flushes with throttle + reflush scheduling."""

    def __init__(self, do_flush: Callable[[], Awaitable[None]]) -> None:
        self._do_flush = do_flush
        self._flush_in_progress = False
        self._flush_waiters: list[asyncio.Future[None]] = []
        self._needs_reflush = False
        self._pending_timer: asyncio.Task[None] | None = None
        self._last_update_at = 0.0
        self._completed = False
        self._ready = False

    def complete(self) -> None:
        """Prevent future flushes once the current one settles."""
        self._completed = True
        self.cancel_pending_flush()

    def cancel_pending_flush(self) -> None:
        """Cancel any scheduled deferred flush."""
        if self._pending_timer and not self._pending_timer.done():
            self._pending_timer.cancel()
        self._pending_timer = None

    def set_ready(self, ready: bool) -> None:
        """Mark the backing message/card as available for flushing."""
        self._ready = ready
        if ready:
            self._last_update_at = asyncio.get_running_loop().time()

    async def wait_for_flush(self) -> None:
        """Wait until the in-flight flush completes."""
        if not self._flush_in_progress:
            return
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._flush_waiters.append(waiter)
        await waiter

    async def flush(self) -> None:
        """Run the flush callback under a simple mutex."""
        if not self._ready or self._completed:
            return
        if self._flush_in_progress:
            self._needs_reflush = True
            return

        self._flush_in_progress = True
        self._needs_reflush = False
        loop = asyncio.get_running_loop()
        self._last_update_at = loop.time()

        try:
            await self._do_flush()
            self._last_update_at = loop.time()
        finally:
            self._flush_in_progress = False
            waiters = self._flush_waiters
            self._flush_waiters = []
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(None)

            if self._needs_reflush and not self._completed and self._pending_timer is None:
                self._needs_reflush = False
                self._pending_timer = asyncio.create_task(self._run_delayed_flush(0.0))

    async def throttled_update(self, throttle_seconds: float) -> None:
        """Schedule a flush respecting the configured throttle window."""
        if not self._ready or self._completed:
            return

        loop = asyncio.get_running_loop()
        now = loop.time()
        elapsed = now - self._last_update_at

        if elapsed >= throttle_seconds:
            self.cancel_pending_flush()
            if elapsed > LONG_GAP_THRESHOLD_SECONDS:
                self._last_update_at = now
                self._pending_timer = asyncio.create_task(self._run_delayed_flush(BATCH_AFTER_GAP_SECONDS))
            else:
                await self.flush()
            return

        if self._pending_timer is None:
            self._pending_timer = asyncio.create_task(self._run_delayed_flush(throttle_seconds - elapsed))

    async def _run_delayed_flush(self, delay_seconds: float) -> None:
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            await self.flush()
        except asyncio.CancelledError:
            raise
        finally:
            self._pending_timer = None
