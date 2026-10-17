"""Tests for phase1_report over tiny synthetic extracts (sessions, git, engram, kit)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import phase1_report as pr  # noqa: E402


def session(sid, project, ts, kit, sub=0, peak=1000, comp=0, out=100, cache_read=900, recall=0, save=0,
            reply=(200,), lat=(2.0,), sub_tokens=0, last_ts=None, marker_ts=None):
    marker_ts = marker_ts or (ts if kit else None)
    return {
        "session_id": sid, "project": project, "project_dir": f"-x-{project}", "first_ts": ts, "last_ts": last_ts or ts,
        "duration_s": 100.0, "requests": 5, "versions": ["2.1.2"], "branches": ["main"],
        "tokens": {"main": {"input": 10, "cache_write": 100, "cache_read": cache_read, "output": out},
                   "subagents": {"input": 0, "cache_write": 0, "cache_read": sub_tokens, "output": 0}},
        "peak_context_tokens": peak, "cache_hit_ratio": 0.5, "models": {"claude-opus-5-5": 5}, "model_switches": 0,
        "effort_levels": {}, "tool_calls": {"Read": 4, "Edit": 1}, "mcp_servers": {}, "agent_tool_calls_by_type": {},
        "agent_prompt_chars": [300] * sub, "subagents": {"count": sub, "by_type": {}, "by_model": {}, "requests": 0,
                                                          "peak_context_tokens": 0},
        "skills": {}, "kit": {"uses_kit": kit, "markers": ["mcp:metodo"] if kit else [],
                              "marker_ts": {"mcp:metodo": marker_ts} if kit else {},
                              "first_marker_ts": marker_ts, "weak_markers": []},
        "engram": {"recall_calls": recall, "save_calls": save, "other_calls": 0},
        "hooks": {"by_event": {}, "metodo_runs": 1 if kit else 0},
        "compactions": [{"trigger": "auto", "pre": 150000, "post": 20000}] * comp, "api_errors": 0,
        "turn_durations_ms": [], "cost_usd": 1.0, "permission_modes": {}, "output_style": None,
        "human_prompts": {"count": 1, "chars_total": 50, "chars": [50]}, "slash_commands": 0,
        "final_replies": {"count": len(reply), "chars_total": sum(reply), "chars": list(reply)},
        "latency_s": {"first_response": list(lat), "turn_wall_clock": []},
    }


SESSIONS = {"schema_version": "1.0.0", "tool_sha256": "s", "root": "projects", "failures": [], "sessions": [
    session("s1", "alpha", "2026-08-01T10:00:00.000Z", False, peak=2000, out=100, reply=(400,), lat=(4.0,)),
    session("s2", "alpha", "2026-08-10T10:00:00.000Z", False, sub=2, peak=4000, comp=1, out=200, sub_tokens=5000),
    session("s3", "alpha", "2026-09-05T10:00:00.000Z", True, sub=3, peak=3000, out=150, recall=2, save=1, reply=(100,), lat=(2.0,), sub_tokens=9000),
    session("s4", "alpha", "2026-09-10T10:00:00.000Z", False, peak=1500, out=120),
    session("s5", "alpha", "2026-09-12T10:00:00.000Z", True, peak=2500, out=130, save=2, reply=(150,)),
    session("s6", "beta", "2026-08-20T10:00:00.000Z", False, peak=800),
    # started in July, resumed in September, kit first ran on 2026-09-20: spanning, sets no boundary
    session("s7", "alpha", "2026-07-01T10:00:00.000Z", True, peak=9000, last_ts="2026-09-25T10:00:00.000Z",
            marker_ts="2026-09-20T10:00:00.000Z"),
]}

GIT = {"schema_version": "1.0.0", "tool_sha256": "g", "since": None, "failures": [], "repos": [{
    "name": "alpha", "head": "abc",
    "commits": [
        {"sha": "1", "date": "2026-08-02", "subject": "feat: a", "is_merge": False, "conventional": True, "files": 1,
         "insertions": 10, "deletions": 0, "touches_tests": False, "touches_code": True, "touches_docs": False},
        {"sha": "2", "date": "2026-09-06", "subject": "fix: b", "is_merge": False, "conventional": True, "files": 2,
         "insertions": 20, "deletions": 1, "touches_tests": True, "touches_code": True, "touches_docs": False},
        {"sha": "3", "date": "2026-09-07", "subject": "wip", "is_merge": False, "conventional": False, "files": 1,
         "insertions": 5, "deletions": 0, "touches_tests": False, "touches_code": True, "touches_docs": False},
    ],
    "merges": [{"sha": "m1", "date": "2026-08-05", "subject": "Merge a", "commits": 2, "lead_time_days": 3.0},
               {"sha": "m2", "date": "2026-09-09", "subject": "Merge b", "commits": 2, "lead_time_days": 1.0}],
    "by_month": {}, "summary": {"commits": 3, "merges": 2, "conventional_rate": 0.666667, "code_commits": 3,
                                "code_commits_with_tests_rate": 0.333333, "first_date": "2026-08-02", "last_date": "2026-09-07"},
}]}

ENGRAM = {"schema_version": "1.0.0", "tool_sha256": "e",
          "projects": {"alpha": {"sessions": 3, "sessions_with_observations": 2, "observations": 4,
                                 "by_type": {"decision": 3, "session_summary": 1}, "with_topic_key": 2, "upserted": 1,
                                 "pinned": 0, "prompts": 5, "first_session": "2026-09-05", "last_session": "2026-09-12",
                                 "ownership": {}}},
          "sessions": [{"session_id": "s3", "project": "alpha", "started_at": "2026-09-05", "observations": 3, "by_type": {"decision": 3}, "prompts": 2},
                       {"session_id": "s5", "project": "alpha", "started_at": "2026-09-12", "observations": 1, "by_type": {"session_summary": 1}, "prompts": 2},
                       {"session_id": "zz", "project": "alpha", "started_at": "2026-09-13", "observations": 0, "by_type": {}, "prompts": 1}],
          "totals": {"sessions": 3, "sessions_with_zero_observations": 1, "observations": 4, "prompts": 5, "relations": 0,
                     "relations_by_relation": {}, "relations_pending": 0}}

KIT = {"schema_version": "1.0.0", "tool_sha256": "k", "instances": [{
    "name": "alpha-tools",
    "sessions": [{"session_id": "s3", "dir_ts": "x", "started_at": "2026-09-05T10:00:00", "lines": 3,
                  "by_kind_decision": {"session-start:log": 1, "gate-push:warn": 1, "reply-lint:warn": 1},
                  "by_hook": {}, "reply_lint_rule_hits": {"COM-09": 1}, "budget_by_agent_type": {}, "touched_paths": 2},
                 {"session_id": "other", "dir_ts": "y", "started_at": "2026-09-06T10:00:00", "lines": 1,
                  "by_kind_decision": {"session-start:log": 1}, "by_hook": {}, "reply_lint_rule_hits": {},
                  "budget_by_agent_type": {}, "touched_paths": 0}],
    "receipts": {"count": 2, "voids": 1, "by_state": {"finalized": 2}, "by_verdict": {"approved": 1, "rejected": 1},
                 "by_risk": {}, "captures_total": 4, "diff_insertions_total": 50, "items": []},
    "totals": {"sessions": 2, "ledger_lines": 4, "by_kind_decision": {"session-start:log": 2, "gate-push:warn": 1, "reply-lint:warn": 1},
               "first_started_at": "2026-09-05", "last_started_at": "2026-09-06"},
}]}


class Phase1ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = pathlib.Path(self.tmp.name) / "data"
        self.data.mkdir()
        for name, payload in (("sessions", SESSIONS), ("git", GIT), ("engram", ENGRAM), ("kit", KIT)):
            (self.data / f"{name}.json").write_text(json.dumps(payload))
        self.report = pr.build(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_adoption_and_groups(self):
        a = self.report["adoption"]["alpha"]
        self.assertEqual(a["date"], "2026-09-05")
        self.assertEqual(a["label"], "Inferred")
        self.assertEqual(a["first_kit_session"], "s3")
        self.assertEqual(a["first_marker"], "mcp:metodo")
        self.assertEqual(a["kit_sessions"], 3)
        self.assertIsNone(self.report["adoption"]["beta"]["date"])
        g = self.report["groups"]["alpha"]
        self.assertEqual(g["before"]["n"], 2)
        self.assertEqual(g["after_kit"]["n"], 2)
        self.assertEqual(g["after_no_kit"]["n"], 1)
        self.assertEqual(g["spanning"]["n"], 1)
        self.assertEqual(self.report["monthly"]["alpha"]["2026-09"]["n"], 3)
        self.assertEqual(self.report["monthly"]["alpha"]["2026-07"]["kit_sessions"], 1)
        self.assertEqual(self.report["groups"]["beta"]["before"]["n"], 0)
        self.assertEqual(self.report["groups"]["beta"]["no_adoption"]["n"], 1)

    def test_group_metrics(self):
        before = self.report["groups"]["alpha"]["before"]["metrics"]
        after = self.report["groups"]["alpha"]["after_kit"]["metrics"]
        self.assertEqual(before["M04_peak_context"]["median"], 3000)
        self.assertEqual(after["M04_peak_context"]["median"], 2750)
        self.assertEqual(before["M02_output_tokens"]["sum"], 300)
        self.assertEqual(after["M51_engram_recall_calls"]["sum"], 2)
        self.assertEqual(after["M50_engram_save_calls"]["sum"], 3)
        self.assertEqual(before["M10_final_reply_chars"]["median"], 300)
        self.assertEqual(after["M12_first_response_s"]["median"], 2.0)
        self.assertEqual(before["M05_compactions"]["sum"], 1)
        self.assertEqual(after["M07_subagent_token_share"]["median"], round((9000 / (9000 + 10 + 100 + 900 + 150) + 0) / 2, 6))
        self.assertEqual(before["M04_peak_context"]["label"], "Measured")

    def test_context_cells_s22(self):
        cells = self.report["context_cells"]
        self.assertEqual(cells["kit|with_subagents"]["n"], 1)
        self.assertEqual(cells["kit|without_subagents"]["n"], 2)
        self.assertEqual(cells["kit|with_subagents"]["M04_peak_context"]["median"], 3000)
        self.assertEqual(cells["no_kit|with_subagents"]["M66_compactions_per_1m_input"]["value"], round(1 / ((10 + 100 + 900) / 1e6), 3))
        self.assertEqual(cells["no_kit|without_subagents"]["n"], 3)
        self.assertEqual(cells["kit|with_subagents"]["M65_agent_prompt_chars"]["median"], 300)

    def test_git_split(self):
        g = self.report["git"]["alpha"]
        self.assertEqual(g["before"]["commits"], 1)
        self.assertEqual(g["after"]["commits"], 2)
        self.assertEqual(g["after"]["conventional_rate"], 0.5)
        self.assertEqual(g["after"]["code_commits_with_tests_rate"], 0.5)
        self.assertEqual(g["before"]["lead_time_days_median"], 3.0)
        self.assertEqual(g["after"]["lead_time_days_median"], 1.0)
        self.assertEqual(g["before"]["label"], "Measured")

    def test_engram_and_kit_joins(self):
        e = self.report["engram"]["alpha"]
        self.assertEqual(e["sessions_with_zero_observations"], 1)
        self.assertEqual(e["joined_transcript_sessions"], 2)
        self.assertEqual(e["sessions_saving_without_recall"], 1)  # s5 saves, never recalls
        k = self.report["kit"]["alpha-tools"]
        self.assertEqual(k["ledger_sessions"], 2)
        self.assertEqual(k["joined_transcript_sessions"], 1)
        self.assertEqual(k["by_kind_decision"]["gate-push:warn"], 1)
        self.assertEqual(k["receipts"]["by_verdict"], {"approved": 1, "rejected": 1})

    def test_missing_input_is_reported_not_hidden(self):
        (self.data / "kit.json").unlink()
        report = pr.build(self.data)
        self.assertEqual(report["inputs"]["kit"]["status"], "failed")
        self.assertEqual(report["kit"], {})
        md = pr.render_md(report)
        self.assertIn("kit.json: failed", md)

    def test_cli_is_deterministic_and_md_has_labels(self):
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "phase1_report.py"), "--data", str(self.data),
                                "--out-dir", od], check=True, capture_output=True)
                outs.append((pathlib.Path(od) / "phase1-baseline.json").read_bytes() +
                            (pathlib.Path(od) / "phase1-baseline.md").read_bytes())
        self.assertEqual(outs[0], outs[1])
        md = outs[0].decode()
        self.assertIn("| Measured |", md)
        self.assertIn("Inferred", md)
        self.assertIn("Unknown", md)


if __name__ == "__main__":
    unittest.main()
