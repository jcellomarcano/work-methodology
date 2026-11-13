"""Tests for lib/bench_ab.py with a stub `claude` and stub judges (no API spend)."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import random
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import bench_ab  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
SECRET = "PLANTEDSECRETWORD"

# Answers like `claude -p --output-format json`. Writes a transcript where Claude Code would
# (CLAUDE_PROJECTS_DIR / realpath(cwd) with non-alphanumerics as "-"), with skill evidence only
# when the prompt asks for a skill that the worktree can see, and logs how it was called.
STUB_CLAUDE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys, time, uuid
args = sys.argv[1:]
prompt = args[-1]
cwd = os.path.realpath(os.getcwd())
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(json.dumps({"cwd": cwd, "claude_dir": os.path.isdir(".claude"), "mcp_json": os.path.isfile(".mcp.json"),
                         "args": args[:-1], "metodo_tools": os.environ.get("METODO_TOOLS")}) + "\n")
if "SLEEP" in prompt:
    time.sleep(30)
if "CRASH" in prompt:
    sys.exit(1)
sid = str(uuid.uuid4())
records = [{"type": "user", "message": {"content": "task"}}]
def skill(name):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": name}}]}}
if "receipt-review" in prompt and os.path.isdir(".claude"):
    records.append(skill("receipt-review"))
if "`code-review`" in prompt:
    records.append(skill("code-review"))
if not os.environ.get("STUB_NO_TRANSCRIPT"):
    d = pathlib.Path(os.environ["CLAUDE_PROJECTS_DIR"]) / re.sub(r"[^A-Za-z0-9]", "-", cwd)
    d.mkdir(parents=True, exist_ok=True)
    (d / (sid + ".jsonl")).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
if "VERDICT" in prompt:
    finding = {"id": "F1", "file": "src/a.py", "line": int(os.environ.get("STUB_LINE", "2")), "severity": "major",
               "category": "correctness", "claim": "SECRET [Measured] off by one at src/a.py:2@abcdef1 via mcp__metodo__lint",
               "evidence": "return x + 1", "fix": "drop the + 1", "label": "Measured"}
    result = "I ran nothing.\n```json\n" + json.dumps([finding]) + "\n```\nVERDICT: request-changes\nOne bug."
else:
    if "MAKE_FILE" in prompt:
        pathlib.Path("done.txt").write_text("ok\n")
    result = "Done SECRET."
print(json.dumps({"type": "result", "session_id": sid, "total_cost_usd": 0.25, "num_turns": 2, "is_error": False,
                  "duration_ms": 10, "usage": {"input_tokens": 5, "output_tokens": 7}, "result": result}))
'''.replace("SECRET", SECRET)

# A position-biased judge: everything in review A is valid, everything in B invalid.
STUB_JUDGE = r'''#!/usr/bin/env python3
import json, os, re, sys
prompt = sys.stdin.read()
with open(os.environ["JUDGE_LOG"], "a") as fh:
    fh.write(prompt + "\n=====\n")
def ids(letter):
    m = re.search(r'<review id="%s">\n(.*?)\n</review>' % letter, prompt, re.S)
    return [f["id"] for f in json.loads(m.group(1))]
mode = sys.argv[1]
if mode == "biased":
    reply = {"A": {"per_finding": {i: "valid" for i in ids("A")}},
             "B": {"per_finding": {i: "invalid" for i in ids("B")}}, "preferred": "A"}
else:
    reply = {"A": {"per_finding": {i: "valid" for i in ids("A")}},
             "B": {"per_finding": {i: "valid" for i in ids("B")}}, "preferred": "tie"}
print("Verdict below.\n```json\n" + json.dumps(reply) + "\n```")
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=dict(os.environ, **GIT_ENV)).stdout


def write_exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class Sandbox(unittest.TestCase):
    """A temp git repo with untracked kit files, a stub claude and stub judges."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self.tmp.name))
        self.repo = self.root / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "a.py").write_text("def f(x):\n    return x + 1\n")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat: a")
        self.base_sha = git(self.repo, "rev-parse", "HEAD").strip()
        (self.repo / "src" / "a.py").write_text("def f(x):\n    return x + 2\n")
        git(self.repo, "commit", "-q", "-am", "fix: a")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text("{}\n")
        (self.repo / ".mcp.json").write_text("{}\n")
        self.status_before = git(self.repo, "status", "--porcelain")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.claude = write_exe(self.bin / "claude", STUB_CLAUDE)
        self.judge = write_exe(self.bin / "judge", STUB_JUDGE)
        self.projects = self.root / "projects"
        self.log = self.root / "stub.log"
        self.judge_log = self.root / "judge.log"
        env = dict(GIT_ENV, CLAUDE_BIN=str(self.claude), CLAUDE_PROJECTS_DIR=str(self.projects),
                   STUB_LOG=str(self.log), JUDGE_LOG=str(self.judge_log))
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def config(self, **over):
        cfg = {"repo": str(self.repo), "head": "main", "model": "m", "effort": "low", "k": 1, "seed": 7,
               "timeout_s": 20, "tasks": [
                   {"id": "rev", "kind": "review", "base": self.base_sha,
                    "prompt": "Review the changes between {base} and {sha}."},
                   {"id": "chg", "kind": "change", "prompt": "MAKE_FILE please", "verify": "test -f done.txt"}],
               "judges": [{"name": "j1", "family": "fam-a", "command": [str(self.judge), "biased"]},
                          {"name": "j2", "family": "fam-a", "command": [str(self.judge), "constant"]}]}
        cfg.update(over)
        path = self.root / "ab.json"
        path.write_text(json.dumps(cfg))
        return path

    def call(self, fn, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = fn(argv)
        return rc, buf.getvalue()

    def runs(self, out):
        return [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]

    def stub_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


class AbTests(Sandbox):
    def test_dry_run_writes_nothing_and_lists_seeded_order(self):
        out = self.root / "out"
        rc, text = self.call(bench_ab.main_ab, ["--config", str(self.config(k=3)), "--preset", "kit-vs-vanilla",
                                                "--out", str(out), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(out.exists())
        self.assertEqual(self.stub_calls(), [])
        self.assertIn("planned runs: 24 (2 tasks x 4 arms x k 3)", text)
        self.assertIn("estimated cost: unknown until the first run", text)
        items = [(t, a, r) for t in ("rev", "chg") for a in ("vanilla", "kit-neutral", "kit-invoked", "native")
                 for r in range(3)]
        random.Random(7).shuffle(items)
        listed = [line.split()[1:4] for line in text.splitlines() if line.startswith("  #")]
        self.assertEqual(listed, [[t, a, str(r)] for t, a, r in items])

    def test_preset_runs_every_arm_in_a_fresh_worktree_outside_the_repo(self):
        out = self.root / "out"
        rc, _ = self.call(bench_ab.main_ab, ["--config", str(self.config()), "--preset", "kit-vs-vanilla",
                                             "--out", str(out)])
        self.assertEqual(rc, 0)
        runs = {(r["task"], r["arm"]): r for r in self.runs(out)}
        self.assertEqual(len(runs), 8)
        self.assertEqual(runs[("rev", "vanilla")]["status"], "ok")
        self.assertEqual(runs[("rev", "kit-invoked")]["status"], "ok")
        self.assertEqual(runs[("rev", "native")]["status"], "ok")
        self.assertEqual(runs[("rev", "kit-neutral")]["status"], "invalid-arm")
        self.assertEqual(runs[("rev", "kit-neutral")]["reason"], "evidence-missing")
        self.assertEqual(runs[("rev", "vanilla")]["findings_count"], 1)
        self.assertEqual(runs[("rev", "vanilla")]["verdict"], "request-changes")
        self.assertEqual(runs[("rev", "kit-invoked")]["overlay_copied"], [".claude", ".mcp.json"])
        self.assertTrue((out / "raw" / "rev" / "vanilla" / "0" / "findings.json").exists())
        calls = self.stub_calls()
        self.assertEqual(len(calls), 8)
        for call in calls:  # every run sat in a temp worktree outside the repo, now removed
            self.assertFalse(call["cwd"].startswith(str(self.repo)))
            self.assertFalse(pathlib.Path(call["cwd"]).exists())
        by_flags = {("--disable-slash-commands" in c["args"], c["claude_dir"]) for c in calls}
        self.assertNotIn((True, True), by_flags)  # a vanilla-flagged run never sees .claude/
        vanilla_calls = [c for c in calls if "--disable-slash-commands" in c["args"]]
        self.assertEqual(len(vanilla_calls), 2)
        self.assertTrue(all(c["metodo_tools"] == "/nonexistent" and not c["mcp_json"] for c in vanilla_calls))
        self.assertEqual(sum(c["claude_dir"] for c in calls), 4)  # kit-neutral and kit-invoked only
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.repo, "status", "--porcelain"), self.status_before)

    def test_worktree_is_removed_when_the_run_crashes(self):
        out = self.root / "out"
        cfg = self.config(tasks=[{"id": "c", "kind": "change", "prompt": "CRASH"}],
                          arms=[{"name": "vanilla", "prompt_template": "{task}"}])
        self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        [run] = self.runs(out)
        self.assertEqual((run["status"], run["reason"]), ("failed", "no-output"))
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertFalse(pathlib.Path(self.stub_calls()[0]["cwd"]).exists())

    def test_timeout_marks_the_run_failed(self):
        out = self.root / "out"
        cfg = self.config(timeout_s=1, tasks=[{"id": "s", "kind": "change", "prompt": "SLEEP"}],
                          arms=[{"name": "vanilla", "prompt_template": "{task}"}])
        self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        [run] = self.runs(out)
        self.assertEqual((run["status"], run["reason"]), ("failed", "timeout"))
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_verify_pass_and_fail(self):
        out = self.root / "out"
        cfg = self.config(tasks=[{"id": "yes", "kind": "change", "prompt": "MAKE_FILE", "verify": "test -f done.txt"},
                                 {"id": "no", "kind": "change", "prompt": "nothing", "verify": "test -f done.txt"}],
                          arms=[{"name": "vanilla", "prompt_template": "{task}"}])
        self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        runs = {r["task"]: r for r in self.runs(out)}
        self.assertEqual((runs["yes"]["status"], runs["yes"]["verify_passed"]), ("ok", True))
        self.assertEqual((runs["no"]["status"], runs["no"]["verify_passed"]), ("ok", False))

    def test_missing_transcript_with_an_evidence_rule_is_invalid_arm(self):
        out = self.root / "out"
        cfg = self.config(tasks=[{"id": "c", "kind": "change", "prompt": "x"}],
                          arms=[{"name": "kit", "prompt_template": "{task}", "evidence": "anything"}])
        with mock.patch.dict(os.environ, {"STUB_NO_TRANSCRIPT": "1"}):
            self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        [run] = self.runs(out)
        self.assertEqual((run["status"], run["reason"]), ("invalid-arm", "transcript-missing"))

    def test_example_config_loads(self):
        path = ROOT / "protocols" / "ab-config.example.json"
        cfg = bench_ab.load_config(path)
        self.assertEqual([t["kind"] for t in cfg["tasks"]], ["review", "change"])
        self.assertEqual([a["name"] for a in cfg["arms"]], ["vanilla", "kit-neutral"])
        self.assertEqual(cfg["arms"][1]["evidence"][:20], bench_ab.KIT_EVIDENCE[:20])
        preset = bench_ab.load_config(path, "kit-vs-vanilla")
        self.assertEqual([a["name"] for a in preset["arms"]], ["vanilla", "kit-neutral", "kit-invoked", "native"])

    def test_runs_as_a_top_level_copy_in_a_skill_folder(self):
        skill = self.root / "skill"
        skill.mkdir()
        for name in ("bench_ab.py", "transcript_metrics.py"):
            (skill / name).write_bytes((ROOT / "lib" / name).read_bytes())
        res = subprocess.run([sys.executable, "-I", str(skill / "bench_ab.py"), "ab", "--config",
                              str(self.config()), "--preset", "kit-vs-vanilla", "--dry-run"],
                             cwd=str(self.root), capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("planned runs: 8", res.stdout)

    def test_dry_run_from_inside_the_repo_without_out_is_allowed(self):
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            rc, text = self.call(bench_ab.main_ab, ["--config", str(self.config()), "--preset", "kit-vs-vanilla",
                                                    "--dry-run"])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 0)
        self.assertIn("planned runs: 8", text)
        self.assertEqual(git(self.repo, "status", "--porcelain"), self.status_before)

    def test_out_inside_the_repo_is_refused(self):
        rc, _ = self.call(bench_ab.main_ab, ["--config", str(self.config()), "--preset", "kit-vs-vanilla",
                                             "--out", str(self.repo / "bench")])
        self.assertEqual(rc, 2)
        self.assertEqual(self.stub_calls(), [])
        self.assertEqual(git(self.repo, "status", "--porcelain"), self.status_before)


class JudgeTests(Sandbox):
    def test_redaction_removes_kit_fingerprints(self):
        raw = [{"id": "X9", "file": "a.py", "line": 3, "severity": "minor", "category": "tests", "label": "Measured",
                "claim": "[Measured] see src/a.py:12@abc1234 (Inferred) via mcp__metodo__lint and generic-challenger",
                "evidence": "receipt-review said [metodo] gate", "fix": "per gentle-ai judgment-day"}]
        [norm] = bench_ab.normalize_findings(raw)
        text = json.dumps(norm)
        for mark in ("Measured", "Inferred", "@abc1234", "mcp__", "generic-", "receipt-review", "metodo",
                     "gentle-ai", "judgment-day", "label"):
            self.assertNotIn(mark, text, mark)
        self.assertEqual(norm["id"], "F1")
        self.assertIn("src/a.py:12", norm["claim"])

    def test_seeded_recall_matches_file_line_window_and_category(self):
        findings = [{"file": "src/a.py", "line": 4, "category": "correctness"},
                    {"file": "src/b.py", "line": 50, "category": "tests"}]
        seeded = [{"file": "src/a.py", "line": 2, "window": 3, "category": "correctness", "severity": "blocker"},
                  {"file": "src/a.py", "line": 2, "window": 1, "severity": "blocker"},
                  {"file": "src/b.py", "line": 50, "window": 0, "category": "security", "severity": "minor"}]
        self.assertEqual(bench_ab.match_seeded(findings, seeded),
                         {"blocker": {"found": 1, "total": 2}, "minor": {"found": 0, "total": 1}})

    def test_judge_prompt_file_matches_the_embedded_copy(self):
        path = ROOT / "protocols" / "prompts" / "judge-pairwise.txt"
        self.assertEqual(path.read_text(encoding="utf-8"), bench_ab.JUDGE_PROMPT)
        self.assertIn("Do not reward length", bench_ab.JUDGE_PROMPT)

    def test_both_orders_each_judge_and_agreement(self):
        out = self.root / "out"
        task = {"id": "rev", "kind": "review", "base": self.base_sha, "prompt": "Review {base}..{sha}.",
                "seeded": [{"file": "src/a.py", "line": 2, "window": 1, "severity": "major"}]}
        self.call(bench_ab.main_ab, ["--config", str(self.config(tasks=[task])), "--preset", "kit-vs-vanilla",
                                     "--out", str(out)])
        rc, _ = self.call(bench_ab.main_judge, ["--run", str(out)])
        self.assertEqual(rc, 0)
        result = json.loads((out / "judge.json").read_text())
        ok = [j for j in result["judgments"] if j["status"] == "ok"]
        # kit-invoked vs vanilla and native vs vanilla (kit-neutral is invalid-arm), kit-invoked vs native:
        # 3 pairs x 2 judges x 2 orders.
        self.assertEqual(len(ok), 12)
        self.assertEqual({j["order"] for j in ok}, {"AB", "BA"})
        skipped = [j for j in result["judgments"] if j["status"] != "ok"]
        self.assertEqual({tuple(j["pair"]) for j in skipped}, {("kit-neutral", "vanilla")})
        orders = {a["judge"]: a for a in result["agreement"]["between_orders"]}
        self.assertEqual(orders["j1"]["percent"], 0.0)
        self.assertEqual(orders["j1"]["kappa"], -1.0)
        self.assertEqual(orders["j1"]["preference_consistency"], 0.0)
        self.assertEqual(orders["j2"]["percent"], 1.0)
        self.assertIsNone(orders["j2"]["kappa"])
        [between] = result["agreement"]["between_judges"]
        self.assertEqual(between["percent"], 0.5)
        self.assertIn("single-family judges", result["limitations"])
        seeded = [s for s in result["seeded"] if s["arm"] == "vanilla"]
        self.assertEqual(seeded[0]["recall"], {"major": {"found": 1, "total": 1}})
        prompts = self.judge_log.read_text()
        for mark in ("mcp__", "[Measured]", "@abcdef1", '"label"'):
            self.assertNotIn(mark, prompts)
        self.assertIn("return x + 2", prompts)  # the judge sees the diff


def make_run_dir(path, tasks, arms, runs, k, seed=0, resamples=2000):
    path.mkdir(parents=True)
    cfg = {"sha": "0" * 40, "model": "m", "effort": "low", "k": k, "seed": seed, "bootstrap_resamples": resamples,
           "tasks": tasks, "arms": [{"name": a} for a in arms], "judges": []}
    (path / "config.json").write_text(json.dumps(cfg))
    (path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    return path


def run(task, arm, rep, passed=None, status="ok", cost=1.0, verdict=None, kind="change", reason=None):
    return {"task": task, "arm": arm, "rep": rep, "kind": kind, "status": status,
            "reason": None if status == "ok" else reason or "api-error", "cost_usd": cost, "verify_passed": passed,
            "verdict": verdict, "findings_count": None}


class ReportTests(Sandbox):
    def report(self, run_dir, out=None):
        argv = ["--run", str(run_dir)] + (["--out", str(out)] if out else [])
        rc, _ = self.call(bench_ab.main_report, argv)
        self.assertEqual(rc, 0)
        return json.loads(((out or run_dir) / "report.json").read_text())

    def test_pass_hat_k_flip_and_failed_runs_listed_not_averaged(self):
        tasks = [{"id": "t1", "kind": "change", "verify": "x"}, {"id": "t2", "kind": "change", "verify": "x"}]
        runs = [run("t1", "vanilla", r, True) for r in range(3)]
        runs += [run("t1", "kit", 0, True), run("t1", "kit", 1, False), run("t1", "kit", 2, True)]
        runs += [run("t2", "vanilla", r, False) for r in range(3)]
        runs += [run("t2", "kit", 0, True), run("t2", "kit", 1, True), run("t2", "kit", 2, None, "failed", 9.0)]
        rep = self.report(make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=3))
        cell = rep["arms"]["kit"]["tasks"]["t1"]
        self.assertAlmostEqual(cell["pass_at_1"]["value"], 0.666667)
        self.assertEqual(cell["pass_at_1"]["label"], "Tested")
        self.assertEqual(cell["pass_hat_k"]["value"], 0)
        self.assertEqual(cell["flip"]["value"], 1)
        self.assertEqual(rep["arms"]["vanilla"]["tasks"]["t1"]["pass_hat_k"]["value"], 1)
        self.assertEqual(rep["arms"]["vanilla"]["tasks"]["t1"]["flip"]["value"], 0)
        t2 = rep["arms"]["kit"]["tasks"]["t2"]
        self.assertEqual(t2["pass_at_1"]["value"], 1.0)  # the failed run is not averaged in
        self.assertIsNone(t2["pass_hat_k"]["value"])
        self.assertEqual((t2["pass_hat_k"]["label"], t2["pass_hat_k"]["status"]), ("Unknown", "failed"))
        # cost per solved task charges every run the arm actually paid for, failed ones included,
        # so cheap failures cannot hide (landscape report, metric row 4): (1 + 1 + 9) / 2 solved
        self.assertEqual(t2["cost_per_solved_usd"]["value"], 5.5)
        self.assertEqual(t2["spend_usd"]["value"], 11.0)
        self.assertEqual(t2["cost_per_run_usd"]["value"], 1.0)  # mean over ok runs, unchanged
        none_solved = rep["arms"]["vanilla"]["tasks"]["t2"]["cost_per_solved_usd"]
        self.assertEqual((none_solved["value"], none_solved["label"], none_solved["status"]),
                         (None, "Unknown", "not-run"))
        self.assertEqual((t2["n_excluded"], t2["n_scored"]), (1, 2))
        self.assertEqual(cell["n_excluded"], 0)
        self.assertEqual(rep["arms"]["kit"]["flip_rate"]["value"], 0.5)
        self.assertEqual(rep["excluded_runs"], [{"arm": "kit", "rep": 2, "status": "failed", "task": "t2",
                                                 "reason": "api-error"}])
        self.assertEqual(rep["signal"], "signal, not a conclusion")  # fewer than 5 tasks
        md = (self.root / "run" / "report.md").read_text()
        self.assertIn("signal, not a conclusion", md)
        self.assertIn("n tasks", md)
        self.assertIn("excluded", md)

    def test_a_timeout_is_an_outcome_not_an_exclusion(self):
        tasks = [{"id": "t1", "kind": "change", "verify": "x"}]
        runs = [run("t1", "kit", 0, True), run("t1", "kit", 1, True),
                run("t1", "kit", 2, None, "failed", None, reason="timeout")]
        rep = self.report(make_run_dir(self.root / "run", tasks, ["kit"], runs, k=3))
        cell = rep["arms"]["kit"]["tasks"]["t1"]
        self.assertEqual((cell["pass_at_1"]["value"], cell["pass_at_1"]["n"]), (0.666667, 3))
        self.assertEqual((cell["pass_hat_k"]["value"], cell["pass_hat_k"]["status"]), (0, "ok"))
        self.assertEqual(cell["flip"]["value"], 1)
        self.assertEqual((cell["n_scored"], cell["n_excluded"]), (3, 0))
        self.assertEqual(rep["excluded_runs"], [])

    def test_a_comparison_over_one_task_is_never_shown(self):
        tasks = [{"id": "t1", "kind": "change", "verify": "x"}]
        runs = [run("t1", "vanilla", r, False) for r in range(3)] + [run("t1", "kit", r, True) for r in range(3)]
        rep = self.report(make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=3))
        [p] = [c for c in rep["comparisons"] if c["metric"] == "pass_at_1"]
        self.assertEqual((p["ci95"], p["reading"]), ([1.0, 1.0], "not shown (n tasks < 2)"))

    def test_bootstrap_is_deterministic_and_not_shown_when_it_crosses_zero(self):
        diffs = [0.137, -0.291, 0.553, 0.071, -0.019, 0.402, 0.333, -0.118]
        a = bench_ab.bootstrap_ci(diffs, "s", 300)
        self.assertEqual(a, bench_ab.bootstrap_ci(diffs, "s", 300))
        self.assertNotEqual(a, bench_ab.bootstrap_ci(diffs, "other", 300))  # the seed, not luck, fixes it
        self.assertLessEqual(a[0], 0.0)
        self.assertGreaterEqual(a[1], 0.0)
        tasks = [{"id": f"t{i}", "kind": "change", "verify": "x"} for i in range(6)]
        runs = []
        for i in range(6):
            runs += [run(f"t{i}", "vanilla", r, False, cost=1.0) for r in range(2)]
            runs += [run(f"t{i}", "kit", r, True, cost=1.0 + (i % 2) * 0.2 - 0.1) for r in range(2)]
        rep = self.report(make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=2, seed=3))
        comps = {(c["metric"], c["arm"], c["baseline"]): c for c in rep["comparisons"]}
        p = comps[("pass_at_1", "kit", "vanilla")]
        self.assertEqual((p["diff"]["value"], p["n_tasks"], p["n_runs"], p["reading"]), (1.0, 6, 24, "shown"))
        c = comps[("cost_per_run_usd", "kit", "vanilla")]
        self.assertEqual(c["reading"], "not shown")
        self.assertIsNone(rep["signal"])
        again = self.report(self.root / "run", self.root / "again")
        self.assertEqual(again["comparisons"], rep["comparisons"])

    def test_signal_line_when_k_is_one(self):
        tasks = [{"id": f"t{i}", "kind": "change", "verify": "x"} for i in range(5)]
        runs = [run(f"t{i}", a, 0, True) for i in range(5) for a in ("vanilla", "kit")]
        rep = self.report(make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=1))
        self.assertEqual(rep["signal"], "signal, not a conclusion")

    def test_end_to_end_report_is_byte_identical_and_leaks_nothing(self):
        out = self.root / "out"
        self.call(bench_ab.main_ab, ["--config", str(self.config()), "--preset", "kit-vs-vanilla",
                                     "--out", str(out)])
        self.call(bench_ab.main_judge, ["--run", str(out)])
        first = self.root / "r1"
        second = self.root / "r2"
        rep = self.report(out, first)
        self.report(out, second)
        for name in ("report.json", "report.md"):
            a = (first / name).read_bytes()
            self.assertEqual(a, (second / name).read_bytes(), name)
            text = a.decode()
            self.assertNotIn(str(self.root), text)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("Review the changes", text)
        self.assertEqual(rep["tool_sha256"], bench_ab._tool_sha256())
        self.assertIn("schema_version", rep)
        self.assertEqual(rep["arms"]["kit-neutral"]["activation"]["value"], 0.0)
        self.assertEqual(rep["arms"]["kit-invoked"]["activation"]["value"], 1.0)
        self.assertEqual(rep["arms"]["vanilla"]["activation"],
                         {"value": None, "label": "Unknown", "status": "not-run", "n": 2,
                          "note": "no evidence pattern"})
        orders = {a["judge"]: a for a in rep["judges"]["agreement"]["between_orders"]}
        self.assertEqual(orders["j2"]["kappa"], {"value": None, "label": "Unknown", "status": "not-run",
                                                 "n": orders["j2"]["n"]["value"]})
        self.assertEqual(orders["j1"]["percent"]["label"], "Measured")
        self.assertEqual(orders["j1"]["n"]["status"], "ok")
        self.assertEqual(orders["j1"]["preference_consistency"]["status"], "ok")
        [between] = rep["judges"]["agreement"]["between_judges"]
        for key in ("n", "percent", "kappa"):
            self.assertEqual(set(between[key]), {"value", "label", "status", "n"}, key)
        md = (first / "report.md").read_text()
        self.assertIn("| between | metric | value | label | status | n |", md)
        self.assertNotIn("| None |", md)
        self.assertEqual(rep["arms"]["vanilla"]["tasks"]["chg"]["pass_at_1"]["value"], 1.0)
        validity = rep["arms"]["vanilla"]["tasks"]["rev"]["judge_validity"]
        self.assertEqual(validity["label"], "Inferred")  # between-judge kappa below 0.6
        self.assertIn("kit-neutral", {r["arm"] for r in rep["excluded_runs"]})


