import tempfile
import unittest
from pathlib import Path

from lib import repo_scan


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ListModulesTests(unittest.TestCase):
    def test_reads_modules_in_declared_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "settings.gradle", "include ':app'\ninclude ':payment:gateway'\n")
            self.assertEqual(repo_scan.list_modules(root), ["app", "payment/gateway"])

    def test_deduplicates_repeated_includes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "settings.gradle", "include ':app'\ninclude ':app'\n")
            self.assertEqual(repo_scan.list_modules(root), ["app"])


class FilterModulesTests(unittest.TestCase):
    def test_accepts_plain_and_colon_prefixed_names(self):
        modules = ["app", "domain", "payment/gateway"]
        self.assertEqual(repo_scan.filter_modules(modules, ["app", ":domain"]), ["app", "domain"])

    def test_none_returns_all(self):
        modules = ["app", "domain"]
        self.assertEqual(repo_scan.filter_modules(modules, None), modules)


class KotlinFilesTests(unittest.TestCase):
    def test_finds_files_under_src_main_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "app/src/main/java/pkg/B.kt", "class B")
            _write(root / "app/src/main/java/pkg/A.kt", "class A")
            result = repo_scan.kotlin_files(root, ["app"], "main")
            self.assertEqual(
                result,
                [("app", "app/src/main/java/pkg/A.kt"), ("app", "app/src/main/java/pkg/B.kt")],
            )

    def test_excludes_claude_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "app/src/main/java/pkg/Real.kt", "class Real")
            # negative control: a file under .claude/ (an agent worktree) must not slip through
            _write(root / "app/.claude/worktrees/x/src/main/java/pkg/Real.kt", "class Real")
            result = repo_scan.kotlin_files(root, ["app"], "main")
            self.assertEqual(result, [("app", "app/src/main/java/pkg/Real.kt")])

    def test_excludes_build_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "app/src/main/java/pkg/Real.kt", "class Real")
            _write(root / "app/src/main/build/generated/pkg/Gen.kt", "class Gen")
            result = repo_scan.kotlin_files(root, ["app"], "main")
            self.assertEqual(result, [("app", "app/src/main/java/pkg/Real.kt")])

    def test_missing_module_src_dir_is_skipped_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = repo_scan.kotlin_files(root, ["ghost"], "main")
            self.assertEqual(result, [])

    def test_determinism_repeated_calls_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                _write(root / f"app/src/main/java/pkg/F{i}.kt", "class F")
            first = repo_scan.kotlin_files(root, ["app"], "main")
            second = repo_scan.kotlin_files(root, ["app"], "main")
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
