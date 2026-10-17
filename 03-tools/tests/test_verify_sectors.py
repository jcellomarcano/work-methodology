"""bin/verify-sectors.sh against a fake repo whose gradlew is a stub that
fails when the task contains FAIL_ME. Never against a real repo."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = TOOLS_ROOT / "bin" / "verify-sectors.sh"

STUB_GRADLEW = """#!/usr/bin/env bash
echo "stub gradlew $*"
case "$1" in *FAIL_ME*) exit 1;; esac
exit 0
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class _SectorFixture:
    SETTINGS = "include ':domain'\ninclude ':bad'\ninclude ':gated'\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-sectors-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "gradlew").write_text(STUB_GRADLEW, encoding="utf-8")
        (self.repo / "gradlew").chmod(0o755)
        # Every project the sector map names goes here, as in a real repo:
        # a task whose project is not included is dropped and forces the
        # full battery, which is what AbsentProjectForcesFull tests.
        (self.repo / "settings.gradle").write_text(self.SETTINGS, encoding="utf-8")
        (self.repo / "domain").mkdir()
        (self.repo / "domain" / "A.kt").write_text("a\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "checkout", "-q", "-b", "feature")
        self.config = self.tmp / "project.json"
        self.config.write_text(json.dumps({
            "shared_build_files": ["settings.gradle"],
            "rdd": {"exempt_globs": ["**/*.md"]},
            "test_sectors": {"base_ref": "main", "full_required_globs": [],
                             "credential_gate": {"name": "sdk_key", "task_prefixes": [":gated:"],
                                                 "local_properties_key": "sdk.key", "env_var": "SDK_KEY_TEST_VAR"},
                             "sectors": [{"paths": ["domain/"], "tasks": [":domain:test"]},
                                         {"paths": ["bad/"], "tasks": [":bad:FAIL_ME"]},
                                         {"paths": ["gated/"], "tasks": [":gated:test"]}]}}), encoding="utf-8")
        self.repo_sha = None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.repo_sha:
            for d in (TOOLS_ROOT / "out" / "verify-sectors").glob(f"{self.repo_sha}*"):
                shutil.rmtree(d, ignore_errors=True)
        lock = TOOLS_ROOT / "out" / ".gradle.lock"
        if lock.exists():
            lock.rmdir()

    def _change(self, rel: str):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", f"touch {rel}")
        self.repo_sha = _git(self.repo, "rev-parse", "HEAD")

    def _run(self, *extra):
        env = dict(os.environ)
        env.pop("SDK_KEY_TEST_VAR", None)
        return subprocess.run(["bash", str(SCRIPT), str(self.repo), "--config", str(self.config), "--run-id", "t", *extra],
                              capture_output=True, text=True, env=env)

    def _summary(self):
        return json.loads((TOOLS_ROOT / "out" / "verify-sectors" / self.repo_sha / "t" / "summary.json").read_text(encoding="utf-8"))


class VerifySectorsTests(_SectorFixture, unittest.TestCase):
    def test_green_sector_run(self):
        self._change("domain/A.kt")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = self._summary()
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual([t["task"] for t in summary["tasks"]], [":domain:test"])
        self.assertFalse((TOOLS_ROOT / "out" / ".gradle.lock").exists())

    def test_failing_task_exits_one(self):
        self._change("bad/B.kt")
        proc = self._run()
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self._summary()["verdict"], "FAIL")

    def test_shared_build_file_exits_three_without_running(self):
        self._change("settings.gradle")
        proc = self._run()
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertFalse((TOOLS_ROOT / "out" / "verify-sectors" / self.repo_sha / "t" / "summary.json").exists())

    def test_credential_gate_skips_and_records(self):
        self._change("gated/G.kt")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = self._summary()
        self.assertEqual(summary["skipped_no_credential"], [":gated:test"])
        self.assertEqual(summary["tasks"], [])

    def test_credential_present_runs_gated_task(self):
        # negative control: with the key in local.properties nothing is skipped
        self._change("gated/G.kt")
        (self.repo / ".git" / "info" / "exclude").write_text("local.properties\n", encoding="utf-8")
        (self.repo / "local.properties").write_text("sdk.key=abc\n", encoding="utf-8")
        proc = self._run("--committed-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = self._summary()
        self.assertEqual(summary["skipped_no_credential"], [])
        self.assertEqual([t["task"] for t in summary["tasks"]], [":gated:test"])


class AbsentProjectForcesFull(_SectorFixture, unittest.TestCase):
    """A sector naming a module absent from settings.gradle does not take the
    shortcut: it escalates to the full battery instead of silently skipping the test."""

    SETTINGS = "include ':domain'\n"

    def test_absent_project_escalates(self):
        self._change("gated/G.kt")
        proc = self._run()
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_present_project_still_runs(self):
        self._change("domain/A.kt")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([t["task"] for t in self._summary()["tasks"]], [":domain:test"])
