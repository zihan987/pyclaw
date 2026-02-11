from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta
from typing import Any, Dict

from aiohttp import web
import httpx

from .base import BaseChannel
from ..bus import InboundMessage, MessageBus, OutboundMessage
from ..config import FeishuConfig
from ..models import ContentBlock


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: str = ""
        self._token_exp: datetime | None = None
        self._client = httpx.AsyncClient(timeout=15)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_token(self) -> str:
        if self._token and self._token_exp and datetime.utcnow() < self._token_exp:
            return self._token

        async with self._lock:
            if self._token and self._token_exp and datetime.utcnow() < self._token_exp:
                return self._token

            payload = {"app_id": self._app_id, "app_secret": self._app_secret}
            resp = await self._client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json=payload,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"feishu token error: {resp.status_code} {resp.text}")
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"feishu token error: {data.get('msg')}")
            self._token = data.get("tenant_access_token", "")
            expires = int(data.get("expire", 0))
            self._token_exp = datetime.utcnow() + timedelta(seconds=max(expires - 60, 60))
            return self._token

    async def send_message(self, chat_id: str, content: str) -> None:
        token = await self.get_token()
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        }
        resp = await self._client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"feishu send error: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu send error: {data.get('msg')}")


class FeishuChannel(BaseChannel):
    def __init__(self, cfg: FeishuConfig, bus: MessageBus) -> None:
        if not cfg.appId or not cfg.appSecret:
            raise ValueError("feishu appId/appSecret required")
        super().__init__(name="feishu", bus=bus, allow_from={item: True for item in cfg.allowFrom})
        self._cfg = cfg
        self._client = FeishuClient(cfg.appId, cfg.appSecret)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.add_routes([web.post("/feishu/webhook", self._handle_webhook)])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self._cfg.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        await self._client.close()

    async def send(self, msg: OutboundMessage) -> None:
        await self._client.send_message(msg.chat_id, msg.content)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            body = await request.read()
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return web.Response(status=400, text="invalid json")

        challenge = data.get("challenge")
        if challenge:
            return web.json_response({"challenge": challenge})

        header = data.get("header") or {}
        token = header.get("token", "")
        if self._cfg.verificationToken and token != self._cfg.verificationToken:
            return web.Response(status=401, text="invalid token")

        if header.get("event_type") != "im.message.receive_v1":
            return web.Response(status=200)

        event = data.get("event") or {}
        sender = ((event.get("sender") or {}).get("sender_id") or {}).get("open_id", "")
        if not sender or not self.is_allowed(sender):
            return web.Response(status=200)

        message = event.get("message") or {}
        chat_id = message.get("chat_id", "")
        message_type = (message.get("message_type") or "").lower()
        content_raw = message.get("content", "")
        content = ""
        content_blocks: list[ContentBlock] = []
        if message_type == "text":
            try:
                content = json.loads(content_raw).get("text", "")
            except Exception:
                content = ""
        elif message_type == "image":
            try:
                image_key = json.loads(content_raw).get("image_key", "")
            except Exception:
                image_key = ""
            if image_key:
                block = await self._download_image_block(image_key)
                if block:
                    content_blocks.append(block)
                content = "[image]"

        if not content and not content_blocks:
            return web.Response(status=200)

        inbound = InboundMessage(
            channel="feishu",
            sender_id=sender,
            chat_id=chat_id,
            content=content,
            timestamp=datetime.utcnow(),
            content_blocks=content_blocks,
            metadata={"message_type": message_type},
        )
        await self.bus.inbound.put(inbound)
        return web.Response(status=200)

    async def _download_image_block(self, image_key: str) -> ContentBlock | None:
        token = await self._client.get_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/images/{image_key}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = await self._client._client.get(url, headers=headers)
        if resp.status_code >= 400:
            return None
        data = resp.content
        media_type = resp.headers.get("Content-Type") or "image/jpeg"
        b64 = base64.b64encode(data).decode("utf-8")
        return ContentBlock(type="image", data=b64, media_type=media_type)
