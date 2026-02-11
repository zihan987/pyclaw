from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from ..config import ToolsConfig
from .types import ToolDefinition


class LocalTools:
    def __init__(self, cfg: ToolsConfig, workspace: str) -> None:
        self.cfg = cfg
        self.workspace = Path(workspace)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="read_file",
                description="Read a file from the workspace",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            ToolDefinition(
                name="write_file",
                description="Write content to a file in the workspace",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            ),
            ToolDefinition(
                name="list_dir",
                description="List files in a directory within the workspace",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            ToolDefinition(
                name="exec",
                description="Execute a shell command in the workspace",
                input_schema={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            ),
        ]

    async def execute(self, name: str, args: Dict[str, Any]) -> str:
        if name == "read_file":
            path = self._resolve_path(args.get("path", ""))
            if not path.exists() or not path.is_file():
                return "file not found"
            return path.read_text(encoding="utf-8")

        if name == "write_file":
            path = self._resolve_path(args.get("path", ""))
            content = args.get("content", "")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return "ok"

        if name == "list_dir":
            path = self._resolve_path(args.get("path", ""))
            if not path.exists() or not path.is_dir():
                return "directory not found"
            return json.dumps(sorted([p.name for p in path.iterdir()]))

        if name == "exec":
            command = args.get("command", "")
            if not command:
                return "command required"
            return await self._exec(command)

        return "unknown tool"

    async def _exec(self, command: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.cfg.execTimeout)
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            return "command timed out"

        output = stdout.decode("utf-8", errors="ignore")
        err = stderr.decode("utf-8", errors="ignore")
        if err:
            return output + "\n" + err
        return output

    def _resolve_path(self, path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = self.workspace / path
        path = path.resolve()
        if self.cfg.restrictToWorkspace:
            try:
                path.relative_to(self.workspace.resolve())
            except ValueError:
                raise ValueError("path outside workspace")
        return path
