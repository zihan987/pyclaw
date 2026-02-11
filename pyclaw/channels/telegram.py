from __future__ import annotations

import asyncio
import base64
import contextlib
from datetime import datetime
from typing import Any, Dict

import httpx

from .base import BaseChannel
from ..bus import InboundMessage, MessageBus, OutboundMessage
from ..config import TelegramConfig
from ..models import ContentBlock


class TelegramChannel(BaseChannel):
    def __init__(self, cfg: TelegramConfig, bus: MessageBus) -> None:
        if not cfg.token:
            raise ValueError("telegram token is required")
        super().__init__(name="telegram", bus=bus, allow_from={item: True for item in cfg.allowFrom})
        self._token = cfg.token
        self._client = httpx.AsyncClient(timeout=30)
        self._task: asyncio.Task | None = None
        self._running = False
        self._offset = 0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._client.aclose()

    async def send(self, msg: OutboundMessage) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": msg.chat_id,
            "text": msg.content,
        }
        resp = await self._client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"telegram send error: {resp.status_code} {resp.text}")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await self._get_updates()
            except Exception:
                await asyncio.sleep(2)
                continue

            for update in updates:
                self._offset = max(self._offset, update.get("update_id", 0) + 1)
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                await self._handle_message(msg)

    async def _get_updates(self) -> list[Dict[str, Any]]:
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        params = {"timeout": 30, "offset": self._offset}
        resp = await self._client.get(url, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"telegram getUpdates error: {resp.status_code} {resp.text}")
        data = resp.json()
        return data.get("result", [])

    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        sender = msg.get("from") or {}
        sender_id = str(sender.get("id", ""))
        if not sender_id or not self.is_allowed(sender_id):
            return

        content = msg.get("text") or msg.get("caption") or ""
        content_blocks: list[ContentBlock] = []

        photos = msg.get("photo") or []
        if photos:
            photo = photos[-1]
            file_id = photo.get("file_id")
            if file_id:
                block = await self._download_content_block(file_id, "image/jpeg")
                if block:
                    content_blocks.append(block)

        document = msg.get("document") or {}
        if document:
            file_id = document.get("file_id")
            if file_id:
                media_type = document.get("mime_type") or "application/octet-stream"
                block = await self._download_content_block(file_id, media_type)
                if block:
                    content_blocks.append(block)

        if not content and not content_blocks:
            return

        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return

        inbound = InboundMessage(
            channel="telegram",
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            timestamp=datetime.utcnow(),
            content_blocks=content_blocks,
            metadata={
                "username": sender.get("username"),
                "first_name": sender.get("first_name"),
                "message_id": msg.get("message_id"),
            },
        )
        await self.bus.inbound.put(inbound)

    async def _download_content_block(self, file_id: str, default_type: str) -> ContentBlock | None:
        file_path = await self._get_file_path(file_id)
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        resp = await self._client.get(url)
        if resp.status_code >= 400:
            return None
        data = resp.content
        media_type = resp.headers.get("Content-Type") or default_type
        if media_type == "application/octet-stream" and default_type:
            media_type = default_type
        b64 = base64.b64encode(data).decode("utf-8")
        block_type = "image" if media_type.startswith("image/") else "document"
        return ContentBlock(type=block_type, data=b64, media_type=media_type)

    async def _get_file_path(self, file_id: str) -> str:
        url = f"https://api.telegram.org/bot{self._token}/getFile"
        resp = await self._client.get(url, params={"file_id": file_id})
        if resp.status_code >= 400:
            return ""
        data = resp.json()
        result = data.get("result") or {}
        return result.get("file_path") or ""
