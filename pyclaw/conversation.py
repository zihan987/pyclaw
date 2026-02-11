from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .config import AutoCompactConfig


@dataclass
class Conversation:
    summary: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def add_user(self, content: Any) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_assistant_tool_calls(self, content: str, tool_calls: List[Dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

    def add_tool(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content})

    def add_anthropic_tool_use(self, content_blocks: List[Dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "content": content_blocks})

    def add_anthropic_tool_result(self, tool_use_id: str, content: str) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            }
        )

    def to_openai_messages(self, system_prompt: str) -> List[Dict[str, Any]]:
        messages = [{"role": "system", "content": system_prompt}]
        if self.summary:
            messages.append({"role": "system", "content": f"# Summary\n{self.summary}"})
        messages.extend(self.messages)
        return messages

    def to_anthropic_messages(self) -> List[Dict[str, Any]]:
        return list(self.messages)


class ConversationStore:
    def __init__(self, compact: AutoCompactConfig, max_tokens: int) -> None:
        self._compact = compact
        self._max_tokens = max_tokens
        self._store: Dict[str, Conversation] = {}

    def get(self, session_id: str) -> Conversation:
        if session_id not in self._store:
            self._store[session_id] = Conversation()
        return self._store[session_id]

    def should_compact(self, conv: Conversation) -> bool:
        if not self._compact.enabled:
            return False
        estimate_chars = sum(len(str(m.get("content", ""))) for m in conv.messages)
        estimate_chars += len(conv.summary)
        max_chars = max(2000, self._max_tokens * 4 * 2)
        return estimate_chars / max_chars >= self._compact.threshold

    def compact_messages(self, conv: Conversation) -> List[Dict[str, Any]]:
        keep = max(self._compact.preserveCount, 1)
        if len(conv.messages) <= keep:
            return []
        old = conv.messages[:-keep]
        conv.messages = conv.messages[-keep:]
        return old