# ------------------------------------------------------------------ S12: A/B runner hardening
# (odd/tasks/benchmark-port.md). Own stubs, so the fixtures of the tests above stay as they were.

# A `claude` that never answers: it starts a child in its own process group, records both pids
# and idles in short sleeps (about 6 s at most, so nothing outlives a failing test for long).
LINGER_CLAUDE = r"""#!/usr/bin/env python3
import json, os, subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time\nfor _ in range(120):\n    time.sleep(0.05)\n"])
target = os.environ["STUB_PIDS"]
with open(target + ".tmp", "w") as fh:
    json.dump([os.getpid(), kid.pid], fh)
os.replace(target + ".tmp", target)
for _ in range(120):
    time.sleep(0.05)
"""

# A judge whose reply parses as JSON but has the wrong shape, one fault per mode.
BAD_JUDGE = r"""#!/usr/bin/env python3
import json, sys
sys.stdin.read()
replies = {"a-list": {"A": ["F1"], "B": {"per_finding": {}}, "preferred": "A"},
           "b-string": {"A": {"per_finding": {}}, "B": "valid", "preferred": "B"},
           "per-finding-list": {"A": {"per_finding": ["F1"]}, "B": {"per_finding": ["F1"]}, "preferred": "tie"}}
print("```json\n" + json.dumps(replies[sys.argv[1]]) + "\n```")
"""


