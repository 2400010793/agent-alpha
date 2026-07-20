from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    text: str


def load_skill(path: str | Path) -> Skill:
    skill_path = Path(path).expanduser().resolve()
    text = skill_path.read_text(encoding="utf-8")
    name = skill_path.parent.name
    for line in text.splitlines():
        if line.lower().startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("'").strip('"') or name
            break
    return Skill(name=name, path=skill_path, text=text)


def load_skills(root: str | Path = "skills") -> dict[str, Skill]:
    root_path = Path(root).expanduser().resolve()
    skills: dict[str, Skill] = {}
    for path in sorted(root_path.glob("*/SKILL.md")):
        skill = load_skill(path)
        skills[skill.name] = skill
    return skills