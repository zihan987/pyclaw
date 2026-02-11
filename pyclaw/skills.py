from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List
import yaml


@dataclass
class Skill:
    name: str
    description: str
    keywords: List[str]
    body: str
    source_path: str


def load_skills(skill_dir: str) -> List[Skill]:
    path = Path(skill_dir)
    if not path.exists() or not path.is_dir():
        return []

    skills: List[Skill] = []
    for entry in sorted(path.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.exists():
            continue
        skill = _parse_skill_file(skill_file)
        if skill:
            skills.append(skill)
    return skills


def _parse_skill_file(path: Path) -> Skill | None:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    if not meta:
        return None

    name = (meta.get("name") or "").strip()
    if not name:
        return None

    description = (meta.get("description") or "").strip()
    keywords = [str(k).strip().lower() for k in (meta.get("keywords") or []) if str(k).strip()]

    return Skill(
        name=name,
        description=description,
        keywords=sorted(set(keywords)),
        body=body.strip(),
        source_path=str(path),
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("\n")
    if len(parts) < 3:
        return {}, text

    end_idx = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text

    front = "\n".join(parts[1:end_idx])
    body = "\n".join(parts[end_idx + 1 :])
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        return {}, body
    return meta, body


def match_skills(skills: List[Skill], message: str) -> List[Skill]:
    msg = message.lower()
    matched = []
    for skill in skills:
        if not skill.keywords:
            continue
        if any(k in msg for k in skill.keywords):
            matched.append(skill)
    return matched