def gone(pid, within=2.0):
    """True once the pid no longer exists (a killed orphan is reaped a moment after the signal)."""
    deadline = time.monotonic() + within
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


class HardeningSandbox(Sandbox):
    PLAIN_ARM = {"prompt_template": "{task}"}

    def call_err(self, fn, argv):
        """Like call, but returns (rc, stderr): the refusal line is what these tests read."""
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = fn(argv)
        return rc, err.getvalue()

    def assert_refused(self, rc, err, prefix, fragment):
        self.assertEqual(rc, 2, err)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertTrue(err.startswith(prefix), err)
        self.assertIn(fragment, err)
        self.assertNotIn("Traceback", err)

    def arms(self, *names, **extra):
        return [dict(self.PLAIN_ARM, name=n, **extra.get(n.replace("-", "_"), {})) for n in names]

    def seed_with_first(self, arm_names, first):
        """A seed whose shuffled plan starts with `first`, so a failing run has a run after it."""
        plan = {"tasks": [{"id": "c"}], "arms": [{"name": n} for n in arm_names], "k": 1}
        return next(s for s in range(64) if bench_ab.plan_runs(dict(plan, seed=s))[0]["arm"] == first)

    def report(self, run_dir):
        rc, _ = self.call(bench_ab.main_report, ["--run", str(run_dir)])
        self.assertEqual(rc, 0)
        return json.loads((run_dir / "report.json").read_text())


