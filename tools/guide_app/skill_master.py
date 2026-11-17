"""スキルマスタ(frontend/src/data/skill_master.json)との照合。"""
from __future__ import annotations

import difflib
import json
from pathlib import Path

# 同じ文字の書き方の違いだけをそろえる。○・◯・〇、半角と全角の「!」「?」「~」は同じ字として扱う。
# ◎ は別のスキルなので、○ とは区別したまま。(マスタ1953件で、この揃え方で別々の名前が重なる組がないことを確認済み)
_FOLD = str.maketrans({"◯": "○", "〇": "○", "!": "！", "?": "？", "~": "〜", "～": "〜"})


def normalize(name: str) -> str:
    """照合用の名前。表記のゆれ(丸の字形、半角・全角の記号)だけをそろえる。"""
    return name.strip().translate(_FOLD)


class SkillMaster:
    def __init__(self, names: list[str]):
        self.names = list(names)
        self._by_key = {normalize(n): n for n in self.names}

    def update(self, names: list[str]) -> None:
        """中身を入れ替える。このオブジェクトを持っている全員に反映される。"""
        if not isinstance(names, list) or not names or not all(isinstance(x, str) and x for x in names):
            raise ValueError("スキルマスタの形式が想定と違います")
        if len(self.names) >= 100 and len(names) < len(self.names) * 0.9:
            # 取得が途中で切れた・壊れた内容で入れ替えると、実在のスキルを「マスタにない」と扱ってしまう
            raise ValueError(f"スキルマスタが急に減っています({len(self.names)}件 → {len(names)}件)。入れ替えません")
        by_key = {normalize(n): n for n in names}
        self.names, self._by_key = list(names), by_key

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
