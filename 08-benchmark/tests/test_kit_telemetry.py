"""Tests for kit_telemetry over a synthetic tools instance (out/hooks + out/rdd)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import kit_telemetry as kt  # noqa: E402

SID1 = "aaaaaaaa-0000-0000-0000-000000000001"
SID2 = "aaaaaaaa-0000-0000-0000-000000000002"


def _ledger_line(seq, hook, kind, decision, agent_type="", tool="", reason="", tree="t1"):
    return {"seq": seq, "hook": hook, "event": "PreToolUse", "agent_type": agent_type, "agent_id": "",
            "tool": tool, "kind": kind, "decision": decision, "mode": "warn", "reason": reason,
            "path": "/private/secret/file.kt", "tree": tree, "receipt": ""}


def build_instance(root: pathlib.Path) -> pathlib.Path:
    inst = root / "proj-tools"
    hooks = inst / "out" / "hooks"
    d1 = hooks / f"2026-09-16T10-00-00-000Z_{SID1}"
    d2 = hooks / f"2026-09-17T10-00-00-000Z_{SID2}"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    (d1 / "run-meta.json").write_text(json.dumps({"started_at": "2026-09-16T12:00:00", "host": "mac", "session_id": SID1}))
    (d1 / "ledger.jsonl").write_text("\n".join(json.dumps(x) for x in [
        _ledger_line(1, "session_start_status", "session-start", "log"),
        _ledger_line(2, "guard_gates", "gate-push", "warn", tool="Bash", reason="no receipt"),
        _ledger_line(3, "budget", "budget-deny", "deny", agent_type="generic-judge"),
        _ledger_line(4, "reply_lint", "reply-lint", "warn", reason="COM-09,COM-19"),
    ]) + "\n")
    (d1 / "touched.jsonl").write_text(json.dumps({"path": "/private/secret/a.kt", "agent_type": ""}) + "\n")
    (d2 / "run-meta.json").write_text(json.dumps({"started_at": "2026-09-17T12:00:00", "host": "mac", "session_id": SID2}))
    (d2 / "ledger.jsonl").write_text(json.dumps(_ledger_line(1, "session_start_status", "session-start", "log")) + "\n")
    rdd = inst / "out" / "rdd"
    rdd.mkdir()
    (rdd / "t1.receipt.json").write_text(json.dumps({
        "schema_version": "1.0.0", "tree_sha": "t1", "state": "finalized", "verdict": "PASS",
        "correction_index": 1, "repo_sha": "abc", "round_dir": "~/secret/round", "owner_ack": {"ack": True},
        "diff_stats": {"files": 3, "insertions": 40, "deletions": 5}, "risk": {"tier": "medium"},
        "captures": [{"role": "judge"}, {"role": "adversary"}], "verdict_reasons": ["ok"]}))
    (rdd / "t0.receipt.json").write_text(json.dumps({
        "schema_version": "1.0.0", "tree_sha": "t0", "state": "open", "verdict": None,
        "correction_index": 0, "repo_sha": "abb", "round_dir": "~/secret/round0", "owner_ack": {},
        "diff_stats": {"files": 1, "insertions": 2, "deletions": 0}, "risk": {}, "captures": [], "verdict_reasons": []}))
    (rdd / "t0.void-1.json").write_text(json.dumps({"tree_sha": "t0", "reason": "tool drift"}))
    return inst


class KitTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inst = build_instance(pathlib.Path(self.tmp.name))
        self.result = kt.analyze_instance(self.inst)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sessions(self):
        s = {x["session_id"]: x for x in self.result["sessions"]}
        self.assertEqual(s[SID1]["started_at"], "2026-09-16T12:00:00")
        self.assertEqual(s[SID1]["lines"], 4)
        self.assertEqual(s[SID1]["by_kind_decision"], {"budget-deny:deny": 1, "gate-push:warn": 1,
                                                        "reply-lint:warn": 1, "session-start:log": 1})
        self.assertEqual(s[SID1]["reply_lint_rule_hits"], {"COM-09": 1, "COM-19": 1})
        self.assertEqual(s[SID1]["touched_paths"], 1)
        self.assertEqual(s[SID1]["budget_by_agent_type"], {"generic-judge": {"budget-deny": 1}})
        self.assertEqual(s[SID2]["lines"], 1)

    def test_receipts(self):
        r = self.result["receipts"]
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["voids"], 1)
        self.assertEqual(r["by_state"], {"finalized": 1, "open": 1})
        self.assertEqual(r["by_verdict"], {"PASS": 1, "none": 1})
        self.assertEqual(r["captures_total"], 2)
        self.assertEqual(r["diff_insertions_total"], 42)

    def test_totals_and_privacy(self):
        t = self.result["totals"]
        self.assertEqual(t["sessions"], 2)
        self.assertEqual(t["by_kind_decision"]["gate-push:warn"], 1)
        self.assertEqual(t["first_started_at"], "2026-09-16")
        dump = json.dumps(self.result)
        self.assertNotIn("secret", dump)

    def test_cli_is_deterministic(self):
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                out = pathlib.Path(od) / "k.json"
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "kit_telemetry.py"),
                                "--instance", str(self.inst), "--out", str(out)], check=True, capture_output=True)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(json.loads(outs[0])["instances"][0]["name"], "proj-tools")


if __name__ == "__main__":
    unittest.main()