class ConfigValidationTests(HardeningSandbox):
    """S12 (a): a config fault is one `bench ab:` line and exit 2, before any run or any file."""

    ONE_TASK = [{"id": "c", "kind": "change", "prompt": "x"}]

    def refuse_ab(self, cfg_path, fragment):
        out = self.root / "out"
        rc, err = self.call_err(bench_ab.main_ab, ["--config", str(cfg_path), "--out", str(out)])
        self.assert_refused(rc, err, "bench ab: ", fragment)
        self.assertFalse(out.exists())
        self.assertEqual(self.stub_calls(), [])

    def test_invalid_evidence_regex_is_refused_before_any_run(self):
        cfg = self.config(tasks=self.ONE_TASK, arms=self.arms("kit", kit={"evidence": "("}))
        self.refuse_ab(cfg, "arm 'kit': evidence is not a valid regular expression")

    def test_missing_or_unreadable_prompt_file_is_refused(self):
        (self.root / "a-directory").mkdir()
        for name in ("nope.txt", "a-directory"):
            with self.subTest(prompt_file=name):
                cfg = self.config(tasks=[{"id": "c", "kind": "change", "prompt_file": name}], arms=self.arms("kit"))
                self.refuse_ab(cfg, f"task 'c': cannot read prompt_file {name!r}")

    def test_non_integer_k_max_turns_and_bootstrap_resamples_are_refused(self):
        for key, value in (("k", "three"), ("k", 2.5), ("max_turns", "many"), ("bootstrap_resamples", "lots")):
            with self.subTest(key=key, value=value):
                cfg = self.config(tasks=self.ONE_TASK, arms=self.arms("kit"), **{key: value})
                self.refuse_ab(cfg, f"{key} must be an integer, got {value!r}")

    def test_top_level_value_that_is_not_an_object_is_refused(self):
        path = self.root / "ab.json"
        path.write_text("[1, 2]")
        self.refuse_ab(path, "config must be a JSON object, got list")

    def test_judge_refuses_a_run_dir_without_its_files_or_with_unreadable_ones(self):
        rc, err = self.call_err(bench_ab.main_judge, ["--run", str(self.root / "nope")])
        self.assert_refused(rc, err, "bench judge: ", "the run dir needs runs.jsonl and config.json")
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "config.json").write_text("{")
        (broken / "runs.jsonl").write_text("")
        rc, err = self.call_err(bench_ab.main_judge, ["--run", str(broken)])
        self.assert_refused(rc, err, "bench judge: ", "cannot read config.json or runs.jsonl")
        self.assertFalse((broken / "judge.json").exists())


