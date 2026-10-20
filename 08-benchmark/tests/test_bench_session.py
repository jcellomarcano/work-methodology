"""Tests for bench_session (observational mode) and bench_cli: synthetic transcripts only."""
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import bench_cli  # noqa: E402
import bench_session as bs  # noqa: E402
import transcript_metrics as tm  # noqa: E402
from tests import test_transcript_metrics as ttm  # noqa: E402

SECRET = "ZEBRA-SECRET-42"
VSID = "99999999-8888-7777-6666-555555555555"
LABELS = {"Measured", "Tested", "Inferred", "Assumed", "Unknown"}
STATUSES = {"ok", "failed", "not-run", "invalid-arm"}


def build_vanilla(root: pathlib.Path, name="-home-y-other", sid=VSID, day="2026-10-01", model="mystery-model-1"):
    """A session with no kit marker, no subagent, no cost record and an unknown model."""
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    common = {"sessionId": sid, "cwd": "/home/y/other", "version": "2.1.300"}
    usage = {"input_tokens": 50, "cache_creation_input_tokens": 100,
             "cache_read_input_tokens": 850, "output_tokens": 30}
    recs = [
        dict(common, type="user", timestamp=f"{day}T09:00:00.000Z", origin={"kind": "human"},
             message={"role": "user", "content": f"please handle {SECRET} now"}),
        dict(common, type="assistant", timestamp=f"{day}T09:00:05.000Z", effort="low",
             message={"id": "m_v1", "model": model, "role": "assistant", "usage": usage,
                      "content": [{"type": "text", "text": f"I saw {SECRET}."},
                                  {"type": "tool_use", "id": "tv1", "name": "Skill",
                                   "input": {"skill": "harness-benchmark", "args": SECRET}}]}),
        dict(common, type="attachment", timestamp=f"{day}T09:00:06.000Z",
             attachment={"type": "queued_command", "prompt": f"{SECRET} again", "origin": {"kind": "human"}}),
        dict(common, type="assistant", timestamp=f"{day}T09:01:00.000Z",
             message={"id": "m_v2", "model": model, "role": "assistant", "usage": usage,
                      "content": [{"type": "text", "text": "ok"}]}),
    ]
    (proj / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return proj


def run_session(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = bs.main(argv)
    return code, out.getvalue(), err.getvalue()


class SessionReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(os.path.realpath(self.tmp.name))
        self.root = base / "projects"
        self.root.mkdir()
        ttm.build_fixture(self.root, extra=ttm.QUEUED_RECORDS)
        build_vanilla(self.root)
        self.out = base / "out"
        code, _, err = run_session(["--root", str(self.root), "--out", str(self.out)])
        self.assertEqual(code, 0, err)
        self.report = json.loads((self.out / "session-report.json").read_text())
        self.md = (self.out / "session-report.md").read_text()
        self.by_id = {s["session_id"]: s for s in self.report["sessions"]}
        self.kit = self.by_id[ttm.SID]["metrics"]
        self.van = self.by_id[VSID]["metrics"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_header_has_schema_and_tool_sha(self):
        self.assertEqual(self.report["schema_version"], bs.SCHEMA_VERSION)
        self.assertEqual(self.report["tool_sha256"],
                         hashlib.sha256((ROOT / "lib" / "bench_session.py").read_bytes()).hexdigest())

    def test_groups_split_by_kit_and_by_subagents(self):
        g = self.report["groups"]
        self.assertEqual(g["by_kit"]["kit"]["n"], 1)
        self.assertEqual(g["by_kit"]["no-kit"]["n"], 1)
        self.assertEqual(g["by_subagents"]["with-subagents"]["n"], 1)
        self.assertEqual(g["by_subagents"]["without-subagents"]["n"], 1)
        self.assertEqual(g["all"]["n"], 2)
        self.assertEqual(self.by_id[ttm.SID]["group"], {"kit": "kit", "subagents": "with-subagents"})
        self.assertEqual(self.by_id[VSID]["group"], {"kit": "no-kit", "subagents": "without-subagents"})

    def test_every_metric_row_has_a_label_and_a_status(self):
        rows = []

        def walk(node):
            if isinstance(node, dict):
                if "value" in node:
                    rows.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk({"sessions": self.report["sessions"], "groups": self.report["groups"]})
        self.assertGreater(len(rows), 40)
        for row in rows:
            self.assertIn(row.get("label"), LABELS, row)
            self.assertIn(row.get("status"), STATUSES, row)
        for group in self.report["groups"]["by_kit"].values():
            for name, row in group["metrics"].items():
                self.assertIn("n", row, name)

    def test_activation(self):
        act = self.kit["activation"]
        self.assertEqual(act["kit_strong"]["value"], True)
        self.assertEqual(act["kit_markers"]["value"], ["hook:metodo", "subagent:generic-judge"])
        self.assertEqual(act["skills"]["value"], {"respuesta-humana": 1})
        self.assertEqual(act["mcp_servers"]["value"], {"engram": 1})
        # the benchmark skill itself is not a kit marker
        self.assertEqual(self.van["activation"]["kit_strong"]["value"], False)
        self.assertEqual(self.van["activation"]["skills"]["value"], {"harness-benchmark": 1})
        group = self.report["groups"]["by_kit"]["kit"]["metrics"]
        self.assertEqual(group["sessions_with_kit_markers"]["value"], 1)

    def test_tokens_by_type(self):
        t = self.kit["tokens"]
        self.assertEqual(t["main"]["value"], {"cache_read": 8800, "cache_write": 1000, "input": 30, "output": 160})
        self.assertEqual(t["subagents"]["value"], {"cache_read": 0, "cache_write": 0, "input": 100, "output": 200})
        self.assertEqual(t["total"]["value"], 9990 + 300)
        self.assertEqual(t["total"]["label"], "Measured")

    def test_cost_names_its_source(self):
        self.assertEqual(self.kit["cost_usd"]["value"], 0.42)
        self.assertEqual(self.kit["cost_usd"]["source"], "transcript cost-state")
        self.assertEqual(self.kit["cost_usd"]["status"], "ok")
        self.assertIsNone(self.van["cost_usd"]["value"])
        self.assertEqual(self.van["cost_usd"]["source"], "not recorded")
        self.assertEqual(self.van["cost_usd"]["label"], "Unknown")
        self.assertEqual(self.van["cost_usd"]["status"], "not-run")
        group = self.report["groups"]["all"]["metrics"]["cost_usd_median"]
        self.assertEqual((group["value"], group["n"]), (0.42, 1))
        self.assertIn("cost-state", group["source"])

    def test_peak_context_and_occupancy(self):
        ctx = self.kit["context"]
        self.assertEqual(ctx["peak_tokens"]["value"], 2105)
        self.assertEqual(ctx["window_tokens"]["value"], 1_000_000)  # fixture model is a 1M-window model
        self.assertEqual(ctx["window_tokens"]["label"], "Assumed")
        self.assertEqual(ctx["occupancy"]["value"], round(2105 / 1_000_000, 6))
        self.assertEqual(ctx["occupancy"]["status"], "ok")
        unknown = self.van["context"]["occupancy"]
        self.assertEqual((unknown["value"], unknown["label"], unknown["status"]), (None, "Unknown", "not-run"))

    def test_window_table_override(self):
        table = self.out.parent / "windows.json"
        table.write_text(json.dumps({"mystery-model": 1000}))
        out = self.out.parent / "out2"
        code, _, err = run_session(["--root", str(self.root), "--out", str(out), "--window-table", str(table)])
        self.assertEqual(code, 0, err)
        rep = json.loads((out / "session-report.json").read_text())
        van = {s["session_id"]: s for s in rep["sessions"]}[VSID]["metrics"]["context"]
        self.assertEqual(van["occupancy"]["value"], 1.0)
        self.assertEqual(van["window_tokens"]["value"], 1000)

    def test_compactions_with_tokens_dropped(self):
        comp = self.kit["compactions"]
        self.assertEqual(comp["count"]["value"], 1)
        self.assertEqual(comp["tokens_dropped"]["value"], 130000)

    def test_delegation_shape(self):
        d = self.kit["delegation"]
        self.assertEqual(d["subagent_token_share"]["value"], round(300 / (9990 + 300), 6))
        self.assertEqual(d["subagents_by_type"]["value"], {"generic-judge": 1})
        self.assertEqual(self.van["delegation"]["subagent_token_share"]["value"], 0.0)

    def test_model_effort_mix(self):
        self.assertEqual(self.kit["model_effort"]["value"],
                         {"claude-haiku-5-5": {"unset": 1}, "claude-opus-5-5": {"high": 1, "unset": 3}})
        mix = self.report["groups"]["all"]["metrics"]["model_effort_share"]
        self.assertEqual(mix["n"], 7)
        self.assertEqual(mix["value"]["mystery-model-1"]["low"], round(1 / 7, 6))

    def test_human_steering_and_wall_clock(self):
        self.assertEqual(self.kit["steering"]["turns"]["value"], 2)
        self.assertEqual(self.kit["steering"]["queued_messages"]["value"], 1)
        self.assertEqual(self.van["steering"]["queued_messages"]["value"], 1)
        self.assertEqual(self.kit["wall_clock_s"]["value"], 302.0)

    def test_markdown_has_legend_n_and_correlational_line(self):
        self.assertIn(bs.CORRELATIONAL_LINE, self.md)
        for label in LABELS:
            self.assertIn(label, self.md)
        self.assertIn("| n |", self.md)
        self.assertIn("signal", self.md.lower())

    def test_outputs_are_deterministic(self):
        out = self.out.parent / "again"
        code, _, _ = run_session(["--root", str(self.root), "--out", str(out)])
        self.assertEqual(code, 0)
        for name in ("session-report.json", "session-report.md"):
            self.assertEqual((self.out / name).read_bytes(), (out / name).read_bytes(), name)

    def test_no_private_text_or_absolute_paths(self):
        for name in ("session-report.json", "session-report.md"):
            text = (self.out / name).read_text()
            for needle in (SECRET, "login bug", "check the logs", "Welcome", "/Users/", "/home/", "/private/"):
                self.assertNotIn(needle, text, f"{needle} in {name}")


class SessionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(os.path.realpath(self.tmp.name))
        self.root = self.base / "projects"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _ids(self, argv):
        out = self.base / "o"
        shutil.rmtree(out, ignore_errors=True)
        code, _, err = run_session(["--root", str(self.root), "--out", str(out)] + argv)
        self.assertEqual(code, 0, err)
        return sorted(s["session_id"] for s in json.loads((out / "session-report.json").read_text())["sessions"])

    def test_project_path_uses_exactly_its_transcript_dir(self):
        repo = self.base / "my_repo"
        repo.mkdir()
        name = tm.transcript_dir(repo, root=self.root).name
        build_vanilla(self.root, name=name, sid="aaaa")
        build_vanilla(self.root, name=name + "-worktree", sid="bbbb")   # shares the prefix
        self.assertEqual(self._ids(["--project", str(repo)]), ["aaaa"])
        # a value that is not a path is a substring filter over dir names
        self.assertEqual(self._ids(["--project", "my-repo"]), ["aaaa", "bbbb"])
        self.assertEqual(self._ids(["--project", "worktree"]), ["bbbb"])

    def test_project_path_with_no_transcripts_reports_zero_sessions(self):
        repo = self.base / "empty_repo"
        repo.mkdir()
        build_vanilla(self.root, sid="cccc")
        self.assertEqual(self._ids(["--project", str(repo)]), [])

    def test_since_filters_on_last_timestamp(self):
        build_vanilla(self.root, name="-a", sid="old", day="2026-09-01")
        build_vanilla(self.root, name="-b", sid="new", day="2026-10-15")
        self.assertEqual(self._ids(["--since", "2026-10-01"]), ["new"])
        self.assertEqual(self._ids([]), ["new", "old"])

    def test_usage_errors_exit_2(self):
        for argv in (["--since", "yesterday"], ["--bogus"]):
            code, _, err = run_session(["--root", str(self.root), "--out", str(self.base / "o")] + argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.strip(), argv)
        missing = self.base / "nope.json"
        code, _, err = run_session(["--root", str(self.root), "--out", str(self.base / "o"),
                                    "--window-table", str(missing)])
        self.assertEqual(code, 2)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(os.path.realpath(self.tmp.name))
        self.root = self.base / "projects"
        self.root.mkdir()
        build_vanilla(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_dispatch(self):
        out = self.base / "o"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = bench_cli.main(["session", "--root", str(self.root), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertTrue((out / "session-report.json").is_file())

    def test_usage_errors_exit_2(self):
        for argv in ([], ["bogus"], ["session", "--bogus"]):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(bench_cli.main(argv), 2, argv)
            self.assertIn("usage", err.getvalue().lower(), argv)

    def test_runs_from_a_skill_folder_without_bench_ab(self):
        skill = self.base / "harness-benchmark"
        skill.mkdir()
        for src in ("transcript_metrics.py", "bench_session.py"):
            shutil.copy(ROOT / "lib" / src, skill / src)
        shutil.copy(ROOT / "lib" / "bench_cli.py", skill / "bench.py")
        out = self.base / "o"
        ok = subprocess.run([sys.executable, "-I", str(skill / "bench.py"), "session",
                             "--root", str(self.root), "--out", str(out)],
                            capture_output=True, text=True, cwd=self.base)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue((out / "session-report.md").is_file())
        for sub in ("ab", "judge", "report"):
            r = subprocess.run([sys.executable, "-I", str(skill / "bench.py"), sub, "--run", str(out)],
                               capture_output=True, text=True, cwd=self.base)
            self.assertEqual(r.returncode, 2, sub)
            self.assertIn("bench_ab.py", r.stderr, sub)


if __name__ == "__main__":
    unittest.main()


class WindowAndPrivacyFixTests(unittest.TestCase):
    """Parent fixes after T2 review (2026-10-20)."""

    def test_current_models_have_a_one_million_window(self):
        # Context windows per the Claude API model table (cached 2026-10-06): the 5.x family and
        # Opus 4.6-4.8 / Sonnet 4.6 have 1M tokens; Haiku 4.5 has 200K.
        table = dict(bs.DEFAULT_WINDOWS)
        for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-5-5",
                      "claude-opus-4-8", "claude-opus-5"):
            self.assertEqual(bs.window_for(model, table), 1_000_000, model)
        self.assertEqual(bs.window_for("claude-haiku-4-5", table), 200_000)
        self.assertEqual(bs.window_for("claude-haiku-4-5-20251001", table), 200_000)
        self.assertIsNone(bs.window_for("gpt-x", table))

    def test_project_dir_hides_the_home_prefix(self):
        self.assertEqual(bs.display_project("-Users-someone-work-repo", home="/Users/someone"), "~-work-repo")
        self.assertEqual(bs.display_project("-Users-some-one-repo", home="/Users/some.one"), "~-repo")
        self.assertEqual(bs.display_project("-opt-builds-repo", home="/Users/someone"), "-opt-builds-repo")
