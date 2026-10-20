"""T3 (WU7): SessionStart(compact|resume) restores a short goal anchor (task
document, its open task ids with their S#, the last receipt state for the
current tree) as additionalContext; startup and clear keep today's status
lines only. The hook runs as a subprocess over a temporary git repo."""
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

## Specs

- **S1 One.** text
- **S2 Two.** text

## Tasks (smallest first)

| ID | Specs | Work | Status | Evidence |
|---|---|---|---|---|
| T1 | S1 | first | done | RED/GREEN |
| T2 | S1 | second | todo | |
| T3 | S1, S2 | third | in progress | |
| T4 | S2 | fourth | done, commit pending | ok |

## Log

| T9 | S9 | not a task row | todo | |
"""

ALL_DONE = """# Feature: closed

## Tasks

| ID | Specs | Work | Status | Evidence |
|---|---|---|---|---|
| T1 | S1 | only | done | ok |
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


class SessionStartAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="session-start-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.tree = _git(self.repo, "rev-parse", "HEAD^{tree}")
        self.tasks = self.repo / "odd" / "tasks"
        self.tasks.mkdir(parents=True)
        self.hooks_dir = self.tmp / "hooks-out"
        self.rdd_dir = self.tmp / "rdd"
        self.config_path = self.tmp / "project.json"
        self.set_config()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_config(self, enabled=True, memory=None):
        config = {"rdd": {"enabled": enabled, "mode": "warn"}}
        if memory is not None:
            config["memory"] = memory
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def write_doc(self, name: str, text: str, mtime: int = 1_700_000_000) -> Path:
        path = self.tasks / name
        path.write_text(text, encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def write_receipt(self, state="reviewing", verdict=None):
        self.rdd_dir.mkdir(exist_ok=True)
        receipt = {"tree_sha": self.tree, "state": state, "verdict": verdict, "round_dir": "~/round",
                   "risk": {"tier": "medium", "consent": "n/a"}}
        (self.rdd_dir / f"{self.tree}.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    def run_hook(self, source: str) -> subprocess.CompletedProcess:
        payload = {"session_id": "s1", "cwd": str(self.repo), "hook_event_name": "SessionStart", "source": source}
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_path),
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.rdd_dir), CLAUDE_PROJECT_DIR=str(self.repo))
        proc = subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def context(self, proc) -> str:
        out = json.loads(proc.stdout)
        specific = out["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        return specific["additionalContext"]

    def anchor_line(self, context: str) -> str:
        lines = [line for line in context.splitlines() if "goal anchor" in line]
        self.assertEqual(len(lines), 1, context)
        return lines[0]

    def test_compact_injects_the_anchor_with_open_ids_and_specs(self):
        self.write_doc("demo.md", TASK_DOC)
        self.write_receipt(state="reviewing")
        context = self.context(self.run_hook("compact"))
        anchor = self.anchor_line(context)
        self.assertIn("odd/tasks/demo.md", anchor)
        self.assertIn("T2 (S1)", anchor)
        self.assertIn("T3 (S1, S2)", anchor)
        self.assertIn("state=reviewing", anchor)
        self.assertIn(self.tree[:12], anchor)
        # done rows and rows after the Tasks table are not open work
        for closed in ("T1", "T4", "T9"):
            self.assertNotIn(closed, anchor)
        # today's status lines stay in the same context
        self.assertIn("[metodo] RDD warn mode", context)

    def test_resume_injects_the_same_anchor(self):
        self.write_doc("demo.md", TASK_DOC)
        compact = self.anchor_line(self.context(self.run_hook("compact")))
        resume = self.anchor_line(self.context(self.run_hook("resume")))
        self.assertEqual(compact, resume)

    def test_anchor_without_a_receipt_says_none_for_the_tree(self):
        self.write_doc("demo.md", TASK_DOC)
        anchor = self.anchor_line(self.context(self.run_hook("compact")))
        self.assertIn(f"last receipt: none for tree {self.tree[:12]}", anchor)

    def test_startup_and_clear_print_no_anchor(self):
        self.write_doc("demo.md", TASK_DOC)
        for source in ("startup", "clear"):
            proc = self.run_hook(source)
            self.assertNotIn("goal anchor", proc.stdout, source)
            self.assertIn("[metodo] RDD warn mode", proc.stdout, source)

    def test_anchor_is_capped_at_120_tokens_and_deterministic(self):
        rows = "".join(f"| T{i} | S{i}, S{i + 1} | work {i} | todo | |\n" for i in range(1, 80))
        self.write_doc("big-feature-with-a-long-name.md",
                       "# Feature\n\n## Tasks\n\n| ID | Specs | Work | Status | Evidence |\n|---|---|---|---|---|\n" + rows)
        self.write_receipt(state="reviewing")
        first = self.anchor_line(self.context(self.run_hook("compact")))
        second = self.anchor_line(self.context(self.run_hook("compact")))
        self.assertEqual(first, second)
        self.assertLessEqual(_tokens(first), 120, first)
        self.assertIn("T1 (S1, S2)", first)
        self.assertIn("more", first)
        self.assertIn("state=reviewing", first)

    def test_pipes_inside_code_spans_do_not_split_cells(self):
        # the live task doc writes `delegate: subagent|main` in a Work cell of a done row
        doc = TASK_DOC.replace("| T4 | S2 | fourth | done, commit pending | ok |",
                               "| T4 | S2 | per entry `delegate: subagent|main` and `a|b` | done, commit pending | ok |")
        doc = doc.replace("| T2 | S1 | second | todo | |", "| T2 | S1 | escaped \\| pipe | todo | |")
        self.write_doc("demo.md", doc)
        anchor = self.anchor_line(self.context(self.run_hook("compact")))
        self.assertNotIn("T4", anchor)
        self.assertIn("T2 (S1), T3 (S1, S2);", anchor)

    def test_no_task_doc_adds_nothing(self):
        proc = self.run_hook("compact")
        self.assertNotIn("goal anchor", proc.stdout)
        self.assertIn("[metodo] RDD warn mode", proc.stdout)

    def test_a_doc_with_every_row_done_is_not_active(self):
        self.write_doc("closed.md", ALL_DONE)
        proc = self.run_hook("compact")
        self.assertNotIn("goal anchor", proc.stdout)

    def test_latest_modified_open_doc_wins(self):
        self.write_doc("older.md", TASK_DOC, mtime=1_700_000_000)
        self.write_doc("newer.md", TASK_DOC.replace("T2 | S1 | second", "T5 | S2 | fifth"), mtime=1_700_000_500)
        # a newer doc with nothing open does not take the anchor
        self.write_doc("closed.md", ALL_DONE, mtime=1_700_000_900)
        anchor = self.anchor_line(self.context(self.run_hook("compact")))
        self.assertIn("odd/tasks/newer.md", anchor)
        self.assertIn("T5 (S2)", anchor)

    def test_config_active_task_doc_wins_over_the_scan(self):
        self.write_doc("newer.md", TASK_DOC, mtime=1_700_000_900)
        self.write_doc("chosen.md", TASK_DOC.replace("T2 | S1 | second", "T6 | S2 | sixth"), mtime=1_700_000_000)
        self.set_config(memory={"active_task_doc": "odd/tasks/chosen.md"})
        anchor = self.anchor_line(self.context(self.run_hook("compact")))
        self.assertIn("odd/tasks/chosen.md", anchor)
        self.assertIn("T6 (S2)", anchor)

    def test_config_path_outside_the_repo_is_never_read(self):
        outside = self.tmp / "outside.md"
        outside.write_text(TASK_DOC.replace("T2 | S1 | second", "T8 | S2 | secret"), encoding="utf-8")
        self.write_doc("demo.md", TASK_DOC)
        for value in ("../outside.md", str(outside)):
            self.set_config(memory={"active_task_doc": value})
            anchor = self.anchor_line(self.context(self.run_hook("compact")))
            self.assertNotIn("T8", anchor, value)
            self.assertIn("odd/tasks/demo.md", anchor, value)

    def test_silent_when_rdd_is_off(self):
        self.set_config(enabled=False)
        self.write_doc("demo.md", TASK_DOC)
        self.assertEqual(self.run_hook("compact").stdout, "")


if __name__ == "__main__":
    unittest.main()