class RunFailureTests(HardeningSandbox):
    """S12 (b): a run that raises is recorded as failed with a fixed reason and the plan goes on."""

    TASK = [{"id": "c", "kind": "change", "prompt": "MAKE_FILE", "verify": "test -f done.txt"}]

    def run_two_arms(self, failing, arms, out=None):
        out = out or self.root / "out"
        cfg = self.config(tasks=self.TASK, arms=arms, seed=self.seed_with_first([failing, "vanilla"], failing))
        rc, text = self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        self.assertEqual(rc, 0)
        records = self.runs(out)
        self.assertEqual([r["arm"] for r in records], [failing, "vanilla"])  # the failure came first
        self.assertEqual(json.loads(text)["by_status"], {"failed": 1, "ok": 1})
        self.assertEqual((records[1]["status"], records[1]["verify_passed"]), ("ok", True))
        self.assertIn(records[0]["reason"], bench_ab.RUN_FAILURE_REASONS)
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)
        return records[0]

    @unittest.skipIf(os.geteuid() == 0, "root can read a mode-000 file")
    def test_overlay_copy_that_fails_is_recorded_and_the_next_run_goes_on(self):
        locked = self.repo / "locked.txt"
        locked.write_text("x\n")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o600)
        failed = self.run_two_arms("broken", self.arms("broken", "vanilla", broken={"overlay": ["locked.txt"]}))
        self.assertEqual((failed["status"], failed["reason"]), ("failed", "overlay-failed"))
        self.assertEqual(len(self.stub_calls()), 1)  # the broken arm never launched, so it cost nothing

    def test_raw_file_that_cannot_be_written_keeps_the_cost_and_the_next_run_goes_on(self):
        out = self.root / "out"
        (out / "raw" / "c" / "blocked" / "0" / "stdout.json").mkdir(parents=True)  # a directory where the file goes
        failed = self.run_two_arms("blocked", self.arms("blocked", "vanilla"), out)
        self.assertEqual((failed["status"], failed["reason"]), ("failed", "raw-write-failed"))
        self.assertEqual(failed["cost_usd"], 0.25)  # the run was paid: its cost is not lost with the file
        self.assertEqual(len(self.stub_calls()), 2)
        rep = self.report(out)  # scored the way the report already scores a failed run: listed, charged
        self.assertEqual(rep["arms"]["blocked"]["tasks"]["c"]["spend_usd"]["value"], 0.25)
        self.assertEqual(rep["excluded_runs"], [{"arm": "blocked", "rep": 0, "status": "failed", "task": "c",
                                                 "reason": "raw-write-failed"}])

    def test_any_other_exception_in_a_run_is_recorded_as_run_error(self):
        real, seen = bench_ab.build_prompt, []

        def flaky(cfg, task, arm):
            seen.append(arm["name"])
            if len(seen) == 1:
                raise RuntimeError("boom")
            return real(cfg, task, arm)

        with mock.patch.object(bench_ab, "build_prompt", flaky):
            failed = self.run_two_arms("odd", self.arms("odd", "vanilla"))
        self.assertEqual((failed["status"], failed["reason"]), ("failed", "run-error"))


