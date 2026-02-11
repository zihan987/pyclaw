from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List

from ..config import MCPServerConfig
from .types import ToolDefinition


@dataclass
class MCPTool:
    server_name: str
    definition: ToolDefinition


class MCPServer:
    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._pending: Dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._read_task: asyncio.Task | None = None

    async def start(self) -> None:
        env = None
        if self.cfg.env:
            env = {**self.cfg.env}
        self._proc = await asyncio.create_subprocess_exec(
            self.cfg.command,
            *self.cfg.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cfg.cwd or None,
            env=env,
        )
        self._read_task = asyncio.create_task(self._read_loop())
        await self._initialize()

    async def stop(self) -> None:
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
        if self._proc:
            self._proc.kill()
            await self._proc.wait()

    async def list_tools(self) -> List[ToolDefinition]:
        result = await self._request("tools/list", {})
        tools = []
        for tool in result.get("tools", []):
            tools.append(
                ToolDefinition(
                    name=tool.get("name", ""),
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema") or {"type": "object"},
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts).strip()
        if isinstance(content, str):
            return content
        return json.dumps(result)

    async def _initialize(self) -> None:
        await self._request(
            "initialize",
            {
                "clientInfo": {"name": "ember", "version": "0.1.0"},
                "capabilities": {},
            },
        )
        await self._notify("initialized", {})

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[req_id] = fut

            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            await self._send(payload)

        return await fut

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._send(payload)

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("MCP server not running")
        data = json.dumps(payload, ensure_ascii=False)
        self._proc.stdin.write((data + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if "id" in msg and msg.get("id") in self._pending:
                fut = self._pending.pop(msg["id"])
                if "error" in msg:
                    fut.set_result({"error": msg["error"]})
                else:
                    fut.set_result(msg.get("result") or {})


class MCPManager:
    def __init__(self, servers: List[MCPServerConfig]) -> None:
        self._servers = [MCPServer(cfg) for cfg in servers]
        self._tool_map: Dict[str, MCPServer] = {}
        self._tools: List[MCPTool] = []

    async def start(self) -> None:
        for server in self._servers:
            await server.start()
            tools = await server.list_tools()
            for tool in tools:
                if tool.name:
                    self._tool_map[tool.name] = server
                    self._tools.append(MCPTool(server_name=server.cfg.name, definition=tool))

    async def stop(self) -> None:
        for server in self._servers:
            await server.stop()

    def list_tools(self) -> List[MCPTool]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        server = self._tool_map.get(name)
        if not server:
            return "tool not found"
        return await server.call_tool(name, arguments)


import contextlib
