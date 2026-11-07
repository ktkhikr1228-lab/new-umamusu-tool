import contextlib
import copy
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import publish_reviewed_race_data as pub
import dispatch_reviewed_race_data as sender

MASTER = ["末脚", "直線巧者", "左回り○", "左回り◎"]

def request(skill="末脚", tier="recommended", event="2026-09_CM", race="東京 芝 1800m"):
    return {"event": event, "rows": [{"race": race, "strategy": "先行", "tier": tier, "skill": skill, "status": "ready"}]}


class PublicationTests(unittest.TestCase):
    def test_add_new_race_and_preserve_everything_else(self):
        base = {"既存条件": {"自由項目": ["変更しない"]}}
        original = copy.deepcopy(base)
        data, stats = pub.merge(base, pub.validate(request(), MASTER))
        self.assertEqual(base, original)
        self.assertEqual(data["既存条件"], base["既存条件"])
        self.assertEqual(data["東京 芝 1800m"]["先行"]["recommended"], ["末脚"])
        self.assertTrue(stats["changed"])
        self.assertEqual(stats["added"], 1)

    def test_same_request_preserves_order_and_is_noop(self):
        base = {"東京 芝 1800m": {"先行": {"super_recommended": [], "recommended": ["末脚", "直線巧者"]}}}
        data, stats = pub.merge(base, pub.validate(request(), MASTER))
        self.assertEqual(data, base)
        self.assertFalse(stats["changed"])

    def test_explicit_tier_move_handles_circle_variants(self):
        base = {"東京 芝 1800m": {"先行": {"super_recommended": ["左回り◯", "直線巧者"], "recommended": []}}}
        data, stats = pub.merge(base, pub.validate(request("左回り〇"), MASTER))
        detail = data["東京 芝 1800m"]["先行"]
        self.assertEqual(detail["super_recommended"], ["直線巧者"])
        self.assertEqual(detail["recommended"], ["左回り○"])
        self.assertEqual(stats["moved"], 1)

    def test_pending_rows_accumulate_and_latest_review_can_move_tier(self):
        pending = request()
        incoming = request("直線巧者")
        combined = pub.combine(pending, incoming, MASTER)
        self.assertEqual({r["skill"] for r in combined["rows"]}, {"末脚", "直線巧者"})
        combined = pub.combine(combined, request(tier="super_recommended"), MASTER)
        self.assertEqual(next(r["tier"] for r in combined["rows"] if r["skill"] == "末脚"), "super_recommended")
        with self.assertRaises(ValueError):
            pub.combine(pending, request(event="other-event"), MASTER)

    def test_draft_rejected_unknown_and_conflicting_data_fail(self):
        bad = []
        p = request(); p["rows"][0]["status"] = "draft"; bad.append(p)
        bad.append(request("存在しないスキル"))
        p = request(); p["rows"][0]["strategy"] = "不正"; bad.append(p)
        bad.append(request(race="東京 芝 1800m\n悪い条件"))
        bad.append(request(event="../../other"))
        p = request(); p["rows"].append({**p["rows"][0], "tier": "super_recommended"}); bad.append(p)
        p = request(); p["rows"] = []; bad.append(p)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pub.validate(value, MASTER)

    def test_duplicate_aliases_collapse_without_collapsing_double_circle(self):
        p = request("左回り◯")
        p["rows"] += request("左回り〇")["rows"] + request("左回り◎")["rows"]
        clean = pub.validate(p, MASTER)
        self.assertEqual({r["skill"] for r in clean["rows"]}, {"左回り○", "左回り◎"})

    def test_prepare_filters_unreviewed_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "input.csv"
            rows = [request()["rows"][0], {**request("直線巧者")["rows"][0], "status": "draft"}, {**request("左回り◎")["rows"][0], "status": "rejected"}]
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
            clean, skipped = pub.prepare_csv(path, "event", MASTER)
            self.assertEqual(len(clean["rows"]), 1)
            self.assertEqual(skipped, 2)

    def test_duplicate_json_keys_and_oversized_payload_rejected(self):
        with self.assertRaises(ValueError):
            pub.receive('{"event":"one","event":"two","rows":[]}', MASTER)
        with self.assertRaises(ValueError):
            pub.receive(" " * (pub.MAX_INPUT_BYTES + 1), MASTER)

    def test_end_to_end_cli_and_noop_does_not_create_pending_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); master = root/"master.json"; pub.write(master, MASTER)
            incoming = root/"request.json"; pub.write(incoming, request())
            data = root/"race.json"; pub.write(data, {})
            pending = root/"pending.json"; summary = root/"summary.md"; output = root/"outputs"
            tool = Path(pub.__file__)
            cmd = [sys.executable, str(tool), "--master", str(master), "apply", "--input", str(incoming), "--data", str(data), "--pending-output", str(pending), "--summary", str(summary), "--github-output", str(output)]
            first = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("changed=true", output.read_text())
            pending.unlink(); original = data.read_bytes()
            second = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(data.read_bytes(), original)
            self.assertFalse(pending.exists())
            self.assertIn("changed=false", output.read_text())
            invalid = request("unknown"); pub.write(incoming, invalid)
            failed = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(data.read_bytes(), original)


class DispatchTests(unittest.TestCase):
    def test_dry_run_does_not_access_credentials_or_network(self):
        opener = Mock(side_effect=AssertionError("No network"))
        result = sender.dispatch(request(), None, opener=opener)
        self.assertFalse(result["sent"])
        opener.assert_not_called()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"request.json"; pub.write(path, request())
            result = subprocess.run([sys.executable, sender.__file__, "--input", str(path), "--token-file", str(Path(d)/"missing"), "--dry-run"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["sent"])

    def test_dispatch_uses_existing_actions_auth_and_reports_only_acceptance(self):
        response = Mock(); response.status = 204
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)
        result = sender.dispatch(request(), "fake-test-token", opener=opener)
        req = opener.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body["ref"], "main")
        self.assertEqual(json.loads(body["inputs"]["payload"])["rows"][0]["status"], "ready")
        self.assertTrue(result["sent"])
        self.assertIn("not yet confirmed", result["note"])
        self.assertNotIn("fake-test-token", json.dumps(result))

    def test_draft_dispatch_never_reaches_network(self):
        value = request(); value["rows"][0]["status"] = "draft"
        opener = Mock()
        with self.assertRaises(ValueError):
            sender.dispatch(value, "fake-test-token", opener=opener)
        opener.assert_not_called()

if __name__ == "__main__":
    unittest.main()
