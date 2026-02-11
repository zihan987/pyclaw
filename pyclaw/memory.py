from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime


@dataclass
class MemoryStore:
    workspace: str

    def _legacy_memory_dir(self) -> Path:
        return Path(self.workspace) / "memory"

    def _memory_dir(self) -> Path:
        return Path(self.workspace) / "journal"

    def _ensure_dir(self) -> None:
        self._memory_dir().mkdir(parents=True, exist_ok=True)

    def read_long_term(self) -> str:
        path = self._memory_dir() / "LONGTERM.md"
        if not path.exists():
            legacy = self._legacy_memory_dir() / "MEMORY.md"
            if legacy.exists():
                return legacy.read_text(encoding="utf-8")
            return ""
        return path.read_text(encoding="utf-8")

    def write_long_term(self, content: str) -> None:
        self._ensure_dir()
        path = self._memory_dir() / "LONGTERM.md"
        path.write_text(content, encoding="utf-8")

    def _today_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self._memory_dir() / f"{date_str}.md"

    def read_today(self) -> str:
        path = self._today_path()
        if not path.exists():
            legacy = self._legacy_memory_dir() / path.name
            if legacy.exists():
                return legacy.read_text(encoding="utf-8")
            return ""
        return path.read_text(encoding="utf-8")

    def append_today(self, content: str) -> None:
        self._ensure_dir()
        path = self._today_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")

    def get_recent_memories(self, days: int = 7) -> str:
        mem_dir = self._memory_dir()
        if not mem_dir.exists():
            mem_dir = self._legacy_memory_dir()
            if not mem_dir.exists():
                return ""

        files = sorted(
            [p for p in mem_dir.glob("*.md") if p.name not in {"MEMORY.md", "LONGTERM.md"}],
            reverse=True,
        )
        if days > 0:
            files = files[:days]

        parts = []
        for path in files:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            date = path.stem
            parts.append(f"## {date}\n{content}\n")
        return "\n".join(parts).strip()

    def get_memory_context(self) -> str:
        parts = []
        long_term = self.read_long_term().strip()
        if long_term:
            parts.append("# Long-term Memory\n" + long_term)

        recent = self.get_recent_memories(7).strip()
        if recent:
            parts.append("# Recent Journal\n" + recent)

        return "\n\n".join(parts).strip()
