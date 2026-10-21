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


# ---------------------------------------------------------------- T9 (WU9)

TOOLS = Path(hooks_report.__file__).resolve().parent.parent
THRESHOLDS = json.loads((TOOLS / "config" / "activation.json").read_text(encoding="utf-8"))["thresholds"]
AS_OF = "2026-10-20"


def _day(offset):
    import datetime
    return (datetime.date.fromisoformat(AS_OF) - datetime.timedelta(days=offset)).isoformat()


class Fixture(unittest.TestCase):
    """A hooks dir built session by session; `old` opens the observation one
    full window back so the window is met unless a test removes it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hooks = Path(self.tmp.name) / "hooks"
        self.session("old", 6, [])

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, days_ago, lines, runs=None):
        sdir = self.hooks / name
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "run-meta.json").write_text(json.dumps({"started_at": _day(days_ago) + "T09:00:00"}), encoding="utf-8")
        ledger = sdir / "ledger.jsonl"
        existing = hooks_report.read_jsonl(ledger)
        with ledger.open("a", encoding="utf-8") as fh:
            for i, line in enumerate(lines, start=len(existing) + 1):
                fh.write(_line(**dict(line, seq=i)) + "\n")
        if runs:
            with (sdir / "hook-runs.jsonl").open("a", encoding="utf-8") as fh:
                for run in runs:
                    fh.write(json.dumps(run) + "\n")
        return sdir

    def warns(self, n, **kw):
        return [dict({"kind": "gate-push", "decision": "warn", "mode": "warn"}, **kw) for _ in range(n)]

    def cli(self, *args):
        """hooks_report.main with stdout and stderr captured (usage errors raise SystemExit)."""
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return hooks_report.main(["--hooks-dir", str(self.hooks), *args])

    def mark(self, session, seqs):
        for seq in seqs:
            hooks_report.mark_false_positive(self.hooks, session, seq, "owner says no")

    def verdicts(self, as_of=AS_OF, metrics=None):
        return hooks_report.verdicts(self.hooks, as_of, THRESHOLDS, transcript_metrics=metrics)

    def element(self, name, **kw):
        return self.verdicts(**kw)["elements"][name]

    def metrics_file(self, judged, acted, kind="gate-push", day=0):
        path = Path(self.tmp.name) / "sessions.json"
        path.write_text(json.dumps({"sessions": [{"session_id": "t1", "first_ts": _day(day) + "T10:00:00Z",
                                                  "context_metrics": {"warn_act": {"id": "M107", "by_kind": {
                                                      kind: {"fires": judged, "judged": judged, "acted": acted}}}}}]}),
                        encoding="utf-8")
        return path


class MarkFalsePositiveTests(Fixture):
    def test_mark_appends_to_the_session_file_and_never_touches_the_ledger(self):
        sdir = self.session("s1", 0, self.warns(3))
        before = (sdir / "ledger.jsonl").read_bytes()
        self.assertEqual(self.cli("--mark-fp", "s1", "2", "--reason", "not a push"), 0)
        self.cli("--mark-fp", "s1", "3", "--reason", "lease")
        marks = hooks_report.read_jsonl(sdir / "false-positives.jsonl")
        self.assertEqual([(m["session"], m["seq"], m["reason"], m["element"]) for m in marks],
                         [("s1", 2, "not a push", "push_gate"), ("s1", 3, "lease", "push_gate")])
        self.assertEqual((sdir / "ledger.jsonl").read_bytes(), before)

    def test_unknown_line_is_refused_and_nothing_is_written(self):
        sdir = self.session("s1", 0, self.warns(1))
        with self.assertRaises(SystemExit) as ctx:
            self.cli("--mark-fp", "s1", "9", "--reason", "x")
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse((sdir / "false-positives.jsonl").exists())

    def test_mark_fp_script_appends(self):
        import subprocess
        sdir = self.session("s1", 0, self.warns(1))
        proc = subprocess.run([str(TOOLS / "bin" / "mark-fp.sh"), "s1", "1", "--reason", "owner mark",
                               "--hooks-dir", str(self.hooks)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(hooks_report.read_jsonl(sdir / "false-positives.jsonl")[0]["reason"], "owner mark")


class VerdictTests(Fixture):
    def test_fires_boundary_19_is_insufficient_20_is_measured(self):
        self.session("cur", 0, self.warns(19))
        self.mark("cur", [1])
        self.assertEqual(self.element("push_gate", metrics=self.metrics_file(10, 5))["verdict"], "INSUFFICIENT_DATA")
        self.session("cur", 0, self.warns(1))
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertEqual((e["fires"], e["verdict"], e["recommend"]), (20, "PROMOTE", "BLOCK"))

    def test_window_not_met_without_a_full_window_of_observation(self):
        import shutil
        shutil.rmtree(self.hooks / "old")
        self.session("cur", 0, self.warns(30))
        self.assertEqual(self.element("push_gate")["verdict"], "INSUFFICIENT_DATA")

    def test_precision_boundary(self):
        self.session("a", 0, self.warns(20))
        self.mark("a", [1, 2])
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertEqual((e["precision"], e["verdict"]), (0.9, "PROMOTE"))
        self.session("b", 1, self.warns(80))
        self.mark("b", range(1, 10))  # 11 of 100
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertEqual((e["precision"], e["verdict"], e["recommend"]), (0.89, "DEMOTE", "OFF"))

    def test_precision_ok_but_more_than_two_fps_is_not_promoted(self):
        self.session("a", 0, self.warns(30))
        self.mark("a", [1, 2, 3])
        e = self.element("push_gate")
        self.assertEqual((e["precision"], e["verdict"]), (0.9, "KEEP"))

    def _asks(self, overrides):
        lines = []
        for i in range(100):
            lines.append({"kind": "gate-push", "decision": "ask", "mode": "block", "tree": f"t{i}"})
            if i < overrides:
                lines.append({"kind": "gate-push-outcome", "decision": "ran", "mode": "block", "tree": f"t{i}"})
        return lines

    def test_override_boundary(self):
        self.session("a", 0, self._asks(10))
        e = self.element("push_gate")
        self.assertEqual((e["override_rate"], e["block_rate"], e["verdict"]), (0.1, 1.0, "KEEP"))  # already BLOCK
        self.session("a", 0, [{"kind": "gate-push-outcome", "decision": "ran", "mode": "block", "tree": "t10"}])
        e = self.element("push_gate")
        self.assertEqual((e["override_rate"], e["verdict"]), (0.11, "DEMOTE"))

    def test_an_outcome_on_another_tree_is_not_an_override(self):
        self.session("a", 0, self._asks(0) + [{"kind": "gate-push-outcome", "decision": "ran", "mode": "block", "tree": "zz"}])
        self.assertEqual(self.element("push_gate")["override_rate"], 0.0)

    def test_override_without_outcome_lines_is_unmeasured_never_zero(self):
        self.session("a", 0, [{"kind": "gate-push", "decision": "ask", "mode": "block"}] * 20)
        e = self.element("push_gate")
        self.assertIsNone(e["override_rate"])
        self.assertIn("override_rate", [n["metric"] for n in e["not_measured"]])

    def test_act_rate_boundary_from_transcript_metrics(self):
        self.session("a", 0, self.warns(20))
        self.mark("a", [1])
        e = self.element("push_gate", metrics=self.metrics_file(100, 9))
        self.assertEqual((e["act_rate"], e["verdict"]), (0.09, "DEMOTE"))
        e = self.element("push_gate", metrics=self.metrics_file(100, 10))
        self.assertEqual((e["act_rate"], e["verdict"]), (0.1, "PROMOTE"))

    def test_act_rate_not_measured_without_metrics_or_outside_the_window(self):
        self.session("a", 0, self.warns(20))
        e = self.element("push_gate")
        self.assertIsNone(e["act_rate"])
        self.assertIn("act_rate", [n["metric"] for n in e["not_measured"]])
        e = self.element("push_gate", metrics=self.metrics_file(100, 0, day=30))
        self.assertIsNone(e["act_rate"])

    def test_absolute_set_is_always_keep(self):
        self.session("a", 0, [{"kind": "force-push", "decision": "deny", "mode": "block"}] * 40)
        self.mark("a", range(1, 21))
        e = self.element("force_push")
        self.assertEqual((e["precision"], e["verdict"], e["recommend"]), (0.5, "KEEP", "BLOCK"))
        self.assertTrue(e["absolute"])

    def test_expiry_after_two_windows(self):
        scope = {"kind": "scope-outside", "decision": "warn", "mode": "log", "agent_type": "generic-proposer", "agent_id": "a1"}
        self.session("first", 13, [scope])
        self.session("a", 0, [scope] * 3)
        self.assertEqual(self.element("subagent_scope")["verdict"], "INSUFFICIENT_DATA")
        self.session("first2", 14, [scope])
        e = self.element("subagent_scope")
        self.assertEqual((e["age_days"], e["verdict"], e["recommend"]), (14, "EXPIRE", "OFF"))

    def test_expiry_does_not_override_a_promotion(self):
        self.session("first", 20, self.warns(1))
        self.session("a", 0, self.warns(20))
        self.mark("a", [1])
        self.assertEqual(self.element("push_gate", metrics=self.metrics_file(10, 5))["verdict"], "PROMOTE")

    def test_main_session_deny_fp_blocks_a_promotion(self):
        self.session("a", 0, [{"kind": "scope-outside", "decision": "deny", "mode": "warn"}] * 20)
        self.mark("a", [1])
        e = self.element("subagent_scope")
        self.assertEqual((e["main_deny_false_positives"], e["verdict"]), (1, "KEEP"))

    # T18 (B-007/A-009): unmeasured data never earns PROMOTE.
    def test_warn_element_without_fp_marks_is_not_promoted_and_names_precision(self):
        self.session("a", 0, self.warns(20))
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertIsNone(e["precision"])
        self.assertEqual((e["verdict"], e["recommend"]), ("INSUFFICIENT_DATA", None))
        self.assertIn("precision", [n["metric"] for n in e["not_measured"]])
        self.assertTrue(any("precision" in r for r in e["reasons"]), e["reasons"])

    def test_warn_element_without_act_rate_is_not_promoted_and_names_it(self):
        self.session("a", 0, self.warns(20))
        self.mark("a", [1])
        e = self.element("push_gate")
        self.assertEqual(e["verdict"], "INSUFFICIENT_DATA")
        self.assertTrue(any("act_rate" in r for r in e["reasons"]), e["reasons"])

    def test_asks_without_outcome_lines_are_not_promoted(self):
        asks = [{"kind": "gate-push", "decision": "ask", "mode": "warn", "tree": f"t{i}"} for i in range(20)]
        self.session("a", 0, asks)
        self.mark("a", [1])
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertIsNone(e["override_rate"])
        self.assertEqual(e["verdict"], "INSUFFICIENT_DATA")
        self.assertTrue(any("override_rate" in r for r in e["reasons"]), e["reasons"])

    def test_measured_asks_with_outcomes_can_still_promote(self):
        # negative control: every PROMOTE criterion measured
        lines = []
        for i in range(20):
            lines.append({"kind": "gate-push", "decision": "ask", "mode": "warn", "tree": f"t{i}"})
            lines.append({"kind": "gate-push-outcome", "decision": "skipped", "mode": "warn", "tree": f"t{i}"})
        self.session("a", 0, lines)
        self.mark("a", [1])
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertEqual((e["override_rate"], e["verdict"]), (0.0, "PROMOTE"))

    def test_an_element_whose_lines_are_all_mode_off_is_never_promoted(self):
        self.session("a", 0, self.warns(20, mode="off"))
        self.mark("a", [1])
        e = self.element("push_gate", metrics=self.metrics_file(10, 5))
        self.assertNotEqual(e["verdict"], "PROMOTE")
        self.assertIn(e["verdict"], ("KEEP", "INSUFFICIENT_DATA"))
        self.assertTrue(any("mode off" in r for r in e["reasons"]), e["reasons"])

    def test_fire_rate_from_run_lines(self):
        run = {"kind": "run", "hook": "guard_gates", "element": "push_gate", "mode": "warn", "outcome": "silent",
               "elapsed_ms": 3.0}
        self.session("a", 0, self.warns(20), runs=[run] * 80)
        e = self.element("push_gate")
        self.assertEqual((e["runs"], e["fire_rate"]), (80, 0.25))

    def test_determinism_and_dates_only_from_as_of(self):
        self.session("a", 0, self.warns(20))
        self.session("future", -3, self.warns(50))  # after --as-of: ignored
        out = []
        for _ in range(2):
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(hooks_report.main(["--hooks-dir", str(self.hooks), "--verdicts", "--as-of", AS_OF]), 0)
            out.append(buf.getvalue())
        self.assertEqual(out[0], out[1])
        report = json.loads(out[0])
        self.assertEqual(report["elements"]["push_gate"]["fires"], 20)
        self.assertEqual(report["as_of"], AS_OF)
        self.assertIn("card", report["note"])

    def test_verdicts_require_as_of_and_never_write_config(self):
        with self.assertRaises(SystemExit):
            self.cli("--verdicts")
        self.session("a", 0, self.warns(20))
        config = TOOLS / "config" / "activation.json"
        before = config.read_bytes()
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            hooks_report.main(["--hooks-dir", str(self.hooks), "--verdicts", "--as-of", AS_OF, "--format", "md"])
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.hooks.iterdir()), ["a", "old"])  # nothing written

    def test_markdown_is_short_and_names_each_verdict(self):
        self.session("a", 0, self.warns(20))
        self.mark("a", [1])
        md = hooks_report.verdicts_markdown(self.verdicts(metrics=self.metrics_file(10, 5)))
        self.assertIn("| push_gate |", md)
        self.assertIn("PROMOTE", md)
        self.assertLessEqual(len(md.splitlines()), 40)