class InterruptTests(HardeningSandbox):
    """S12 (c): an interrupt kills the child's process group before the worktree is removed."""

    def setUp(self):
        super().setUp()
        self.pid_file = self.root / "pids.json"
        self.linger = write_exe(self.bin / "linger", LINGER_CLAUDE)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_BIN": str(self.linger), "STUB_PIDS": str(self.pid_file)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.kill_leftovers)

    def kill_leftovers(self):
        if self.pid_file.exists():
            for pid in json.loads(self.pid_file.read_text()):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)

    def interrupting_popen(self):
        stub, pid_file = str(self.linger), self.pid_file

        class InterruptedPopen(subprocess.Popen):
            """communicate() on the stub raises KeyboardInterrupt once, when the stub and its child are up."""

            def communicate(self, input=None, timeout=None):
                if self.args[0] == stub and not getattr(self, "_fired", False):
                    self._fired = True
                    deadline = time.monotonic() + 2
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    raise KeyboardInterrupt
                return super().communicate(input, timeout)

        return InterruptedPopen

    def test_interrupt_kills_the_process_group_before_the_worktree_is_removed(self):
        out = self.root / "out"
        cfg = self.config(tasks=[{"id": "c", "kind": "change", "prompt": "x"}], arms=self.arms("vanilla"))
        real_git, seen = bench_ab._git, {}

        def spy(repo, *args):
            if args[:2] == ("worktree", "remove"):
                seen["gone_at_removal"] = [gone(pid) for pid in json.loads(self.pid_file.read_text())]
            return real_git(repo, *args)

        with mock.patch.object(subprocess, "Popen", self.interrupting_popen()), \
                mock.patch.object(bench_ab, "_git", spy):
            with self.assertRaises(KeyboardInterrupt):
                self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        self.assertEqual(seen.get("gone_at_removal"), [True, True])  # the stub and its own child
        self.assertEqual(git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)


