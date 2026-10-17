"""lib/detect_repo.py: deterministic facts about a target repo (languages,
build system and shared build files, base ref, ticket keys, test globs,
remote, name), as sorted-key JSON on stdout, over throwaway git repos."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DETECT = TOOLS_ROOT / "lib" / "detect_repo.py"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path: Path, files: dict[str, str], subjects: list[str] = ("init",), branch: str = "main") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if files:
        _git(path, "add", "-A")
    for subject in subjects:
        _git(path, "commit", "-q", "--allow-empty", "-m", subject)
    return path


def detect(repo: Path) -> tuple[dict, str]:
    proc = subprocess.run([sys.executable, str(DETECT), str(repo)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"detect_repo exit {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout), proc.stdout


GRADLE_FILES = {
    "settings.gradle.kts": "rootProject.name = \"x\"\n",
    "build.gradle.kts": "\n",
    "gradle.properties": "\n",
    "gradle/libs.versions.toml": "[versions]\n",
    "app/build.gradle.kts": "\n",
    "app/src/main/kotlin/A.kt": "class A\n",
    "app/src/main/kotlin/B.kt": "class B\n",
    "app/src/test/kotlin/ATest.kt": "class ATest\n",
    "legacy/Foo.java": "class Foo {}\n",
    "README.md": "x\n",
}

PYTHON_FILES = {
    "pyproject.toml": "[project]\nname='x'\n",
    "uv.lock": "\n",
    "requirements-dev.txt": "\n",
    "pkg/a.py": "\n",
    "pkg/b.py": "\n",
    "tests/test_a.py": "\n",
}

NODE_FILES = {
    "package.json": "{}\n",
    "package-lock.json": "{}\n",
    "src/a.ts": "\n",
    "src/b.ts": "\n",
    "src/a.test.ts": "\n",
    "tools/x.js": "\n",
}


class DetectRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="detect-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gradle_repo_languages_build_files_tests_globs(self):
        repo = make_repo(self.tmp / "android-app", GRADLE_FILES)
        facts, _ = detect(repo)
        self.assertEqual(facts["languages"], [{"files": 3, "name": "kotlin"}, {"files": 1, "name": "java"}])
        self.assertEqual(facts["primary_language"], "kotlin")
        self.assertEqual(facts["build_system"], "gradle")
        # a Gradle repo gets the whole Gradle glob set, not only the files present
        self.assertEqual(facts["shared_build_files"], sorted([
            "**/*.gradle", "**/*.gradle.kts", "**/gradle.properties", "**/gradlew", "**/gradlew.bat",
            "**/gradle/wrapper/**", "**/gradle/*.versions.toml", "**/gradle/verification-metadata.xml",
            "**/gradle/verification-keyring.*", "**/gradle/gradle-daemon-jvm.properties", "**/gradle.lockfile",
            "**/settings-gradle.lockfile", "**/gradle/dependency-locks/**", "**/buildSrc/**", "**/build-logic/**",
        ]))
        self.assertEqual(facts["tests_globs"]["kotlin"], ["**/src/androidTest/**", "**/src/test/**"])
        self.assertIn("java", facts["tests_globs"])

    def test_python_repo_build_files_and_tests_globs(self):
        repo = make_repo(self.tmp / "py", PYTHON_FILES)
        facts, _ = detect(repo)
        self.assertEqual(facts["primary_language"], "python")
        self.assertEqual(facts["build_system"], "python")
        self.assertEqual(facts["shared_build_files"], ["pyproject.toml", "requirements-dev.txt", "uv.lock"])
        self.assertIn("tests/**", facts["tests_globs"]["python"])
        self.assertIn("**/test_*.py", facts["tests_globs"]["python"])

    def test_node_repo_typescript_ranked_over_javascript(self):
        repo = make_repo(self.tmp / "web", NODE_FILES)
        facts, _ = detect(repo)
        self.assertEqual([l["name"] for l in facts["languages"]], ["typescript", "javascript"])
        self.assertEqual(facts["build_system"], "node")
        self.assertEqual(facts["shared_build_files"], ["package-lock.json", "package.json"])
        self.assertIn("**/*.test.ts", facts["tests_globs"]["typescript"])
        self.assertIn("**/*.spec.ts", facts["tests_globs"]["typescript"])

    def test_base_ref_prefers_origin_head(self):
        repo = make_repo(self.tmp / "r", {"a.go": "package a\n", "go.mod": "module a\n"})
        _git(repo, "remote", "add", "origin", "https://example.com/acme/bookings-api.git")
        _git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        facts, _ = detect(repo)
        self.assertEqual(facts["base_ref"], "origin/trunk")
        self.assertTrue(facts["has_remote"])
        self.assertEqual(facts["repo_name"], "bookings-api")
        self.assertEqual(facts["build_system"], "go")
        self.assertEqual(facts["tests_globs"]["go"], ["**/*_test.go"])

    def test_base_ref_falls_back_to_first_existing_candidate(self):
        repo = make_repo(self.tmp / "r", {"a.txt": "x\n"}, branch="feature")
        _git(repo, "remote", "add", "origin", "https://example.com/acme/thing.git")
        _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        _git(repo, "update-ref", "refs/heads/main", "HEAD")
        facts, _ = detect(repo)
        self.assertEqual(facts["base_ref"], "origin/develop")

    def test_repo_without_remote(self):
        repo = make_repo(self.tmp / "solo", {"a.py": "\n"}, branch="master")
        facts, _ = detect(repo)
        self.assertFalse(facts["has_remote"])
        self.assertEqual(facts["repo_name"], "solo")
        self.assertEqual(facts["base_ref"], "master")

    def test_no_base_ref_and_no_ticket_keys_in_an_unborn_repo(self):
        repo = make_repo(self.tmp / "empty", {}, subjects=[], branch="feature")
        facts, _ = detect(repo)
        self.assertIsNone(facts["base_ref"])
        self.assertEqual(facts["ticket_keys"], [])
        self.assertIsNone(facts["primary_language"])
        self.assertIsNone(facts["build_system"])
        self.assertEqual(facts["languages"], [])

    def test_ticket_keys_kept_at_three_sightings_sorted_by_count_then_name(self):
        subjects = [
            "DEV-1 a", "DEV-2 b", "DEV-3 c", "DEV-4 d",
            "ABC-1 e", "ABC-2 f", "ABC-3 g",
            "BOOK-9 only twice", "BOOK-10 again",
            "UTF-8 fix", "UTF-8 fix again", "UTF-8 third",
            "XYZ-1 x", "XYZ-2 y", "XYZ-3 z",
        ]
        repo = make_repo(self.tmp / "t", {"a.txt": "x\n"}, subjects=subjects)
        facts, _ = detect(repo)
        self.assertEqual(facts["ticket_keys"], ["DEV", "ABC", "XYZ"])

    def test_two_runs_are_byte_identical_sorted_and_path_free(self):
        repo = make_repo(self.tmp / "android-app", GRADLE_FILES, subjects=["DEV-1 a", "DEV-2 b", "DEV-3 c"])
        _, first = detect(repo)
        _, second = detect(repo)
        self.assertEqual(first, second)
        self.assertEqual(first, json.dumps(json.loads(first), sort_keys=True, indent=2) + "\n")
        self.assertNotIn(str(self.tmp), first)
        self.assertNotIn(str(self.tmp.resolve()), first)

    def test_missing_repo_is_a_usage_error(self):
        proc = subprocess.run([sys.executable, str(DETECT), str(self.tmp / "nope")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
