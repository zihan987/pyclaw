from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class TokenUsage:
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: float
    metadata: Dict[str, str] | None = None


class TokenTracker:
    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, usage: TokenUsage) -> None:
        data = {
            "provider": usage.provider,
            "model": usage.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "timestamp": usage.timestamp,
            "metadata": usage.metadata or {},
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def build_usage(provider: str, model: str, usage_data: Dict[str, int]) -> Optional[TokenUsage]:
    if not usage_data:
        return None
    prompt = usage_data.get("prompt_tokens", usage_data.get("input_tokens", 0))
    completion = usage_data.get("completion_tokens", usage_data.get("output_tokens", 0))
    total = usage_data.get("total_tokens", prompt + completion)
    if total <= 0:
        return None
    return TokenUsage(
        provider=provider,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        timestamp=time.time(),
    )
