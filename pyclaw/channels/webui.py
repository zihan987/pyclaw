from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict

from aiohttp import web, WSMsgType
from datetime import datetime

from .base import BaseChannel
from ..bus import InboundMessage, MessageBus, OutboundMessage
from ..config import GatewayConfig, WebUIConfig


class WebUIChannel(BaseChannel):
    def __init__(self, cfg: WebUIConfig, gw_cfg: GatewayConfig, bus: MessageBus) -> None:
        super().__init__(name="webui", bus=bus, allow_from={item: True for item in cfg.allowFrom})
        self._cfg = cfg
        self._gw_cfg = gw_cfg
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._clients: Dict[str, web.WebSocketResponse] = {}
        self._next_id = 0

    async def start(self) -> None:
        app = web.Application()
        app.add_routes([web.get("/ws", self._handle_ws), web.get("/", self._handle_index)])

        static_dir = Path(__file__).parent / "static"
        app.router.add_static("/static/", static_dir)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        port = self._cfg.port or self._gw_cfg.port
        self._site = web.TCPSite(self._runner, self._gw_cfg.host, port)
        await self._site.start()

    async def stop(self) -> None:
        for ws in list(self._clients.values()):
            await ws.close()
        self._clients.clear()
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    async def send(self, msg: OutboundMessage) -> None:
        payload = json.dumps({"type": "message", "content": msg.content})
        if msg.chat_id and msg.chat_id in self._clients:
            await self._clients[msg.chat_id].send_str(payload)
            return
        for ws in list(self._clients.values()):
            await ws.send_str(payload)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        token = request.query.get("token", "")
        if self.allow_from and not token:
            await ws.close()
            return ws
        if self.allow_from and token and not self.is_allowed(token):
            await ws.close()
            return ws

        self._next_id += 1
        client_id = token or f"webui-{self._next_id}"
        self._clients[client_id] = ws

        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if data.get("type") != "message":
                continue
            content = (data.get("content") or "").strip()
            if not content:
                continue
            if not self.is_allowed(client_id):
                continue
            await self.bus.inbound.put(
                InboundMessage(
                    channel="webui",
                    sender_id=client_id,
                    chat_id=client_id,
                    content=content,
                    timestamp=datetime.utcnow(),
                )
            )

        self._clients.pop(client_id, None)
        return ws

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = Path(__file__).parent / "static" / "index.html"
        return web.FileResponse(index_path)