class JudgeFailureTests(HardeningSandbox):
    """S12 (d): a malformed judge reply is one failed judgment; the others are kept."""

    def test_malformed_reply_is_recorded_and_the_other_judgments_are_kept(self):
        bad = write_exe(self.bin / "bad-judge", BAD_JUDGE)
        modes = ("a-list", "b-string", "per-finding-list")
        judges = [{"name": "good-before", "family": "fam-a", "command": [str(self.judge), "constant"]}]
        judges += [{"name": m, "family": "fam-b", "command": [str(bad), m]} for m in modes]
        judges += [{"name": "good-after", "family": "fam-a", "command": [str(self.judge), "constant"]}]
        task = {"id": "rev", "kind": "review", "base": self.base_sha, "prompt": "Review {base}..{sha}."}
        out = self.root / "out"
        cfg = self.config(tasks=[task], arms=self.arms("vanilla", "other"), judges=judges)
        self.call(bench_ab.main_ab, ["--config", str(cfg), "--out", str(out)])
        rc, text = self.call(bench_ab.main_judge, ["--run", str(out)])
        self.assertEqual(rc, 0)
        by_judge = {}
        for j in json.loads((out / "judge.json").read_text())["judgments"]:
            by_judge.setdefault(j["judge"], []).append((j["status"], j["reason"]))
        for name in ("good-before", "good-after"):  # both orders, before and after the bad judges
            self.assertEqual(by_judge[name], [("ok", None)] * 2, name)
        for mode in modes:
            self.assertEqual(by_judge[mode], [("failed", "malformed-reply")] * 2, mode)
        self.assertEqual((json.loads(text)["judgments"], json.loads(text)["ok"]), (10, 4))
        rep = self.report(out)  # the report builds from the judgments that were kept
        self.assertEqual(rep["arms"]["vanilla"]["tasks"]["rev"]["judge_validity"]["n"], 4)


