from __future__ import annotations

import base64
import hmac
import hashlib
import json
from datetime import datetime
from typing import Any, Dict

from aiohttp import web
import httpx

from .base import BaseChannel
from ..bus import InboundMessage, MessageBus, OutboundMessage
from ..config import SlackConfig
from ..models import ContentBlock


class SlackChannel(BaseChannel):
    def __init__(self, cfg: SlackConfig, bus: MessageBus) -> None:
        if not cfg.botToken or not cfg.signingSecret:
            raise ValueError("slack botToken/signingSecret required")
        super().__init__(name="slack", bus=bus, allow_from={item: True for item in cfg.allowFrom})
        self._cfg = cfg
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._client = httpx.AsyncClient(timeout=15)

    async def start(self) -> None:
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.add_routes([web.post("/slack/events", self._handle_events)])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self._cfg.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        await self._client.aclose()

    async def send(self, msg: OutboundMessage) -> None:
        url = "https://slack.com/api/chat.postMessage"
        payload = {"channel": msg.chat_id, "text": msg.content}
        headers = {"Authorization": f"Bearer {self._cfg.botToken}"}
        resp = await self._client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"slack send error: {resp.status_code} {resp.text}")
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack send error: {data.get('error')}")

    async def _handle_events(self, request: web.Request) -> web.Response:
        body = await request.read()
        if not self._verify_signature(request, body):
            return web.Response(status=401, text="invalid signature")

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return web.Response(status=400, text="invalid json")

        if data.get("type") == "url_verification":
            return web.json_response({"challenge": data.get("challenge", "")})

        if data.get("type") != "event_callback":
            return web.Response(status=200)

        event = data.get("event") or {}
        if event.get("type") != "message" or event.get("subtype"):
            return web.Response(status=200)

        user = event.get("user") or ""
        if user and not self.is_allowed(user):
            return web.Response(status=200)

        content = event.get("text") or ""
        channel_id = event.get("channel") or ""
        files = event.get("files") or []
        content_blocks = await self._download_files(files)

        if not content and not content_blocks:
            return web.Response(status=200)
        if not channel_id:
            return web.Response(status=200)

        inbound = InboundMessage(
            channel="slack",
            sender_id=user,
            chat_id=channel_id,
            content=content,
            timestamp=datetime.utcnow(),
            content_blocks=content_blocks,
            metadata={"event_id": data.get("event_id")},
        )
        await self.bus.inbound.put(inbound)
        return web.Response(status=200)

    async def _download_files(self, files: list[Dict[str, Any]]) -> list[ContentBlock]:
        if not files:
            return []
        blocks: list[ContentBlock] = []
        for info in files:
            url = info.get("url_private_download") or info.get("url_private")
            if not url:
                continue
            resp = await self._client.get(url, headers={"Authorization": f"Bearer {self._cfg.botToken}"})
            if resp.status_code >= 400:
                continue
            data = resp.content
            media_type = info.get("mimetype") or resp.headers.get("Content-Type") or "application/octet-stream"
            b64 = base64.b64encode(data).decode("utf-8")
            block_type = "image" if media_type.startswith("image/") else "document"
            blocks.append(ContentBlock(type=block_type, data=b64, media_type=media_type))
        return blocks

    def _verify_signature(self, request: web.Request, body: bytes) -> bool:
        ts = request.headers.get("X-Slack-Request-Timestamp", "")
        sig = request.headers.get("X-Slack-Signature", "")
        if not ts or not sig:
            return False

        try:
            ts_int = int(ts)
        except ValueError:
            return False

        now = int(datetime.utcnow().timestamp())
        if abs(now - ts_int) > 60 * 5:
            return False

        base = f"v0:{ts}:{body.decode('utf-8')}".encode("utf-8")
        mac = hmac.new(self._cfg.signingSecret.encode("utf-8"), base, hashlib.sha256)
        expected = f"v0={mac.hexdigest()}"
        return hmac.compare_digest(expected, sig)
