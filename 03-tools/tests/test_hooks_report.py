"""hooks_report.py over a fixture ledger and receipts; the warn -> block
graduation criterion is tested in both directions."""
import json
import tempfile
import unittest
from pathlib import Path

from lib import hooks_report


def _line(**kw):
    base = {"seq": 1, "hook": "guard_gates", "event": "PreToolUse", "agent_type": None, "agent_id": None, "tool": "Bash",
            "kind": "gate-push", "decision": "warn", "mode": "warn", "reason": "", "path": None, "tree": "abc", "receipt": "none"}
    base.update(kw)
    return json.dumps(base)


def _receipt(tier="low", verdict="approved", correction_index=0, reasons=None, ack=None, state="finalized"):
    return {"tree_sha": "t", "state": state, "verdict": verdict, "correction_index": correction_index,
            "risk": {"tier": tier}, "verdict_reasons": reasons or [], "owner_ack": ack, "inherited_from": None}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.hooks = root / "hooks"
        self.receipts = root / "rdd"
        session = self.hooks / "s1"
        session.mkdir(parents=True)
        (session / "ledger.jsonl").write_text("\n".join([
            _line(seq=1),
            _line(seq=2, receipt="approved", decision="allow"),
            _line(seq=3, kind="force-push", decision="deny", mode="block"),
            _line(seq=4, agent_type="generic-proposer", agent_id="a1", kind="budget-deny", decision="deny"),
            _line(seq=5, agent_type="generic-challenger", agent_id="a2", kind="output-invalid", decision="warn", hook="validate_subagent_output"),
        ]) + "\n", encoding="utf-8")
        (session / "budget-generic-proposer-a1.count").write_text("41\n", encoding="utf-8")
        (session / "run-meta.json").write_text(json.dumps({"started_at": "2026-09-01T10:00:00"}), encoding="utf-8")
        other = self.hooks / "s2"
        other.mkdir()
        (other / "run-meta.json").write_text(json.dumps({"started_at": "2026-09-09T10:00:00"}), encoding="utf-8")
        self.receipts.mkdir()
        fixtures = [_receipt(), _receipt(tier="medium"), _receipt(tier="medium", verdict="rejected", reasons=["verifier FAIL"]),
                    _receipt(tier="high", verdict="approved", correction_index=1), _receipt(tier="high", verdict="escalated", ack={"decision": "accept-escalation", "reason": "x"})]
        for i, r in enumerate(fixtures):
            (self.receipts / f"t{i}.receipt.json").write_text(json.dumps(r), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        report = hooks_report.build_report(self.hooks, self.receipts, 7, 5, 2)
        self.assertEqual(report["sessions"], 2)
        self.assertEqual(report["per_agent"]["generic-proposer"]["calls"], 41)
        self.assertEqual(report["per_agent"]["generic-proposer"]["denials"], 1)
        self.assertEqual(report["per_agent"]["generic-challenger"]["invalid_outputs"], 1)
        self.assertEqual(report["gates"]["gate-push_with_receipt"], 1)
        self.assertEqual(report["gates"]["gate-push_without_receipt"], 1)
        self.assertEqual(report["gates"]["force_denied"], 1)
        self.assertEqual(report["receipts"]["by_tier"], {"high": 2, "low": 1, "medium": 2})
        self.assertEqual(report["receipts"]["first_pass_acceptance"], 2)
        self.assertEqual(report["receipts"]["corrections_used"], 1)
        self.assertEqual(report["receipts"]["verifier_fail_caught"], 1)
        self.assertEqual(report["receipts"]["owner_acks"], 1)

    def test_flip_criteria_ready_and_not_ready(self):
        report = hooks_report.build_report(self.hooks, self.receipts, 7, 5, 2)
        self.assertTrue(report["flip_warn_to_block"]["ready"], report["flip_warn_to_block"])
        hooks_report.record_false_positive(self.hooks, "s1", 1, "no era push")
        hooks_report.record_false_positive(self.hooks, "s1", 3, "era lease")
        hooks_report.record_false_positive(self.hooks, "s2", 1, "tercero")
        # negative control: three false positives exceed the cap of two
        self.assertFalse(hooks_report.build_report(self.hooks, self.receipts, 7, 5, 2)["flip_warn_to_block"]["ready"])

    def test_empty_dirs_produce_a_valid_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = hooks_report.build_report(Path(tmp) / "h", Path(tmp) / "r", 7, 5, 2)
            self.assertEqual(report["sessions"], 0)
            self.assertFalse(report["flip_warn_to_block"]["ready"])
            self.assertTrue(report["not_measured"])

    def test_determinism(self):
        a = json.dumps(hooks_report.build_report(self.hooks, self.receipts, 7, 5, 2), sort_keys=True)
        b = json.dumps(hooks_report.build_report(self.hooks, self.receipts, 7, 5, 2), sort_keys=True)
        self.assertEqual(a, b)