def pass_hat_k_fixture():
    """The fixture of ReportTests.test_pass_hat_k_flip_and_failed_runs_listed_not_averaged."""
    tasks = [{"id": "t1", "kind": "change", "verify": "x"}, {"id": "t2", "kind": "change", "verify": "x"}]
    runs = [run("t1", "vanilla", r, True) for r in range(3)]
    runs += [run("t1", "kit", 0, True), run("t1", "kit", 1, False), run("t1", "kit", 2, True)]
    runs += [run("t2", "vanilla", r, False) for r in range(3)]
    runs += [run("t2", "kit", 0, True), run("t2", "kit", 1, True), run("t2", "kit", 2, None, "failed", 9.0)]
    return tasks, runs


class ReportSpendTests(HardeningSandbox):
    """S12 (e): timed-out runs with no measured cost are counted next to the spend."""

    # Keys S12 added to a report cell. Everything else must stay as it was.
    ADDED_CELL_KEYS = {"n_timed_out_no_cost"}
    # sha256 of this fixture's report before the hardening (bench_ab.py at f0c2485): report.json as
    # json.dumps(sort_keys=True) without `tool_sha256`, and report.md byte for byte.
    BASELINE_JSON = "0df1cc5aed2668e5dfd32a4d12ad18dcc2c9f2afe556d2e8edd99ec9d0cb1a35"
    BASELINE_MD = "0097c00b0f57b6a75bc792b53a9fda38d0f927628f49a4ce1714516d6651f83d"

    def test_timed_out_runs_without_a_cost_are_counted_next_to_the_spend(self):
        tasks = [{"id": "t1", "kind": "change", "verify": "x"}]
        runs = [run("t1", "kit", 0, True), run("t1", "kit", 1, None, "failed", None, reason="timeout"),
                run("t1", "kit", 2, None, "failed", None, reason="timeout"),
                run("t1", "vanilla", 0, True), run("t1", "vanilla", 1, True),
                run("t1", "vanilla", 2, None, "failed", 0.5, reason="timeout")]
        run_dir = make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=3)
        rep = self.report(run_dir)
        kit, vanilla = (rep["arms"][a]["tasks"]["t1"] for a in ("kit", "vanilla"))
        self.assertEqual((kit["spend_usd"]["value"], kit["n_timed_out_no_cost"]), (1.0, 2))
        # a timed-out run that did report a cost is already in the spend, so it is not counted
        self.assertEqual((vanilla["spend_usd"]["value"], vanilla["n_timed_out_no_cost"]), (2.5, 0))
        rows = {line.split(" | ")[0]: line for line in (run_dir / "report.md").read_text().splitlines()
                if " | t1 | " in line}
        self.assertIn("| 1.0 [Measured] (+2 timed out, cost not measured) |", rows["| kit"])
        self.assertNotIn("cost not measured", rows["| vanilla"])

    def test_report_from_the_existing_fixture_is_unchanged_apart_from_added_keys(self):
        def strip(node):
            if isinstance(node, dict):
                return {k: strip(v) for k, v in node.items() if k not in self.ADDED_CELL_KEYS}
            return [strip(v) for v in node] if isinstance(node, list) else node

        tasks, runs = pass_hat_k_fixture()
        run_dir = make_run_dir(self.root / "run", tasks, ["vanilla", "kit"], runs, k=3)
        rep = self.report(run_dir)
        rep.pop("tool_sha256")  # the hash of bench_ab.py itself changes with every edit of the tool
        self.assertEqual(hashlib.sha256(json.dumps(strip(rep), sort_keys=True).encode()).hexdigest(),
                         self.BASELINE_JSON)
        self.assertEqual(hashlib.sha256((run_dir / "report.md").read_bytes()).hexdigest(), self.BASELINE_MD)



if __name__ == "__main__":
    unittest.main()
