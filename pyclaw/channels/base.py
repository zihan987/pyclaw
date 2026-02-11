from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..bus import MessageBus, OutboundMessage


@dataclass
class BaseChannel:
    name: str
    bus: MessageBus
    allow_from: Dict[str, bool]

    @classmethod
    def from_allowlist(cls, name: str, bus: MessageBus, allow_list: List[str]) -> "BaseChannel":
        allow_map = {item: True for item in allow_list}
        return cls(name=name, bus=bus, allow_from=allow_map)

    def is_allowed(self, sender_id: str) -> bool:
        if not self.allow_from:
            return True
        return self.allow_from.get(sender_id, False)

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def send(self, msg: OutboundMessage) -> None:
        raise NotImplementedError
