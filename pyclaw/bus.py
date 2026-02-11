from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List
import asyncio

from .models import ContentBlock

@dataclass
class InboundMessage:
    channel: str
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_blocks: List[ContentBlock] = field(default_factory=list)

    def session_key(self) -> str:
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_blocks: List[ContentBlock] = field(default_factory=list)


class MessageBus:
    def __init__(self, buffer_size: int = 100) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=buffer_size)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=buffer_size)
        self._subs: dict[str, list[Callable[[OutboundMessage], None]]] = {}

    def subscribe_outbound(self, channel: str, fn: Callable[[OutboundMessage], None]) -> None:
        self._subs.setdefault(channel, []).append(fn)

    async def dispatch_outbound(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(self.outbound.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            callbacks = self._subs.get(msg.channel, [])
            if not callbacks:
                continue
            for cb in callbacks:
                try:
                    cb(msg)
                except Exception:
                    continue
