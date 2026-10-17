"""bin/adopt.sh over a throwaway tools instance (bin/adopt.sh,
lib/detect_repo.py and config/ copied to a temp dir) and a throwaway target
repo: a never-adapted project.json (missing or byte-identical to the kit's
template) is rebuilt generically from detection, a hand-adapted one is
preserved, --critical-flow-example keeps the critical-flow start, --answers wins over
detection, and running against the kit itself is refused."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
ADOPT = TOOLS_ROOT / "bin" / "adopt.sh"
DETECT = TOOLS_ROOT / "lib" / "detect_repo.py"
BUILD_FILES = TOOLS_ROOT / "lib" / "build_files.py"
KIT_CONFIG = TOOLS_ROOT / "config"

EXAMPLE_MARKERS = ("Capacity", "Booking status", "booking/", "ui/booking", "ARCH-006", "origin/develop",
                   "\"DEV\"", "\"BOOK\"", "Repository*.kt")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path: Path, files: dict[str, str], subjects=("init",), branch="main") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(path, "add", "-A")
    for subject in subjects:
        _git(path, "commit", "-q", "--allow-empty", "-m", subject)
    return path


def make_tools(root: Path, template: bytes, with_config: bool = True) -> Path:
    """A tools directory with the scripts under test and, optionally, a
    config/project.json holding `template`."""
    (root / "bin").mkdir(parents=True)
    (root / "lib").mkdir()
    shutil.copy2(ADOPT, root / "bin" / "adopt.sh")
    if DETECT.exists():
        shutil.copy2(DETECT, root / "lib" / "detect_repo.py")
    if BUILD_FILES.exists():
        shutil.copy2(BUILD_FILES, root / "lib" / "build_files.py")
    (root / "config" / "examples").mkdir(parents=True)
    shutil.copytree(KIT_CONFIG / "examples" / "critical-flow", root / "config" / "examples" / "critical-flow")
    for name in ("dep-boundaries.json", "invariants-checks.json", "duplication-targets.json",
                 "property-hierarchy-map.json"):
        shutil.copy2(KIT_CONFIG / name, root / "config" / name)
    if with_config:
        (root / "config" / "project.json").write_bytes(template)
    return root


PYTHON_FILES = {"pyproject.toml": "[project]\n", "pkg/a.py": "\n", "tests/test_a.py": "\n"}


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adopt-"))
        self.template = (KIT_CONFIG / "project.json").read_bytes()
        # a snapshot of the kit's template, so a parallel edit cannot race the test
        self.kit = make_tools(self.tmp / "kit-snapshot" / "03-tools", self.template)
        self.instance = make_tools(self.tmp / "acme-tools", self.template)
        self.repo = make_repo(self.tmp / "acme", PYTHON_FILES)
        self.config = self.instance / "config" / "project.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, tools: Path, *extra: str, repo: Path | None = None):
        return subprocess.run(
            ["bash", str(tools / "bin" / "adopt.sh"), str(repo or self.repo), "~/acme-audit",
             "--kit", str(self.kit), *extra],
            capture_output=True, text=True)

    def _config(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def _assert_generic(self, config: dict):
        text = json.dumps(config, ensure_ascii=False)
        for marker in EXAMPLE_MARKERS:
            self.assertNotIn(marker, text, f"example value survived: {marker}")
        self.assertEqual(config["docs_root"], "~/acme-audit")
        self.assertEqual(config["property_order"][0], "Correctness")
        self.assertTrue(config["critical_properties"])
        self.assertTrue(set(config["critical_properties"]) <= set(config["property_order"]))
        self.assertEqual(config["critical_paths"], [])
        self.assertEqual(config["language"], "python")
        self.assertEqual(config["shared_build_files"], ["pyproject.toml"])
        self.assertEqual(config["rdd"]["lens_paths"], {})
        self.assertIn("tests/**", config["rdd"]["tests_globs"])
        self.assertNotIn("**/src/test/**", config["rdd"]["tests_globs"])
        self.assertEqual(config["test_sectors"]["sectors"], [])
        self.assertEqual(config["test_sectors"]["base_ref"], "main")
        self.assertIn("memory", config)

    def test_template_identical_config_is_rebuilt_generically(self):
        proc = self._run(self.instance)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._assert_generic(self._config())

    def test_missing_config_is_rebuilt_generically(self):
        self.config.unlink()
        proc = self._run(self.instance)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._assert_generic(self._config())

    def test_hand_adapted_config_is_preserved_and_only_missing_keys_filled(self):
        hand = {"docs_root": "~/old", "property_order": ["Capacity", "Ledger"], "critical_paths": ["core/seats/"],
                "language": "go", "ticket_keys": ["ACME"]}
        self.config.write_text(json.dumps(hand), encoding="utf-8")
        proc = self._run(self.instance)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        self.assertEqual(config["property_order"], ["Capacity", "Ledger"])
        self.assertEqual(config["critical_paths"], ["core/seats/"])
        self.assertEqual(config["language"], "go")
        self.assertEqual(config["ticket_keys"], ["ACME"])
        self.assertEqual(config["docs_root"], "~/acme-audit")
        self.assertNotIn("critical_properties", config, "generic critical set must not mix with a hand hierarchy")
        self.assertEqual(config["shared_build_files"], ["pyproject.toml"])
        self.assertIn("rdd", config)

    def test_gradle_repo_gets_the_full_gradle_glob_set(self):
        repo = make_repo(self.tmp / "android", {"settings.gradle.kts": "\n", "app/build.gradle.kts": "\n",
                                                 "app/src/main/kotlin/A.kt": "class A\n"})
        proc = self._run(self.instance, repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        for glob in ("**/*.gradle.kts", "**/gradlew", "**/gradle/wrapper/**", "**/gradle/verification-metadata.xml",
                     "**/buildSrc/**", "**/build-logic/**", "**/gradle.properties", "**/gradle/*.versions.toml"):
            self.assertIn(glob, config["shared_build_files"], glob)
            self.assertIn(glob, config["test_sectors"]["full_required_globs"], glob)
        self.assertNotIn("**/build.gradle", config["test_sectors"]["full_required_globs"])

    def test_critical_flow_example_keeps_its_start(self):
        proc = self._run(self.instance, "--critical-flow-example")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        template = json.loads((KIT_CONFIG / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(config["property_order"], template["property_order"])  # setdefault keeps what is there
        self.assertIn("booking/", config["critical_paths"])
        self.assertEqual(config["ticket_keys"], ["DEV", "BOOK"])
        self.assertEqual(config["language"], "kotlin")
        self.assertEqual(config["docs_root"], "~/acme-audit")
        example = KIT_CONFIG / "examples" / "critical-flow" / "dep-boundaries.json"
        self.assertEqual((self.instance / "config" / "dep-boundaries.json").read_bytes(), example.read_bytes())

    def test_answers_win_over_detection(self):
        repo = make_repo(self.tmp / "tickets", PYTHON_FILES, subjects=["DEV-1 a", "DEV-2 b", "DEV-3 c"])
        answers = {"ticket_keys": ["ABC"], "language": "swift", "critical_paths": ["billing/"],
                   "property_order": ["Capacity", "Integrity", "UX"], "critical_properties": ["Capacity"]}
        answers_file = self.tmp / "answers.json"
        answers_file.write_text(json.dumps(answers), encoding="utf-8")
        proc = self._run(self.instance, "--answers", str(answers_file), repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        for key, value in answers.items():
            self.assertEqual(config[key], value, key)

    def test_answered_hierarchy_without_critical_set_makes_every_property_critical(self):
        proc = self._run(self.instance, "--answers", '{"property_order": ["Capacity", "UX"]}')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._config()["critical_properties"], ["Capacity", "UX"])

    def test_deprecated_money_paths_answer_lands_as_critical_paths(self):
        proc = self._run(self.instance, "--answers", '{"money_paths": ["billing/"]}')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        self.assertEqual(config["critical_paths"], ["billing/"])
        self.assertNotIn("money_paths", config)

    def test_hand_config_with_deprecated_money_paths_gets_no_empty_critical_paths(self):
        hand = {"docs_root": "~/old", "property_order": ["Capacity", "Ledger"], "money_paths": ["core/seats/"]}
        self.config.write_text(json.dumps(hand), encoding="utf-8")
        proc = self._run(self.instance)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = self._config()
        self.assertEqual(config["money_paths"], ["core/seats/"])
        self.assertNotIn("critical_paths", config)

    def test_detected_ticket_keys_land_without_answers(self):
        repo = make_repo(self.tmp / "tickets", PYTHON_FILES, subjects=["ABC-1 a", "ABC-2 b", "ABC-3 c"])
        proc = self._run(self.instance, "--answers", '{"language": "python"}', repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._config()["ticket_keys"], ["ABC"])

    def test_bad_answers_are_refused_without_writing(self):
        before = self.config.read_bytes()
        for bad in ('{"unknown_key": 1}', '{"critical_properties": ["Nope"]}', '{"money_paths": "x/"}', "not json"):
            proc = self._run(self.instance, "--answers", bad)
            self.assertEqual(proc.returncode, 2, bad + proc.stdout + proc.stderr)
            self.assertEqual(self.config.read_bytes(), before, bad)

    def test_dry_run_writes_nothing_and_prints_the_config(self):
        before = self.config.read_bytes()
        proc = self._run(self.instance, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn('"Correctness"', proc.stdout)

    def test_pending_human_steps_are_printed_deterministically(self):
        first = self._run(self.instance, "--dry-run")
        second = self._run(self.instance, "--dry-run")
        self.assertEqual(first.stdout, second.stdout)
        out = first.stdout
        self.assertIn("pending human steps", out)
        for needle in ("property_order", "critical_properties", "critical_paths", "invariants.md", "CONVENTIONS.md",
                       "dep-boundaries.json", "Owner"):
            self.assertIn(needle, out)
        self.assertIn("bin/metrics.sh", out)
        self.assertIn("--save", out)
        self.assertNotIn("Typical time: an afternoon", out, "the whole checklist is no longer dumped")

    def test_refuses_to_adapt_the_kit_itself(self):
        kit_repo = self.tmp / "methodology"
        (kit_repo / "01-roles").mkdir(parents=True)
        (kit_repo / "05-adopt").mkdir()
        kit_tools = make_tools(kit_repo / "03-tools", self.template)
        kit_config = kit_tools / "config" / "project.json"
        proc = subprocess.run(["bash", str(kit_tools / "bin" / "adopt.sh"), str(self.repo), "~/acme-audit"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("sync-instance.sh", proc.stderr)
        self.assertIn("--allow-kit", proc.stderr)
        self.assertEqual(kit_config.read_bytes(), self.template)
        dry = subprocess.run(["bash", str(kit_tools / "bin" / "adopt.sh"), str(self.repo), "~/acme-audit",
                              "--dry-run"], capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual(kit_config.read_bytes(), self.template)
        allowed = subprocess.run(["bash", str(kit_tools / "bin" / "adopt.sh"), str(self.repo), "~/acme-audit",
                                  "--allow-kit"], capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(json.loads(kit_config.read_text(encoding="utf-8"))["property_order"][0], "Correctness")


if __name__ == "__main__":
    unittest.main()
