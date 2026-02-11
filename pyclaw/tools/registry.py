from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import ToolsConfig
from ..hooks import HookManager
from .local import LocalTools
from .mcp import MCPManager
from .types import ToolDefinition


class ToolRegistry:
    def __init__(self, tools_cfg: ToolsConfig, workspace: str, hooks: HookManager, mcp: MCPManager | None) -> None:
        self._local = LocalTools(tools_cfg, workspace)
        self._hooks = hooks
        self._mcp = mcp

    def list_definitions(self) -> List[ToolDefinition]:
        defs = list(self._local.definitions())
        if self._mcp:
            for tool in self._mcp.list_tools():
                defs.append(tool.definition)
        return defs

    async def execute(self, name: str, args: Dict[str, Any]) -> str:
        payload = {"tool": name, "args": json.dumps(args, ensure_ascii=False)}
        await self._hooks.run_pre(name, payload)
        try:
            result = await self._execute_inner(name, args)
        except Exception as exc:
            result = f"error: {exc}"
        await self._hooks.run_post(name, {"tool": name, "result": result})
        return result

    async def _execute_inner(self, name: str, args: Dict[str, Any]) -> str:
        for tool in self._local.definitions():
            if tool.name == name:
                return await self._local.execute(name, args)
        if self._mcp:
            return await self._mcp.call_tool(name, args)
        return "unknown tool"

    @staticmethod
    def openai_tools(defs: List[ToolDefinition]) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in defs
        ]

    @staticmethod
    def anthropic_tools(defs: List[ToolDefinition]) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in defs
        ]
