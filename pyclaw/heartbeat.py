from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable


class HeartbeatService:
    def __init__(self, workspace: str, on_heartbeat: Callable[[str], Awaitable[str]], interval_sec: int = 1800) -> None:
        self.workspace = Path(workspace)
        self.on_heartbeat = on_heartbeat
        self.interval_sec = interval_sec
        self._task: asyncio.Task | None = None

    async def start(self, stop_event: asyncio.Event) -> None:
        self._task = asyncio.create_task(self._loop(stop_event))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(self.interval_sec)
            await self._tick()

    async def _tick(self) -> None:
        path = self.workspace / "PULSE.md"
        if not path.exists():
            legacy = self.workspace / "HEARTBEAT.md"
            if legacy.exists():
                path = legacy
            else:
                return
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return
        if not self.on_heartbeat:
            return
        result = await self.on_heartbeat(content)
        if "HEARTBEAT_OK" in result:
            return


import contextlib
