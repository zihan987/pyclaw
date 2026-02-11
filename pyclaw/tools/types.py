from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
