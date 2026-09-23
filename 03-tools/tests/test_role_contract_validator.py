import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import role_contract_validator as rcv


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")


PERMISSIVE_CONTRACT = {"agent": "permissive", "may_write": []}
SCOPED_CONTRACT = {"agent": "scoped-proposer", "may_write": ["app/**"], "forbidden_paths": ["**/*.jks"]}


class MatchAnyTests(unittest.TestCase):
    def test_double_star_matches_nested_path(self):
        self.assertEqual(rcv._match_any("a/b/c.kt", ["a/**"]), "a/**")

    def test_no_match_returns_none(self):
        self.assertIsNone(rcv._match_any("domain/Foo.kt", ["app/**"]))


class EvaluateTests(unittest.TestCase):
    def test_no_allowlist_means_only_forbidden_paths_are_checked(self):
        result = rcv.evaluate(PERMISSIVE_CONTRACT, ["domain/Foo.kt", "app/Bar.kt"], [])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["outside_allowlist"], [])

    def test_change_inside_may_write_passes(self):
        result = rcv.evaluate(SCOPED_CONTRACT, ["app/src/main/Foo.kt"], [])
        self.assertEqual(result["verdict"], "PASS")

    def test_change_outside_may_write_fails(self):
        result = rcv.evaluate(SCOPED_CONTRACT, ["domain/src/main/Foo.kt"], [])
        # negative control: domain/ is not in may_write=["app/**"]
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["outside_allowlist"], ["domain/src/main/Foo.kt"])

    def test_scope_glob_extends_the_allowlist(self):
        result = rcv.evaluate(SCOPED_CONTRACT, ["domain/src/main/Foo.kt"], ["domain/**"])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["outside_allowlist"], [])

    def test_contract_forbidden_path_fails_even_inside_may_write(self):
        result = rcv.evaluate(SCOPED_CONTRACT, ["app/libs/prod.jks"], [])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["forbidden_hits"], [{"path": "app/libs/prod.jks", "pattern": "**/*.jks"}])

    def test_always_forbidden_build_file_fails_regardless_of_contract(self):
        # negative control: a permissive contract (no may_write, no forbidden_paths)
        # can NEVER lift the lock on shared build files.
        result = rcv.evaluate(PERMISSIVE_CONTRACT, ["settings.gradle"], [])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(len(result["forbidden_hits"]), 1)

    def test_always_forbidden_covers_all_five_build_files(self):
        five = ["settings.gradle", "build.gradle", "gradle.properties",
                "gradle/libs.versions.toml", "app/build.gradle"]
        result = rcv.evaluate(PERMISSIVE_CONTRACT, five, [])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(len(result["forbidden_hits"]), 5)

    def test_dot_claude_at_repo_root_is_always_forbidden(self):
        result = rcv.evaluate(PERMISSIVE_CONTRACT, [".claude/worktrees/x/f.kt"], [])
        self.assertEqual(result["verdict"], "FAIL")

    def test_dot_claude_nested_is_always_forbidden(self):
        result = rcv.evaluate(PERMISSIVE_CONTRACT, ["app/.claude/scratch/f.kt"], [])
        self.assertEqual(result["verdict"], "FAIL")

    def test_clean_change_set_passes(self):
        result = rcv.evaluate(SCOPED_CONTRACT, ["app/src/main/Foo.kt", "app/src/main/Bar.kt"], [])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["forbidden_hits"], [])
        self.assertEqual(result["outside_allowlist"], [])

    def test_determinism(self):
        changed = ["app/b.kt", "app/a.kt", "domain/z.kt"]
        first = rcv.evaluate(SCOPED_CONTRACT, changed, [])
        second = rcv.evaluate(SCOPED_CONTRACT, changed, [])
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["changed_paths"], sorted(changed))


class AlwaysForbiddenPatternsTests(unittest.TestCase):
    def test_falls_back_to_default_gradle_files_without_config(self):
        patterns = rcv.always_forbidden_patterns(None)
        self.assertIn("settings.gradle", patterns)
        self.assertIn("**/.claude/**", patterns)

    def test_reads_shared_build_files_from_project_config(self):
        config = {"shared_build_files": ["custom.build.file"]}
        patterns = rcv.always_forbidden_patterns(config)
        self.assertIn("custom.build.file", patterns)
        self.assertNotIn("settings.gradle", patterns)
        self.assertIn("**/.claude/**", patterns)


class ChangedPathsFromRangeTests(unittest.TestCase):
    def test_lists_files_changed_between_two_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "a.kt").write_text("1", encoding="utf-8")
            _git(root, "add", "a.kt")
            _git(root, "commit", "-q", "-m", "a")
            sha_a = _git(root, "rev-parse", "HEAD")

            (root / "b.kt").write_text("1", encoding="utf-8")
            (root / "a.kt").write_text("2", encoding="utf-8")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "b")
            sha_b = _git(root, "rev-parse", "HEAD")

            changed = rcv.changed_paths_from_range(root, f"{sha_a}..{sha_b}")
            self.assertEqual(changed, ["a.kt", "b.kt"])


class ChangedPathsFromWorktreeTests(unittest.TestCase):
    def test_lists_dirty_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "a.kt").write_text("1", encoding="utf-8")
            _git(root, "add", "a.kt")
            _git(root, "commit", "-q", "-m", "init")

            (root / "a.kt").write_text("2", encoding="utf-8")
            (root / "b.kt").write_text("new", encoding="utf-8")

            changed = rcv.changed_paths_from_worktree(root)
            self.assertEqual(changed, ["a.kt", "b.kt"])


class MainCliTests(unittest.TestCase):
    def test_exits_zero_when_worktree_change_is_in_scope(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as contract_dir:
            root = Path(tmp)
            _init_repo(root)
            (root / "README.md").write_text("x", encoding="utf-8")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "init")

            (root / "app").mkdir()
            (root / "app" / "Foo.kt").write_text("class Foo", encoding="utf-8")

            contract_path = Path(contract_dir) / "role.contract.json"
            contract_path.write_text(json.dumps(SCOPED_CONTRACT), encoding="utf-8")

            code = rcv.main(["--contract", str(contract_path), "--repo", str(root), "--worktree", str(root)])
            self.assertEqual(code, 0)

    def test_exits_one_when_worktree_touches_a_build_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as contract_dir:
            root = Path(tmp)
            _init_repo(root)
            (root / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "init")

            (root / "settings.gradle").write_text("include ':app'\ninclude ':domain'\n", encoding="utf-8")

            contract_path = Path(contract_dir) / "role.contract.json"
            contract_path.write_text(json.dumps(PERMISSIVE_CONTRACT), encoding="utf-8")

            code = rcv.main(["--contract", str(contract_path), "--repo", str(root), "--worktree", str(root)])
            # negative control: touching settings.gradle must fail no matter what the contract says
            self.assertEqual(code, 1)

    def test_requires_exactly_one_of_range_or_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "role.contract.json"
            contract_path.write_text(json.dumps(PERMISSIVE_CONTRACT), encoding="utf-8")
            with self.assertRaises(SystemExit):
                rcv.main(["--contract", str(contract_path), "--repo", str(root)])


if __name__ == "__main__":
    unittest.main()
