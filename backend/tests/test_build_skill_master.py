import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_skill_master as bsm


def run(args):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = bsm.main(args)
    return code, err.getvalue()


class SkillMasterBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.output = self.dir / "skill_master.json"

    def tearDown(self):
        self.tmp.cleanup()

    def skills_file(self, names):
        path = self.dir / "skills.json"
        path.write_text(json.dumps([{"jpname": n} for n in names], ensure_ascii=False), encoding="utf-8")
        return path

    def test_writes_sorted_unique_names_and_reports_changes(self):
        self.output.write_text(json.dumps(["末脚"]), encoding="utf-8")
        code, _ = run(["--input", str(self.skills_file(["末脚", "直感力", "直感力", "主導権"])), "--output", str(self.output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), sorted({"末脚", "直感力", "主導権"}))

    def test_refuses_to_shrink_the_master_by_default(self):
        existing = [f"スキル{i:03d}" for i in range(100)]
        self.output.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        code, err = run(["--input", str(self.skills_file(existing[:50])), "--output", str(self.output)])
        self.assertEqual(code, 1)
        self.assertIn("書き換えません", err)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), existing)   # 中身は変わらない

    def test_small_shrink_is_allowed_and_override_works(self):
        existing = [f"スキル{i:03d}" for i in range(100)]
        self.output.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(run(["--input", str(self.skills_file(existing[:97])), "--output", str(self.output)])[0], 0)   # 3%減
        self.assertEqual(run(["--input", str(self.skills_file(existing[:40])), "--output", str(self.output)])[0], 1)
        self.assertEqual(run(["--input", str(self.skills_file(existing[:40])), "--output", str(self.output), "--allow-shrink"])[0], 0)

    def test_empty_download_is_an_error(self):
        code, err = run(["--input", str(self.skills_file([])), "--output", str(self.output)])
        self.assertEqual(code, 1)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
