"""SessionStart reads memory back by reference: on a non-trunk branch, with
memory on, the hook prints up to three `[metodo] memory: #id (kind) title`
pointers for the branch's subject, never a body. Off, on a trunk branch or
on any engram failure it prints none and the status lines stay as they were.

The hook runs as a subprocess over a temporary git repo. `engram` is a stub
script on a temporary PATH: this test never reaches the real engram store."""
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOK = TOOLS_ROOT / "hooks" / "session_start_status.py"

TASK_DOC = """# Feature: demo

## Tasks

| ID | Specs | Work | Status | Evidence |
|---|---|---|---|---|
| T1 | S1 | first | todo | |
"""

ONE_MEMORY = ["[1] #42 (decision) — Refund guard chosen", "    body that must not print",
              "    2026-11-11 20:42:38 | project: payments | scope: project"]
FIVE_MEMORIES = [f"[{i}] #{100 + i} (discovery) — Finding {i}" for i in range(1, 6)]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


class SessionStartMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="session-start-memory-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.hooks_dir = self.tmp / "hooks-out"
        self.rdd_dir = self.tmp / "rdd"
        self.config_path = self.tmp / "project.json"
        self.set_config()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.args_file = self.bin / "engram.args"
        self.stub(ONE_MEMORY)

    def set_config(self, rdd=True, memory=True):
        self.config_path.write_text(json.dumps({
            "rdd": {"enabled": rdd, "mode": "warn"},
            "memory": {"enabled": memory, "engram_project": "payments"},
        }), encoding="utf-8")

    def stub(self, lines: list[str], exit_code: int = 0):
        """A fake `engram`: records its arguments, prints `lines`, exits `exit_code`."""
        (self.bin / "engram.out").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        engram = self.bin / "engram"
        engram.write_text(f'#!/bin/sh\necho "$@" > "$0.args"\ncat "$0.out"\nexit {exit_code}\n', encoding="utf-8")
        engram.chmod(0o755)

    def branch(self, name: str):
        _git(self.repo, "checkout", "-q", "-b", name)

    def run_hook(self, source="startup", memory_switch="on") -> subprocess.CompletedProcess:
        payload = {"session_id": "s1", "cwd": str(self.repo), "hook_event_name": "SessionStart", "source": source}
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_path),
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.rdd_dir),
                   CLAUDE_PROJECT_DIR=str(self.repo), METODO_MEMORY=memory_switch,
                   PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        env.pop("ENGRAM_PROJECT", None)
        proc = subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return proc

    def memory_lines(self, text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("[metodo] memory:")]

    def test_a_feature_branch_points_at_memory_by_reference(self):
        self.branch("feat/refund-guard")
        proc = self.run_hook()
        self.assertEqual(self.memory_lines(proc.stdout), ["[metodo] memory: #42 (decision) Refund guard chosen"])
        self.assertNotIn("body that must not print", proc.stdout)
        # the branch's subject is the query, scoped to the configured project and to three pointers
        self.assertEqual(self.args_file.read_text(encoding="utf-8").strip(),
                         "search refund guard --project payments --limit 3 --match any")
        # the status lines the hook already printed are still there, in the same order
        lines = proc.stdout.splitlines()
        self.assertTrue(lines[0].startswith("[metodo] RDD warn mode; tree "), lines)
        self.assertTrue(lines[-2].startswith("[metodo] ledger: "), lines)

    def test_at_most_three_pointers_and_ten_lines(self):
        self.branch("fix/ledger_rounding")
        self.stub(FIVE_MEMORIES)
        proc = self.run_hook()
        self.assertEqual(self.memory_lines(proc.stdout),
                         [f"[metodo] memory: #{100 + i} (discovery) Finding {i}" for i in (1, 2, 3)])
        self.assertLessEqual(len(proc.stdout.splitlines()), 10)
        self.assertIn("search ledger rounding ", self.args_file.read_text(encoding="utf-8"))

    def test_a_long_title_is_cut_to_the_pointer_budget(self):
        self.branch("feat/refund-guard")
        self.stub([f"[1] #7 (decision) — {'very long title ' * 40}"])
        first = self.memory_lines(self.run_hook().stdout)
        self.assertEqual(len(first), 1)
        self.assertLessEqual(_tokens(first[0]), 30, first[0])
        self.assertTrue(first[0].startswith("[metodo] memory: #7 (decision) very long title"), first[0])
        self.assertTrue(first[0].endswith("…"), first[0])
        self.assertEqual(first, self.memory_lines(self.run_hook().stdout))

    def test_a_trunk_branch_or_a_detached_head_asks_nothing(self):
        proc = self.run_hook()  # main
        self.assertEqual(self.memory_lines(proc.stdout), [])
        self.assertIn("[metodo] RDD warn mode", proc.stdout)
        _git(self.repo, "checkout", "-q", "--detach")
        self.assertEqual(self.memory_lines(self.run_hook().stdout), [])
        self.assertFalse(self.args_file.exists())

    def test_memory_off_prints_no_pointer_and_never_calls_engram(self):
        self.branch("feat/refund-guard")
        self.assertEqual(self.memory_lines(self.run_hook(memory_switch="off").stdout), [])
        self.set_config(memory=False)
        proc = self.run_hook()
        self.assertEqual(self.memory_lines(proc.stdout), [])
        self.assertIn("[metodo] RDD warn mode", proc.stdout)
        self.set_config(rdd=False)
        self.assertEqual(self.run_hook().stdout, "")
        self.assertFalse(self.args_file.exists())

    def test_an_engram_failure_leaves_the_status_lines_alone(self):
        self.branch("feat/refund-guard")
        self.stub(ONE_MEMORY, exit_code=1)
        proc = self.run_hook()
        self.assertEqual(self.memory_lines(proc.stdout), [])
        self.assertIn("[metodo] RDD warn mode", proc.stdout)
        self.assertIn("[metodo] ledger: ", proc.stdout)
        self.assertTrue(self.args_file.exists())  # negative control: engram was reached and its failure swallowed

    def test_compact_carries_the_pointers_next_to_the_goal_anchor(self):
        self.branch("feat/refund-guard")
        self.stub(FIVE_MEMORIES)
        tasks = self.repo / "odd" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "demo.md").write_text(TASK_DOC, encoding="utf-8")
        specific = json.loads(self.run_hook(source="compact").stdout)["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        lines = specific["additionalContext"].splitlines()
        self.assertEqual(len(self.memory_lines(specific["additionalContext"])), 3)
        self.assertLessEqual(len(lines), 10)
        self.assertTrue(lines[-1].startswith("[metodo] goal anchor: odd/tasks/demo.md; open: T1 (S1);"), lines)


if __name__ == "__main__":
    unittest.main()
