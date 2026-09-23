"""round_files (numbering, guard), handoff.py and round_output.py over a
temporary round outside a temporary git repo."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import handoff, round_files, round_output

TOOLS_ROOT = Path(__file__).resolve().parent.parent

VALID_FINDINGS = {
    "round": "r1", "role": "challenger",
    "findings": [{"id": "F-01", "lens": "simplicidad", "claim": "c", "attack": "a", "failure_scenario": "f",
                  "evidence": ["x.kt:1"], "verdict": "OK", "epistemic": "Probado", "simpler_alternative": "none"}],
    "summary": "ok",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="round-files-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.round_dir = self.tmp / "round-x"
        self.round_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RoundFilesTests(Fixture):
    def test_next_seq_starts_at_one_and_skips_context_pack(self):
        self.assertEqual(round_files.next_seq(self.round_dir), 1)
        (self.round_dir / "000-context.md").write_text("x", encoding="utf-8")
        (self.round_dir / "007-judge-verdict.json").write_text("{}", encoding="utf-8")
        self.assertEqual(round_files.next_seq(self.round_dir), 8)

    def test_normalize_role_accepts_short_and_long(self):
        self.assertEqual(round_files.normalize_role("judge"), "generic-judge")
        self.assertEqual(round_files.normalize_role("generic-judge"), "generic-judge")
        with self.assertRaises(ValueError):
            round_files.normalize_role("wizard")

    def test_write_guard_refuses_repo_and_build_files(self):
        with self.assertRaises(PermissionError):
            round_files.assert_write_allowed(self.repo / "round" / "x.json", self.repo)
        with self.assertRaises(PermissionError):
            round_files.assert_write_allowed(self.tmp / "settings.gradle", self.repo)
        # negative control: outside the repo and with no forbidden name, it passes
        round_files.assert_write_allowed(self.round_dir / "x.json", self.repo)

    def test_every_role_schema_file_exists(self):
        for role, name in round_files.ROLE_SCHEMA.items():
            self.assertTrue(round_files.schema_path(name).exists(), f"{role} -> {name}")


class HandoffTests(Fixture):
    def test_writes_numbered_file_with_script_filled_shas(self):
        artifact = self.round_dir / "003-challenger-findings.json"
        artifact.write_text("{}", encoding="utf-8")
        path, doc = handoff.write_handoff(self.repo, self.round_dir, "challenger", "judge", "findings",
                                          artifact, "attacked 3 claims", ["disk full undecided"])
        self.assertEqual(path.name, "004-challenger-findings.json")
        self.assertEqual(doc["repo_sha"], _git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(doc["tools_sha"], _git(TOOLS_ROOT, "rev-parse", "HEAD"))
        self.assertEqual(doc["artifact_path"], "003-challenger-findings.json")
        self.assertEqual(doc["from_role"], "generic-challenger")
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written, doc)

    def test_bad_slug_is_rejected(self):
        with self.assertRaises(ValueError):
            handoff.write_handoff(self.repo, self.round_dir, "judge", "proposer", "Not A Slug", self.round_dir / "a.json", "s", [])

    def test_cli_exit_two_on_unknown_role(self):
        code = handoff.main(["--repo", str(self.repo), "--round-dir", str(self.round_dir), "--from-role", "wizard",
                             "--to-role", "judge", "--topic", "x", "--artifact", "a.json", "--summary", "s"])
        self.assertEqual(code, 2)
        self.assertEqual(list(self.round_dir.iterdir()), [])


class RoundOutputTests(Fixture):
    def test_valid_document_is_written_under_role_schema(self):
        result = round_output.write_output(self.round_dir, "challenger", VALID_FINDINGS, repo=self.repo)
        self.assertEqual(result["verdict"], "PASS")
        self.assertTrue((self.round_dir / "001-challenger-findings.json").exists())
        self.assertEqual(result["schema"], "findings")

    def test_invalid_document_writes_nothing(self):
        # negative control
        result = round_output.write_output(self.round_dir, "challenger", {"round": 1}, repo=self.repo)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIsNone(result["path"])
        self.assertEqual(list(self.round_dir.iterdir()), [])

    def test_truncated_document_is_incomplete_but_written(self):
        doc = dict(VALID_FINDINGS, truncated=True, not_covered=["C-09"])
        result = round_output.write_output(self.round_dir, "challenger", doc, repo=self.repo)
        self.assertEqual(result["verdict"], "INCOMPLETE")
        self.assertIsNotNone(result["path"])

    def test_cli_exit_one_on_fail_and_zero_on_pass(self):
        doc_path = self.tmp / "doc.json"
        doc_path.write_text(json.dumps(VALID_FINDINGS), encoding="utf-8")
        self.assertEqual(round_output.main(["--round-dir", str(self.round_dir), "--role", "challenger",
                                            "--document", str(doc_path)]), 0)
        doc_path.write_text(json.dumps({"round": 1}), encoding="utf-8")
        self.assertEqual(round_output.main(["--round-dir", str(self.round_dir), "--role", "challenger",
                                            "--document", str(doc_path)]), 1)
