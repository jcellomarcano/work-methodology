"""Tests for lib/bench_ab.py with a stub `claude` and stub judges (no API spend)."""
import contextlib
import io
import json
import os
import pathlib
import random
import stat
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
