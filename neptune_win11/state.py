from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class InstallState:
    schema: int = 1
    phase: str = "not-started"
    detail: str = ""

    @classmethod
    def load(cls, path: Path) -> "InstallState":
        if not path.exists():
            return cls()
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != 1:
            raise ValueError(f"unsupported state schema: {value.get('schema')!r}")
        return cls(**value)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".new")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
