"""Tests bin/verify-commit.sh against a fake repo whose tools/verify/
verify.sh is a stub: it passes or fails based on a marker in the commit
message ('FAIL_ME'). This is NEVER run against a real project's real repo (that would be
~4 min per real Gradle commit): this is exactly the "unit test with a fake
repo" the task calls for instead of that real run.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
VERIFY_COMMIT_SH = TOOLS_ROOT / "bin" / "verify-commit.sh"

STUB_VERIFY_SH = """#!/usr/bin/env bash
set -euo pipefail
MSG="$(git log -1 --pretty=%B)"
echo "stub verify.sh corriendo, args: $*"
if echo "$MSG" | grep -q "FAIL_ME"; then
  echo "stub: encontrado el marcador FAIL_ME"
  exit 1
fi
echo "stub: todo en orden"
exit 0
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(cwd: Path, message: str) -> str:
    _git(cwd, "commit", "-q", "--allow-empty", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


class VerifyCommitFakeRepoTests(unittest.TestCase):
    def setUp(self):
        self.repo_dir = tempfile.mkdtemp(prefix="verify-commit-repo-")
        self.repo = Path(self.repo_dir)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")

        verify_dir = self.repo / "tools" / "verify"
        verify_dir.mkdir(parents=True)
        stub_path = verify_dir / "verify.sh"
        stub_path.write_text(STUB_VERIFY_SH, encoding="utf-8")
        stub_path.chmod(0o755)
        (self.repo / "README.md").write_text("fake repo\n", encoding="utf-8")
        _git(self.repo, "add", "-A")

        self.sha_base = _commit(self.repo, "chore: init con el stub de verify")
        self.sha_fail = _commit(self.repo, "feat: rompe algo FAIL_ME aqui")
        self.sha_pass = _commit(self.repo, "fix: arregla lo anterior")

        self.range = f"{self.sha_base}..{self.sha_pass}"

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        # cleans up any worktree/lock/log/json left behind, even
        # from a half-failed run.
        for out_dir in (TOOLS_ROOT / "out" / "worktrees").glob("verify-commit-*"):
            shutil.rmtree(out_dir, ignore_errors=True)
        lock_dir = TOOLS_ROOT / "out" / ".gradle.lock"
        if lock_dir.exists():
            lock_dir.rmdir()
        for sha in (self.sha_base, self.sha_fail, self.sha_pass):
            (TOOLS_ROOT / "out" / "verify" / f"{sha}.log").unlink(missing_ok=True)
        self._out_json_path().unlink(missing_ok=True)

    def _out_json_path(self) -> Path:
        """The name carries range AND repo tip since 15-sep.

        Two different worktrees use the same range ('55529c347..HEAD' is valid for
        one slice and for its fix) and without the suffix the second run would
        silently overwrite the first one's result.
        """
        sanitized = self.range.replace("/", "_").replace(":", "_").replace(" ", "_")
        # sha_pass IS the tip: git is not asked again because tearDown
        # deletes the repo before calling here to clean up the json.
        return TOOLS_ROOT / "out" / "verify" / f"{sanitized}.{self.sha_pass[:9]}.json"

    def test_range_excludes_base_and_processes_oldest_first(self):
        proc = subprocess.run(
            ["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range],
            capture_output=True, text=True,
        )
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        self.assertTrue(out_path.exists(), proc.stderr)

        payload = json.loads(out_path.read_text(encoding="utf-8"))
        shas = [c["sha"] for c in payload["commits"]]
        # negative control: sha_base is the EXCLUDED end of range A..B, it must not appear.
        self.assertNotIn(self.sha_base, shas)
        # oldest first: the commit that breaks it comes before the one that fixes it.
        self.assertEqual(shas, [self.sha_fail, self.sha_pass])

    def test_fail_marker_commit_is_marked_fail_others_pass(self):
        subprocess.run(["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range], capture_output=True)
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        payload = json.loads(out_path.read_text(encoding="utf-8"))

        by_sha = {c["sha"]: c for c in payload["commits"]}
        self.assertEqual(by_sha[self.sha_fail]["verdict"], "FAIL")
        self.assertEqual(by_sha[self.sha_pass]["verdict"], "PASS")

    def test_script_exits_nonzero_when_any_commit_fails(self):
        proc = subprocess.run(
            ["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range], capture_output=True, text=True
        )
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        self.assertNotEqual(proc.returncode, 0)

    def test_logs_are_captured_per_commit(self):
        subprocess.run(["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range], capture_output=True)
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        payload = json.loads(out_path.read_text(encoding="utf-8"))

        for commit in payload["commits"]:
            log_path = TOOLS_ROOT / commit["log"]
            self.addCleanup(lambda p=log_path: p.unlink(missing_ok=True))
            self.assertTrue(log_path.exists())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("stub verify.sh corriendo", text)

    def test_full_flag_is_forwarded_to_verify_script(self):
        subprocess.run(
            ["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range, "--full"], capture_output=True
        )
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        for commit in payload["commits"]:
            log_path = TOOLS_ROOT / commit["log"]
            self.addCleanup(lambda p=log_path: p.unlink(missing_ok=True))
            self.assertIn("args: --full", log_path.read_text(encoding="utf-8"))

    def test_worktree_is_removed_after_each_commit(self):
        subprocess.run(["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range], capture_output=True)
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        for commit in json.loads(out_path.read_text(encoding="utf-8"))["commits"]:
            log_path = TOOLS_ROOT / commit["log"]
            self.addCleanup(lambda p=log_path: p.unlink(missing_ok=True))
        # negative control: no worktree should be left hanging around.
        leftover = list((TOOLS_ROOT / "out" / "worktrees").glob("verify-commit-*"))
        self.assertEqual(leftover, [])

    def test_payload_has_no_durations_and_has_envelope_keys(self):
        subprocess.run(["bash", str(VERIFY_COMMIT_SH), str(self.repo), self.range], capture_output=True)
        out_path = self._out_json_path()
        self.addCleanup(lambda: out_path.unlink(missing_ok=True))
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        for commit in payload["commits"]:
            log_path = TOOLS_ROOT / commit["log"]
            self.addCleanup(lambda p=log_path: p.unlink(missing_ok=True))

        self.assertEqual(
            set(payload) - {"range", "commits"},
            {"schema_version", "tool_sha", "tool_versions", "repo_sha", "repo_dirty"},
        )
        for commit in payload["commits"]:
            self.assertEqual(set(commit), {"sha", "subject", "verdict", "log"})
            # negative control: no wall-clock at all in the payload.
            self.assertNotIn("duration", commit)
            self.assertNotIn("started_at", commit)

    def test_missing_range_has_no_commits_exits_nonzero(self):
        proc = subprocess.run(
            ["bash", str(VERIFY_COMMIT_SH), str(self.repo), f"{self.sha_pass}..{self.sha_pass}"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
