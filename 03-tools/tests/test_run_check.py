"""bin/run-check.sh + lib/run_check.py (WU15, context-method §6): a check
command runs unchanged, its exit code passes through, and one deterministic
line lands in <runs>/runs.jsonl (never in a tracked path of the target
repo), with the combined output in <runs>/<seq>.log and its sha256 in the
record. No wall clock: "after the last edit" is the worktree fingerprint."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import run_check

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = TOOLS_ROOT / "lib" / "run_check.py"
WRAPPER = TOOLS_ROOT / "bin" / "run-check.sh"
RECORD_KEYS = ["argv", "cwd", "dirty", "elapsed_ms", "exit", "head_sha", "log", "name", "output_sha256", "repo",
               "schema_version", "seq", "tree_sha", "worktree_sha"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class RunCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run-check-"))
        self.repo = self.tmp / "repo"
        (self.repo / "sub").mkdir(parents=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.runs = self.tmp / "runs"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args, cwd=None, runs=None, via=None):
        argv = (["bash", str(WRAPPER)] if via == "sh" else ["python3", str(SCRIPT)]) + list(args[:1]) \
            + ["--runs-dir", str(runs or self.runs)] + list(args[1:])
        return subprocess.run(argv, cwd=str(cwd or self.repo), capture_output=True, text=True, timeout=60)

    def _records(self, runs=None):
        path = (runs or self.runs) / "runs.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_records_one_line_with_fixed_keys_and_output_hash(self):
        proc = self._run("unit", "--", "python3", "-c", "import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("out", proc.stdout)  # the output still reaches the caller
        [record] = self._records()
        self.assertEqual(sorted(record), RECORD_KEYS)
        self.assertEqual(record["name"], "unit")
        self.assertEqual(record["argv"], ["python3", "-c", "import sys; print('out'); print('err', file=sys.stderr)"])
        self.assertEqual((record["exit"], record["cwd"], record["seq"], record["dirty"]), (0, ".", 1, False))
        self.assertEqual(record["head_sha"], _git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(record["tree_sha"], _git(self.repo, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(record["repo"], str(self.repo.resolve()))  # A-005: a run is bound to its repo
        log = self.runs / record["log"]
        self.assertEqual(record["log"], "1.log")
        data = log.read_bytes()
        self.assertIn(b"out", data)
        self.assertIn(b"err", data)
        self.assertEqual(record["output_sha256"], hashlib.sha256(data).hexdigest())
        self.assertIsInstance(record["elapsed_ms"], int)

    def test_exit_code_passes_through_unchanged(self):
        for code in (0, 1, 3, 42):
            with self.subTest(code=code):
                proc = self._run("unit", "--", "python3", "-c", f"raise SystemExit({code})")
                self.assertEqual(proc.returncode, code)
                self.assertEqual(self._records()[-1]["exit"], code)
        self.assertEqual([r["seq"] for r in self._records()], [1, 2, 3, 4])

    def test_wrapper_passes_the_exit_code_and_records(self):
        proc = self._run("unit", "--", "python3", "-c", "raise SystemExit(5)", via="sh")
        self.assertEqual(proc.returncode, 5, proc.stderr)
        self.assertEqual(self._records()[-1]["exit"], 5)

    def test_missing_command_is_recorded_as_127(self):
        proc = self._run("unit", "--", "no-such-command-xyz")
        self.assertEqual(proc.returncode, 127)
        self.assertEqual(self._records()[-1]["exit"], 127)

    def test_cwd_is_relative_to_the_repo(self):
        self._run("unit", "--", "true", cwd=self.repo / "sub")
        self.assertEqual(self._records()[-1]["cwd"], "sub")

    def test_dirty_and_worktree_fingerprint_follow_edits(self):
        clean = run_check.worktree_fingerprint(self.repo)
        self.assertEqual(clean, run_check.worktree_fingerprint(self.repo))  # deterministic
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        edited = run_check.worktree_fingerprint(self.repo)
        self.assertNotEqual(clean["worktree_sha"], edited["worktree_sha"])
        self.assertTrue(edited["dirty"])
        self.assertEqual(clean["tree_sha"], edited["tree_sha"])  # HEAD tree alone cannot see the edit
        (self.repo / "new.txt").write_text("n\n", encoding="utf-8")
        self.assertNotEqual(edited["worktree_sha"], run_check.worktree_fingerprint(self.repo)["worktree_sha"])
        (self.repo / "ignored").mkdir()
        (self.repo / "ignored" / "x").write_text("i\n", encoding="utf-8")
        after_new = run_check.worktree_fingerprint(self.repo)
        (self.repo / "ignored" / "x").write_text("changed\n", encoding="utf-8")
        self.assertEqual(after_new, run_check.worktree_fingerprint(self.repo))  # ignored files never count
        self._run("unit", "--", "true")
        record = self._records()[-1]
        self.assertTrue(record["dirty"])
        self.assertEqual(record["worktree_sha"], after_new["worktree_sha"])

    def test_worktree_sha_is_the_tested_content_and_survives_a_commit_of_the_same_bytes(self):
        # B-003: "run tests, then commit" keeps the green proof; HEAD's tree stays tree_sha
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "u.py").write_text("u = 1\n", encoding="utf-8")
        staged = _git(self.repo, "ls-files", "--stage")
        dirty = run_check.worktree_fingerprint(self.repo)
        # the real index never gains the overlay (git status may still refresh its stat cache)
        self.assertEqual(_git(self.repo, "ls-files", "--stage"), staged)
        (self.repo / "u.py").unlink()
        dirty = run_check.worktree_fingerprint(self.repo)
        _git(self.repo, "commit", "-q", "-am", "same bytes")
        committed = run_check.worktree_fingerprint(self.repo)
        self.assertEqual(dirty["worktree_sha"], committed["worktree_sha"])
        self.assertFalse(committed["dirty"])
        self.assertEqual(committed["tree_sha"], _git(self.repo, "rev-parse", "HEAD^{tree}"))
        self.assertNotEqual(dirty["tree_sha"], committed["tree_sha"])
        (self.repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        edited = run_check.worktree_fingerprint(self.repo)
        self.assertNotEqual(edited["worktree_sha"], committed["worktree_sha"])  # an edit changes it
        (self.repo / "new.py").write_text("y = 1\n", encoding="utf-8")
        untracked = run_check.worktree_fingerprint(self.repo)
        self.assertNotEqual(untracked["worktree_sha"], edited["worktree_sha"])  # untracked files count
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "with the new file")
        self.assertEqual(run_check.worktree_fingerprint(self.repo)["worktree_sha"], untracked["worktree_sha"])

    def test_worktree_sha_follows_the_worktree_not_the_staged_copy(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _git(self.repo, "add", "a.py")
        staged = run_check.worktree_fingerprint(self.repo)
        (self.repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        self.assertNotEqual(staged["worktree_sha"], run_check.worktree_fingerprint(self.repo)["worktree_sha"])
        self.assertEqual(_git(self.repo, "diff", "--cached", "--name-only"), "a.py")  # staging untouched

    def test_runs_dir_inside_a_tracked_path_is_refused_and_nothing_runs(self):
        marker = self.tmp / "ran"
        proc = self._run("unit", "--", "python3", "-c", f"open({str(marker)!r}, 'w').close()", runs=self.repo / "runs")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("inside the target repo", proc.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.repo / "runs").exists())

    def test_runs_dir_inside_an_ignored_path_is_allowed(self):
        proc = self._run("unit", "--", "true", runs=self.repo / "ignored" / "runs")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._records(self.repo / "ignored" / "runs")), 1)

    def test_usage_errors_exit_2_and_record_nothing(self):
        for args in (("unit", "true"), ("unit", "--"), ("bad name!", "--", "true")):
            with self.subTest(args=args):
                proc = self._run(*args)
                self.assertEqual(proc.returncode, 2)
        self.assertEqual(self._records(), [])
        outside = self.tmp / "outside"
        outside.mkdir()
        self.assertEqual(self._run("unit", "--", "true", cwd=outside).returncode, 2)
        self.assertEqual(self._records(), [])

    def test_record_line_is_sorted_compact_json(self):
        self._run("unit", "--", "true")
        line = (self.runs / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        self.assertEqual(line, json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
