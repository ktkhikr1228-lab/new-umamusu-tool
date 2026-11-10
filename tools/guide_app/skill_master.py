"""スキルマスタ(frontend/src/data/skill_master.json)との照合。"""
from __future__ import annotations

import difflib
import json
from pathlib import Path

_CIRCLES = str.maketrans({"◯": "○", "〇": "○"})


def normalize(name: str) -> str:
    """公開スクリプトと同じ規則。○・◯・〇は同一視し、◎は別扱い。"""
    return name.strip().translate(_CIRCLES)


class SkillMaster:
    def __init__(self, names: list[str]):
        self.names = list(names)
        self._by_key = {normalize(n): n for n in self.names}

    @classmethod
    def load(cls, path: Path) -> "SkillMaster":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            raise ValueError(f"スキルマスタの形式が想定と違います: {path}")
        return cls(data)

    def canonical(self, name: str) -> str | None:
        """マスタにあれば正式表記を返す。なければNone。"""
        return self._by_key.get(normalize(name))

    def suggest(self, name: str, limit: int = 5) -> list[str]:
        keys = difflib.get_close_matches(normalize(name), list(self._by_key), n=limit, cutoff=0.5)
        return [self._by_key[k] for k in keys]
