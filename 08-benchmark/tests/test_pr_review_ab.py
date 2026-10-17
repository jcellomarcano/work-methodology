"""Tests for bin/pr-review-ab.sh using a stub `claude` binary (no API spend)."""
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "pr-review-ab.sh"

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

# The stub answers like `claude -p --output-format json`: a review when the prompt
# asks for findings, a judgement when it asks to judge. It also records how it was
# called so the test can check the arm flags.
STUB = r'''#!/usr/bin/env bash
log="$STUB_LOG"
printf '%s\n' "$*" >> "$log"
printf 'METODO_TOOLS=%s\n' "${METODO_TOOLS:-unset}" >> "$log"
prompt="${@: -1}"
if [[ "$prompt" == *"judging two code reviews"* ]]; then
  printf '%s\n' "JUDGE_SAW_METODO=$([[ "$prompt" == *metodo* || "$prompt" == *mcp__* ]] && echo yes || echo no)" >> "$log"
  result='Here. ```json\n{"A": {"valid": 1, "invalid": 0, "unverifiable": 0, "per_finding": {"F1": "valid"}}, "B": {"valid": 0, "invalid": 1, "unverifiable": 0, "per_finding": {"F1": "invalid"}}, "missed_by_both": [], "clearer": "A", "clearer_why": "x", "preferred": "A", "preferred_why": "y"}\n```'
elif [[ "${STUB_BREAK_ARM:-}" == "yes" && -z "${METODO_TOOLS:-}" ]]; then
  result='I could not produce findings.'
else
  result='I ran nothing. ```json\n[{"id": "F1", "file": "src/A.kt", "line": 1, "severity": "minor", "category": "readability", "claim": "c", "evidence": "class A // via mcp__metodo__lint and [metodo] gate", "fix": "f", "label": "Inferred"}]\n```\nVERDICT: approve\nFine.'
fi
python3 -c 'import json,sys,uuid; print(json.dumps({"type":"result","session_id":str(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1][:20])),"total_cost_usd":0.5,"duration_ms":1200,"duration_api_ms":1000,"num_turns":3,"is_error":False,"usage":{"input_tokens":10,"cache_read_input_tokens":200,"cache_creation_input_tokens":300,"output_tokens":40},"result":sys.argv[1].replace("\\n","\n")}))' "$result"
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, env=ENV, capture_output=True, text=True).stdout.strip()


class PrReviewAbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "A.kt").write_text("class A\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat: a")
        git(self.repo, "switch", "-q", "-c", "feat/b")
        (self.repo / "src" / "B.kt").write_text("class B\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat: b")
        self.bin = root / "bin"
        self.bin.mkdir()
        stub = self.bin / "claude"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.out = root / "ab"
        self.log = root / "stub.log"
        self.runs = root / "ab-runs.jsonl"
        self.env = dict(ENV, CLAUDE_BIN=str(stub), AB_OUT_DIR=str(self.out), AB_RUNS_FILE=str(self.runs),
                        STUB_LOG=str(self.log))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return subprocess.run(["bash", str(SCRIPT), str(self.repo), "42", "feat/b", "claude-opus-5-5", "medium"],
                              env=self.env, capture_output=True, text=True)

    def test_runs_both_arms_and_judge(self):
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        out = self.out / "42"
        for name in ("kit.raw.json", "vanilla.raw.json", "kit.review.json", "vanilla.review.json",
                     "judge.raw.json", "judge.json", "judge.mapping.json", "diff.patch"):
            self.assertTrue((out / name).exists(), name)
        review = json.loads((out / "kit.review.json").read_text())
        self.assertEqual(review[0]["id"], "F1")
        summary = json.loads((out / "kit.summary.json").read_text())
        self.assertEqual(summary["findings"], 1)
        self.assertEqual(summary["verdict"], "approve")
        self.assertEqual(summary["cost_usd"], 0.5)
        mapping = json.loads((out / "judge.mapping.json").read_text())
        self.assertEqual({mapping["A"], mapping["B"]}, {"kit", "vanilla"})
        self.assertIn("preferred:", res.stdout)
        self.assertIn(mapping["A"], res.stdout.split("preferred:")[1])

    def test_arm_flags_differ_only_by_kit_switches(self):
        self._run()
        log = self.log.read_text()
        calls = [ln for ln in log.splitlines() if ln.startswith("-p ")]
        self.assertEqual(len(calls), 3)  # two arms + judge
        arms = [c for c in calls if "judging" not in c]
        vanilla = [c for c in arms if "--disable-slash-commands" in c]
        kit = [c for c in arms if "--disable-slash-commands" not in c]
        self.assertEqual(len(vanilla), 1)
        self.assertEqual(len(kit), 1)
        self.assertIn("--strict-mcp-config", vanilla[0])
        for c in arms:
            self.assertIn("--model claude-opus-5-5", c)
            self.assertIn("--effort medium", c)
            self.assertIn("--permission-prompts none", c)
        env_lines = [ln for ln in log.splitlines() if ln.startswith("METODO_TOOLS=")]
        self.assertEqual(env_lines.count("METODO_TOOLS=/nonexistent"), 2)  # vanilla arm + judge
        self.assertEqual(env_lines.count("METODO_TOOLS=unset"), 1)  # kit arm
        self.assertEqual(sum(1 for ln in log.splitlines() if ln.startswith("-p ") and "--no-session-persistence" in ln), 0)

    def test_judge_never_sees_kit_markers(self):
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("JUDGE_SAW_METODO=no", self.log.read_text())
        stored = (self.out / "42" / "kit.review.json").read_text()
        self.assertIn("mcp__metodo__lint", stored)  # the stored review is untouched
        blind = (self.out / "42" / "kit.review.blind.json").read_text()
        self.assertNotIn("metodo", blind)
        self.assertIn("[tool]", blind)

    def test_failed_arm_marks_cell_and_skips_judge(self):
        self.env["STUB_BREAK_ARM"] = "yes"  # the kit arm (METODO_TOOLS unset) answers without a JSON block
        res = self._run()
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("arm kit failed", res.stderr)
        out = self.out / "42"
        self.assertEqual(json.loads((out / "kit.summary.json").read_text())["status"], "failed")
        self.assertEqual(json.loads((out / "judge.summary.json").read_text()), {"status": "failed", "failed_arm": "kit"})
        self.assertFalse((out / "judge.raw.json").exists())
        self.assertNotIn("JUDGE_SAW_METODO", self.log.read_text())

    def _fake_transcript(self, with_kit: bool):
        # the stub derives the session id from the first 20 chars of the result text, so it is stable
        res = subprocess.run([str(self.bin / "claude"), "-p", "x", "probe"], env=dict(self.env, STUB_LOG=str(self.log)),
                             capture_output=True, text=True)
        sid = json.loads(res.stdout)["session_id"]
        projects = pathlib.Path(self.tmp.name) / "projects"
        d = projects / str(self.repo).replace("/", "-")
        d.mkdir(parents=True, exist_ok=True)
        line = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Agent","input":{"subagent_type":"generic-judge"}}]}}' if with_kit \
            else '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"git diff"}}]}}'
        (d / f"{sid}.jsonl").write_text(line + "\n")
        self.env["CLAUDE_PROJECTS_DIR"] = str(projects)

    def test_kit_arm_without_kit_evidence_is_invalid(self):
        self._fake_transcript(with_kit=False)
        res = self._run()
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertIn("arm kit invalid", res.stderr)
        self.assertEqual(json.loads((self.out / "42" / "judge.summary.json").read_text())["status"], "invalid-arm")
        self.assertEqual(json.loads((self.out / "42" / "kit.summary.json").read_text())["kit_evidence_hits"], 0)
        self.assertFalse((self.out / "42" / "judge.raw.json").exists())

    def test_comparator_evidence_pattern_override(self):
        self._fake_transcript(with_kit=False)  # transcript shows a plain Bash call only
        self.env["AB_ARM_EVIDENCE"] = '"name":"Bash"'
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads((self.out / "42" / "kit.summary.json").read_text())["kit_evidence_hits"], 1)

    def test_kit_arm_with_kit_evidence_is_scored(self):
        self._fake_transcript(with_kit=True)
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads((self.out / "42" / "kit.summary.json").read_text())["kit_evidence_hits"], 1)
        self.assertTrue((self.out / "42" / "judge.raw.json").exists())

    def test_refuses_when_tree_is_not_at_pr_head(self):
        git(self.repo, "switch", "-q", "main")
        res = self._run()
        self.assertEqual(res.returncode, 4)
        self.assertIn("not checked out at", res.stderr)
        git(self.repo, "switch", "-q", "feat/b")
        (self.repo / "src" / "A.kt").write_text("class A { }\n")
        res = self._run()
        self.assertEqual(res.returncode, 4)
        self.assertIn("uncommitted tracked changes", res.stderr)

    def test_runs_ledger_has_both_arms(self):
        self._run()
        lines = [json.loads(ln) for ln in self.runs.read_text().splitlines()]
        self.assertEqual(sorted(x["arm"] for x in lines), ["kit", "vanilla"])
        self.assertEqual(lines[-1]["effort"], "medium")
        self.assertEqual(lines[-1]["pr"], "42")
        self.assertFalse((ROOT / "data" / "ab-runs.jsonl").exists() and '"pr": "42"' in (ROOT / "data" / "ab-runs.jsonl").read_text())
        self.assertEqual({x["prompt"] for x in lines}, {"arm.txt"})

    def _baseline(self):
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        base = pathlib.Path(self.tmp.name) / "baseline"
        (self.out / "42").rename(base)
        self.log.write_text("")
        return base

    def test_custom_kit_prompt_with_reused_vanilla(self):
        base = self._baseline()
        tpl = pathlib.Path(self.tmp.name) / "skill.txt"
        tpl.write_text("Invoke the code-review skill on <BASE>...<SHA> first.\n\n<CONTRACT>")
        self.env.update(AB_ARM_PROMPT=str(tpl), AB_REUSE_VANILLA=str(base))
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        calls = [ln for ln in self.log.read_text().splitlines() if ln.startswith("-p ")]
        self.assertEqual(len(calls), 2)  # the kit arm and the judge; vanilla is not re-run
        self.assertIn("Invoke the code-review skill on", calls[0])
        log = self.log.read_text()  # the stub logs multi-line prompts across lines
        self.assertIn("Deliver two things", log)  # the shared output contract is spliced in
        self.assertNotIn("<CONTRACT>", log)
        out = self.out / "42"
        self.assertEqual((out / "vanilla.review.json").read_text(), (base / "vanilla.review.json").read_text())
        rows = [json.loads(ln) for ln in self.runs.read_text().splitlines()]
        self.assertEqual(rows[-1]["prompt"], "skill.txt")
        self.assertEqual(sum(1 for r in rows if r["arm"] == "vanilla"), 1)  # the reused arm adds no ledger row

    def test_reuse_refuses_a_baseline_from_another_diff(self):
        base = self._baseline()
        (base / "diff.patch").write_text("something else\n")
        self.env["AB_REUSE_VANILLA"] = str(base)
        res = self._run()
        self.assertEqual(res.returncode, 4)
        self.assertIn("different diff", res.stderr)


if __name__ == "__main__":
    unittest.main()
