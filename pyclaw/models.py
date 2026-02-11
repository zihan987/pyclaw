from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ContentBlock:
    type: str  # text, image, document
    data: Optional[str] = None  # base64
    media_type: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
