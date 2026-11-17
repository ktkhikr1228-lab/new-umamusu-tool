import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_skill_master_change as chk

OLD = ["末脚", "直線巧者", "左回り○"]


class CheckSkillMasterChangeTests(unittest.TestCase):
    def test_additions_only_is_safe(self):
        self.assertEqual(chk.problems(OLD, OLD + ["遊び心", "直感力"]), [])
        self.assertEqual(chk.problems(OLD, OLD), [])

    def test_removal_or_rename_needs_a_human(self):
        found = chk.problems(OLD, ["末脚", "直線巧者", "左回り◎"])   # 左回り○ が消え、◎ が増えた = 名前の変更
        self.assertTrue(any("削除または名前の変更が 1 件" in f for f in found))

    def test_too_many_additions_needs_a_human(self):
        many = [f"新スキル{i}" for i in range(401)]
        self.assertTrue(any("上限" in f for f in chk.problems(OLD, OLD + many)))
        self.assertEqual(chk.problems(OLD, OLD + many[:400]), [])

    def test_bad_names_need_a_human(self):
        for bad, word in (("", "空の名前"), (" 末脚2", "前後に空白"), ("末脚\n2", "制御文字"), ("あ" * 61, "文字を超える"), ("末脚", "重複")):
            with self.subTest(bad=bad):
                self.assertTrue(any(word in f for f in chk.problems(OLD, OLD + [bad])), bad)
        self.assertTrue(any("文字列でない" in f for f in chk.problems(OLD, OLD + [123])))

    def run_cli(self, before, after, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            b, a = Path(tmp) / "b.json", Path(tmp) / "a.json"
            b.write_text(before if isinstance(before, str) else json.dumps(before, ensure_ascii=False), encoding="utf-8")
            a.write_text(after if isinstance(after, str) else json.dumps(after, ensure_ascii=False), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = chk.main(["--before", str(b), "--after", str(a), *extra])
            return code, out.getvalue()

    def test_exit_codes(self):
        self.assertEqual(self.run_cli(OLD, OLD + ["遊び心"])[0], 0)
        self.assertIn("追加 1 件", self.run_cli(OLD, OLD + ["遊び心"])[1])
        self.assertEqual(self.run_cli(OLD, OLD)[1].strip(), "変更なし")
        self.assertEqual(self.run_cli(OLD, OLD[:2])[0], 2)
        self.assertEqual(self.run_cli(OLD, "not json")[0], 1)
        self.assertEqual(self.run_cli(OLD, '{"a": 1}')[0], 1)
        self.assertEqual(self.run_cli(OLD, OLD + ["a", "b", "c"], "--max-added", "2")[0], 2)


if __name__ == "__main__":
    unittest.main()
