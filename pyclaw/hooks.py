from __future__ import annotations

import asyncio
import os
import re
from typing import Dict, List

from .config import HookEntry, HooksConfig


class HookManager:
    def __init__(self, hooks: HooksConfig) -> None:
        self._hooks = hooks

    async def run_pre(self, tool_name: str, payload: Dict[str, str]) -> None:
        await self._run(self._hooks.preToolUse, tool_name, payload)

    async def run_post(self, tool_name: str, payload: Dict[str, str]) -> None:
        await self._run(self._hooks.postToolUse, tool_name, payload)

    async def run_stop(self, payload: Dict[str, str]) -> None:
        await self._run(self._hooks.stop, "", payload)

    async def _run(self, hooks: List[HookEntry], tool_name: str, payload: Dict[str, str]) -> None:
        for hook in hooks:
            if hook.pattern and tool_name:
                try:
                    if not re.search(hook.pattern, tool_name):
                        continue
                except re.error:
                    continue
            await self._run_command(hook.command, hook.timeout, payload)

    async def _run_command(self, command: str, timeout: int, payload: Dict[str, str]) -> None:
        if not command:
            return
        env = os.environ.copy()
        for key, value in payload.items():
            env[f"PYCLAW_{key.upper()}"] = value
        proc = await asyncio.create_subprocess_shell(
            command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
