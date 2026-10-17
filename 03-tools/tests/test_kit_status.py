"""lib/kit_status.py and bin/kit-status.sh: the measured status block of the
kit's README (kit-init T11, S11).

Two layers:
- the drift test reads the real kit: the README block must match the code it
  describes (`--check` semantics). It is skipped while `--write` runs the
  suite (METODO_KIT_STATUS_RUNNING=1), since that run is about to rewrite
  the block;
- unit tests build a small fake kit tree in a temp git repo and inject fake
  suite and init runners, so they never run the real suite or a real init.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
KIT_ROOT = TOOLS_ROOT.parent
KIT_STATUS = TOOLS_ROOT / "lib" / "kit_status.py"
sys.path.insert(0, str(TOOLS_ROOT))

from lib import kit_status  # noqa: E402

README = ("# Fake kit\n\nIntro line.\n\n## Start here\n\n1. one\n2. two\n\n## Kit map\n\n| a | b |\n|---|---|\n"
          "| x | y |\n")
HOOKS = {"hooks": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "a"}]}],
                   "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "b"}]}]}}
FAKE_TREE = {
    "README.md": README,
    "01-roles/agents/generic-a.md": "agent a\n",
    "01-roles/agents/generic-b.md": "agent b\n",
    "01-roles/agents/generic-a.contract.json": "{}\n",
    "02-skills/one/SKILL.md": "skill one\n",
    "02-skills/two/SKILL.md": "skill two\n",
    "03-tools/README.md": "# tools\n",
    "03-tools/.gitignore": "out/\nbaselines/\nvendor/\n__pycache__/\n",
    "03-tools/bin/install-claude.sh": "#!/usr/bin/env bash\nSKILLS=(\n  one\n  two\n)\n",
    "03-tools/lib/thing.py": "X = 1\n",
    "03-tools/mcp/__init__.py": "",
    "03-tools/mcp/catalog.py": "TOOLS = ('a', 'b', 'c')\n",
    "03-tools/hooks/hooks.settings.json": json.dumps(HOOKS) + "\n",
    "03-tools/config/docs-caps.json": json.dumps({"docs_root": "~/x", "caps": {"README.md": 80, "gone.md": 10}}) + "\n",
    "03-tools/config/output-lint.personal.json": "{}\n",
    "03-tools/schemas/a.schema.json": "{}\n",
    "03-tools/tests/__init__.py": "",
    "03-tools/tests/test_fake.py": ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
                                    "        pass\n\n    def test_b(self):\n        pass\n"),
}
OK_SUITE = {"result": "OK", "ran": 2, "failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0,
            "unexpected_successes": 0, "exit": 0}
FAILED_SUITE = dict(OK_SUITE, result="FAILED", failures=1, exit=1)
INIT = {"reported": True, "exit": 0, "doctor": "PASS", "kit_installed": True, "smoke": "PASS", "loop_ran": True,
        "ready_for_benchmark": True, "pending": 22, "missing": 3, "unknown": 1, "suggestions": 9,
        "idempotent": True}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout


def make_tree(root: Path) -> Path:
    for rel, text in FAKE_TREE.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fake kit")
    return root


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir() and (KIT_ROOT / ".git").exists(), "kit only: drift test")
class ReadmeBlockDriftTest(unittest.TestCase):
    @unittest.skipIf(os.environ.get("METODO_KIT_STATUS_RUNNING") == "1",
                     "kit-status.sh --write is running the suite: the block is about to be rewritten")
    def test_readme_status_block_is_current(self):
        current, messages = kit_status.check(KIT_ROOT)
        self.assertTrue(current, "\n".join(messages))


class KitStatusUnitTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="kit-status-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = make_tree(tmp / "kit")
        self.readme = self.root / "README.md"

    def write(self, suite=OK_SUITE, init=INIT, allow_failing=False) -> int:
        return kit_status.write(self.root, suite_runner=lambda _root: dict(suite),
                                init_runner=lambda _root: dict(init), allow_failing=allow_failing,
                                log=lambda _msg: None)

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(KIT_STATUS), *args, "--root", str(self.root)],
                              capture_output=True, text=True, env=dict(os.environ, METODO_MEMORY="off"), timeout=120)

    # structure and fingerprint

    def test_structure_counts_the_fake_tree(self):
        counts = kit_status.structure(self.root)
        self.assertEqual(counts, {"agents": 2, "skills": 2, "skills_installed": 2, "mcp_tools": 3, "claude_hooks": 2,
                                  "test_cases": 2})

    def test_personal_files_and_docs_are_not_fingerprinted(self):
        paths = kit_status.fingerprint(self.root)["paths"]
        self.assertIn("03-tools/lib/thing.py", paths)
        self.assertIn("01-roles/agents/generic-a.contract.json", paths)
        self.assertNotIn("03-tools/config/output-lint.personal.json", paths)
        self.assertNotIn("03-tools/README.md", paths)
        self.assertNotIn("README.md", paths)
        before = kit_status.fingerprint(self.root)["digest"]
        (self.root / "03-tools/config/output-lint.personal.json").write_text('{"mine": 1}\n', encoding="utf-8")
        self.assertEqual(before, kit_status.fingerprint(self.root)["digest"])
        # the convention, not a list of names: any *.personal.* or personal/ path is skipped
        (self.root / "03-tools/lib/personal").mkdir()
        (self.root / "03-tools/lib/personal/notes.py").write_text("Z = 3\n", encoding="utf-8")
        (self.root / "03-tools/lib/helper.personal.py").write_text("Z = 4\n", encoding="utf-8")
        self.assertEqual(before, kit_status.fingerprint(self.root)["digest"])

    def test_untracked_file_counts_and_committing_it_changes_nothing(self):
        before = kit_status.fingerprint(self.root)["digest"]
        (self.root / "03-tools/lib/new.py").write_text("Y = 2\n", encoding="utf-8")
        untracked = kit_status.fingerprint(self.root)["digest"]
        self.assertNotEqual(before, untracked)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "new")
        self.assertEqual(untracked, kit_status.fingerprint(self.root)["digest"])

    def test_generated_dirs_are_not_fingerprinted(self):
        before = kit_status.fingerprint(self.root)["digest"]
        for rel in ("03-tools/out/x.json", "03-tools/lib/__pycache__/thing.pyc", "03-tools/lib/docs/notes.md"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("noise\n", encoding="utf-8")
        self.assertEqual(before, kit_status.fingerprint(self.root)["digest"])

    # --check

    def test_check_fails_without_a_block_and_names_the_fix(self):
        current, messages = kit_status.check(self.root)
        self.assertFalse(current)
        self.assertIn(kit_status.FIX_COMMAND, "\n".join(messages))
        proc = self.cli("--check")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("03-tools/bin/kit-status.sh --write", proc.stderr)

    def test_change_to_fingerprinted_file_makes_check_fail_with_the_fix(self):
        self.assertEqual(self.write(), 0)
        self.assertEqual(self.cli("--check").returncode, 0)
        (self.root / "03-tools/lib/thing.py").write_text("X = 2\n", encoding="utf-8")
        current, messages = kit_status.check(self.root)
        self.assertFalse(current)
        text = "\n".join(messages)
        self.assertIn("code_fingerprint", text)
        self.assertIn(kit_status.FIX_COMMAND, text)
        proc = self.cli("--check")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("03-tools/bin/kit-status.sh --write", proc.stderr)

    def test_new_test_case_or_skill_makes_check_fail(self):
        self.assertEqual(self.write(), 0)
        (self.root / "02-skills/three").mkdir()
        (self.root / "02-skills/three/SKILL.md").write_text("skill three\n", encoding="utf-8")
        current, messages = kit_status.check(self.root)
        self.assertFalse(current)
        self.assertIn("structure", "\n".join(messages))

    def test_docs_only_change_keeps_check_green(self):
        self.assertEqual(self.write(), 0)
        (self.root / "03-tools/README.md").write_text("# tools\n\nMore prose.\n", encoding="utf-8")
        text = self.readme.read_text(encoding="utf-8")
        self.readme.write_text(text.replace("Intro line.", "Intro line, reworded."), encoding="utf-8")
        current, messages = kit_status.check(self.root)
        self.assertTrue(current, messages)

    def test_doc_over_its_cap_makes_check_fail(self):
        self.assertEqual(self.write(), 0)
        self.readme.write_text(self.readme.read_text(encoding="utf-8") + "x\n" * 80, encoding="utf-8")
        current, messages = kit_status.check(self.root)
        self.assertFalse(current)
        self.assertIn("docs caps", "\n".join(messages))

    # --write

    def test_first_write_inserts_the_block_under_start_here(self):
        self.assertEqual(self.write(), 0)
        text = self.readme.read_text(encoding="utf-8")
        start = text.index(kit_status.START)
        self.assertLess(text.index("2. two"), start)
        self.assertLess(text.index(kit_status.END), text.index("## Kit map"))
        before, after = README.split("## Kit map", 1)
        self.assertTrue(text.startswith(before))
        self.assertTrue(text.endswith("## Kit map" + after))
        self.assertIn("2. two\n\n" + kit_status.START, text)
        self.assertIn(kit_status.END + "\n\n## Kit map", text)
        block = kit_status.extract_block(text)
        self.assertLessEqual(len(block.splitlines()), 13)
        self.assertIn("[Measured]", block)
        self.assertIn("[Tested]", block)
        self.assertIn("[Measured, this machine]", block)

    def test_rewrite_touches_only_the_lines_between_markers(self):
        self.assertEqual(self.write(), 0)
        text = self.readme.read_text(encoding="utf-8")
        edited = text.replace("Intro line.", "Intro line, edited by hand.").replace("| x | y |", "| x | z |")
        self.readme.write_text(edited, encoding="utf-8")
        (self.root / "03-tools/lib/thing.py").write_text("X = 3\n", encoding="utf-8")
        self.assertEqual(self.write(init=dict(INIT, pending=5)), 0)
        new = self.readme.read_text(encoding="utf-8")
        head, tail = edited.split(kit_status.START, 1)
        tail = tail.split(kit_status.END, 1)[1]
        self.assertTrue(new.startswith(head))
        self.assertTrue(new.endswith(tail))
        self.assertIn("5 pending human steps", new)
        self.assertIn("3 missing, 1 unknown of 9 suggested helpers", new)
        self.assertNotEqual(kit_status.extract_block(text), kit_status.extract_block(new))

    def test_write_refuses_a_failing_suite_without_allow_failing(self):
        original = self.readme.read_bytes()
        self.assertEqual(self.write(suite=FAILED_SUITE), 1)
        self.assertEqual(self.readme.read_bytes(), original)
        self.assertEqual(self.write(suite=FAILED_SUITE, allow_failing=True), 0)
        block = kit_status.extract_block(self.readme.read_text(encoding="utf-8"))
        self.assertIn("FAILED: ran 2, failures 1, errors 0", block)
        self.assertNotIn("| OK", block)

    def test_two_writes_on_the_same_tree_are_byte_identical(self):
        self.assertEqual(self.write(), 0)
        first = self.readme.read_bytes()
        self.assertEqual(self.write(), 0)
        self.assertEqual(first, self.readme.read_bytes())

    def test_half_markers_are_refused(self):
        self.readme.write_text(README + kit_status.START + "\n", encoding="utf-8")
        original = self.readme.read_bytes()
        self.assertEqual(self.write(), 2)
        self.assertEqual(self.readme.read_bytes(), original)

    def test_measured_at_has_sha_and_dirty_and_no_timestamp(self):
        sha = _git(self.root, "rev-parse", "--short", "HEAD").strip()
        self.assertEqual(self.write(), 0)
        block = kit_status.extract_block(self.readme.read_text(encoding="utf-8"))
        self.assertIn(f"`{sha}`, dirty: no", block)
        self.assertNotRegex(block, r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}")
        (self.root / "03-tools/lib/thing.py").write_text("X = 4\n", encoding="utf-8")
        self.assertEqual(self.write(), 0)
        self.assertIn("dirty: yes", kit_status.extract_block(self.readme.read_text(encoding="utf-8")))

    def test_unreported_init_is_written_as_not_measured(self):
        self.assertEqual(self.write(init={"reported": False, "exit": 1}), 0)
        block = kit_status.extract_block(self.readme.read_text(encoding="utf-8"))
        self.assertIn("no report (init exit 1)", block)
        self.assertNotIn("kit_installed true", block)

    # parsing

    def test_unittest_summary_is_parsed(self):
        ok = kit_status.parse_unittest("....\nRan 735 tests in 9.1s\n\nOK (skipped=4, expected failures=2)\n", 0)
        self.assertEqual((ok["result"], ok["ran"], ok["skipped"], ok["expected_failures"], ok["failures"]),
                         ("OK", 735, 4, 2, 0))
        bad = kit_status.parse_unittest("Ran 10 tests in 1s\n\nFAILED (failures=1, errors=2, skipped=3)\n", 1)
        self.assertEqual((bad["result"], bad["failures"], bad["errors"], bad["skipped"]), ("FAILED", 1, 2, 3))
        none = kit_status.parse_unittest("Traceback: boom\n", 1)
        self.assertEqual(none["result"], "FAILED")
        self.assertIsNone(none["ran"])
        lying = kit_status.parse_unittest("Ran 3 tests in 1s\n\nOK\n", 1)
        self.assertEqual(lying["result"], "FAILED")


if __name__ == "__main__":
    unittest.main()
