"""select() over change lists and check_verify() over a synthetic CHECK_TASKS;
changed_files() over a temp repo with base, dirty and untracked state."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import test_sectors as ts

TOOLS_ROOT = Path(__file__).resolve().parent.parent

CONFIG = {
    "shared_build_files": ["settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle"],
    "rdd": {"exempt_globs": ["**/*.md", "docs/**"]},
    "test_sectors": {
        "base_ref": "main",
        "full_required_globs": ["app/libs/**", "**/proguard*.pro"],
        "credential_gate": {"name": "sdk_key", "task_prefixes": [":payment:vendor-a:", ":app:"],
                            "local_properties_key": "vendor-a.repo.xapikey", "env_var": "VENDOR_A_REPO_XAPIKEY"},
        "sectors": [
            {"paths": ["domain/"], "tasks": [":domain:test"]},
            {"paths": ["payment/"], "tasks": [":payment:api:test"]},
            {"paths": ["payment/vendor-a/"], "tasks": [":payment:vendor-a:testDebugUnitTest"]},
            {"paths": ["app/"], "tasks": [":app:test_prod_NON_GMSReleaseUnitTest"]},
        ],
    },
}

VERIFY_SH = """
CHECK_TASKS=(
  # comment with :nada
  :domain:test
  :payment:api:test :payment:vendor-a:testDebugUnitTest
  :app:test_prod_NON_GMSReleaseUnitTest
)
"""


def _changed(*paths):
    return [{"path": p, "source": "committed"} for p in paths]


class SelectTests(unittest.TestCase):
    def test_longest_prefix_wins(self):
        result = ts.select(_changed("payment/vendor-a/X.kt"), CONFIG)
        self.assertEqual(result["tasks"], [":payment:vendor-a:testDebugUnitTest"])
        self.assertEqual(result["sectors_hit"], ["payment/vendor-a/"])
        self.assertFalse(result["full_required"])

    def test_union_of_sectors(self):
        result = ts.select(_changed("domain/A.kt", "payment/api/B.kt"), CONFIG)
        self.assertEqual(result["tasks"], [":domain:test", ":payment:api:test"])

    def test_docs_only_selects_nothing_and_is_not_full(self):
        # negative control
        result = ts.select(_changed("README.md", "docs/x.md"), CONFIG)
        self.assertEqual(result["tasks"], [])
        self.assertFalse(result["full_required"])
        self.assertEqual(result["ignored_files"], ["README.md", "docs/x.md"])

    def test_shared_build_file_forces_full(self):
        result = ts.select(_changed("settings.gradle", "domain/A.kt"), CONFIG)
        self.assertTrue(result["full_required"])
        self.assertIn({"path": "settings.gradle", "rule": "shared_build_files"}, result["full_required_reasons"])

    def test_full_globs_and_unmapped_force_full(self):
        for path in ("app/libs/x.aar", "app/proguard-rules.pro", "mystery/Z.kt"):
            result = ts.select(_changed(path), CONFIG)
            self.assertTrue(result["full_required"], path)
        self.assertEqual(ts.select(_changed("mystery/Z.kt"), CONFIG)["unmapped_files"], ["mystery/Z.kt"])

    def test_credential_gated_tasks_are_listed(self):
        result = ts.select(_changed("app/Foo.kt", "domain/A.kt"), CONFIG)
        self.assertEqual(result["credential_gated_tasks"], [":app:test_prod_NON_GMSReleaseUnitTest"])

    def test_empty_sector_map_makes_everything_full(self):
        result = ts.select(_changed("domain/A.kt"), {"test_sectors": {"sectors": []}})
        self.assertTrue(result["full_required"])

    def test_determinism(self):
        a = json.dumps(ts.select(_changed("payment/api/B.kt", "domain/A.kt"), CONFIG), sort_keys=True)
        b = json.dumps(ts.select(_changed("domain/A.kt", "payment/api/B.kt"), CONFIG), sort_keys=True)
        self.assertEqual(a, b)


class CheckVerifyTests(unittest.TestCase):
    def test_all_mapped_tasks_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text(VERIFY_SH, encoding="utf-8")
            result = ts.check_verify(CONFIG, verify)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["unknown_tasks"], [])

    def test_planted_unknown_task_is_reported(self):
        # negative control
        cfg = json.loads(json.dumps(CONFIG))
        cfg["test_sectors"]["sectors"].append({"paths": ["x/"], "tasks": [":x:bogus"]})
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text(VERIFY_SH, encoding="utf-8")
            result = ts.check_verify(cfg, verify)
            self.assertFalse(result["ok"])
            self.assertEqual(result["unknown_tasks"], [":x:bogus"])

    def test_parse_ignores_comments(self):
        self.assertNotIn(":nada", ts.parse_check_tasks(VERIFY_SH))

    @unittest.skipUnless(os.environ.get("METODO_REPO"), "integracion: exige METODO_REPO")
    def test_example_map_matches_real_verify(self):
        cfg = json.loads((TOOLS_ROOT / "config" / "examples" / "critical-flow" / "project.json").read_text(encoding="utf-8"))
        result = ts.check_verify(cfg, Path(os.environ["METODO_REPO"]) / "tools" / "verify" / "verify.sh")
        self.assertTrue(result["ok"], result["unknown_tasks"])


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class ChangedFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sectors-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "domain").mkdir()
        (self.repo / "domain" / "A.kt").write_text("a\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "domain" / "A.kt").write_text("b\n", encoding="utf-8")
        _git(self.repo, "commit", "-q", "-am", "change")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_committed_dirty_and_untracked_sources(self):
        (self.repo / "domain" / "A.kt").write_text("c\n", encoding="utf-8")
        (self.repo / "payment").mkdir()
        (self.repo / "payment" / "New.kt").write_text("n\n", encoding="utf-8")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "x").write_text("x", encoding="utf-8")
        changed, merge_base, ok = ts.changed_files(self.repo, "main", committed_only=False)
        self.assertTrue(ok)
        self.assertEqual(changed, [{"path": "domain/A.kt", "source": "committed"}, {"path": "payment/New.kt", "source": "untracked"}])
        committed, _, _ = ts.changed_files(self.repo, "main", committed_only=True)
        self.assertEqual(committed, [{"path": "domain/A.kt", "source": "committed"}])

    def test_unresolvable_base_is_reported_not_fatal(self):
        changed, merge_base, ok = ts.changed_files(self.repo, "origin/nope", committed_only=True)
        self.assertFalse(ok)
        self.assertEqual(changed, [])
        self.assertIsNone(merge_base)


class AbsentProjectTasks(unittest.TestCase):
    """A sector can name a module another branch has and this one does not.

    Asking Gradle for it breaks the configuration, so the task is dropped; and
    the drop forces the full battery, because a test that does not run is not
    a green test.
    """

    def test_task_project_splits_on_the_last_segment(self):
        self.assertEqual(ts.task_project(":payment:api:test"), ":payment:api")
        self.assertEqual(ts.task_project(":domain:test"), ":domain")
        self.assertEqual(ts.task_project("lint"), ":")

    def test_absent_task_is_dropped_and_forces_the_full_battery(self):
        result = ts.select(_changed("payment/api/Gateway.kt"), CONFIG, projects={":domain"})
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["absent_project_tasks"], [":payment:api:test"])
        self.assertTrue(result["full_required"])
        self.assertIn("task_project_absent", [r["rule"] for r in result["full_required_reasons"]])

    def test_present_task_survives_and_keeps_the_shortcut(self):
        result = ts.select(_changed("domain/Money.kt"), CONFIG, projects={":domain"})
        self.assertEqual(result["tasks"], [":domain:test"])
        self.assertEqual(result["absent_project_tasks"], [])
        self.assertFalse(result["full_required"])

    def test_no_project_set_disables_the_filter(self):
        result = ts.select(_changed("domain/Money.kt"), CONFIG, projects=None)
        self.assertEqual(result["tasks"], [":domain:test"])
        self.assertEqual(result["absent_project_tasks"], [])

    def test_check_verify_separates_lineage_from_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text(VERIFY_SH, encoding="utf-8")
            absent_lineage = ts.check_verify(CONFIG, verify, projects={":domain", ":payment:api", ":app"})
            self.assertTrue(absent_lineage["ok"])
            self.assertEqual(absent_lineage["absent_project_tasks"], [":payment:vendor-a:testDebugUnitTest"])
            self.assertEqual(absent_lineage["unknown_tasks"], [])

    def test_check_verify_still_catches_real_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text("CHECK_TASKS=(\n  :domain:test\n)\n", encoding="utf-8")
            drift = ts.check_verify(CONFIG, verify, projects={":domain", ":payment:api", ":payment:vendor-a", ":app"})
            self.assertFalse(drift["ok"])
            self.assertIn(":payment:api:test", drift["unknown_tasks"])

    def test_included_projects_reads_settings_gradle(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "settings.gradle").write_text(
                "include ':domain'\ninclude(':payment:api')\n// include ':ghost'\n", encoding="utf-8")
            found = ts.included_projects(Path(tmp))
            self.assertIn(":domain", found)
            self.assertIn(":payment:api", found)

    def test_included_projects_is_none_without_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ts.included_projects(Path(tmp)))


VERIFY_SH_CHANGED = """
  while IFS= read -r f; do
    case "$f" in
      domain/*)                 add_module_task ":domain:test";;
      payment/*)                add_module_task ":payment:api:test";;
    esac
  done < <(git diff --name-only)

CHECK_TASKS=(
  :domain:test
  :payment:api:test :payment:vendor-a:testDebugUnitTest
  :app:test_prod_NON_GMSReleaseUnitTest
)
"""


class ChangedModeDrift(unittest.TestCase):
    """The drift that bites in silence: the full battery names the module's
    task and `--changed` mode has no `case` arm for its path, so a change to
    only that module prints green without running a test."""

    def _check(self, text, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text(text, encoding="utf-8")
            return ts.check_verify(CONFIG, verify, **kw)

    def test_arms_are_parsed_as_prefixes(self):
        self.assertEqual(ts.parse_changed_arms(VERIFY_SH_CHANGED), ["domain/", "payment/"])

    def test_module_without_arm_is_a_gap(self):
        result = self._check(VERIFY_SH_CHANGED, projects={":domain", ":payment:api", ":payment:vendor-a", ":app"})
        self.assertFalse(result["ok"])
        self.assertEqual([g["path"] for g in result["changed_mode_gaps"]], ["app/"])

    def test_no_changed_mode_is_not_drift(self):
        result = self._check(VERIFY_SH, projects={":domain", ":payment:api", ":payment:vendor-a", ":app"})
        self.assertEqual(result["changed_mode"], "absent")
        self.assertEqual(result["changed_mode_gaps"], [])
        self.assertTrue(result["ok"])

    def test_lint_only_sector_is_not_a_gap(self):
        config = json.loads(json.dumps(CONFIG))
        config["test_sectors"]["sectors"] = [{"paths": ["ui/"], "tasks": [":ui:lintRelease"]}]
        with tempfile.TemporaryDirectory() as tmp:
            verify = Path(tmp) / "verify.sh"
            verify.write_text(VERIFY_SH_CHANGED.replace("CHECK_TASKS=(", "CHECK_TASKS=(\n  :ui:lintRelease"), encoding="utf-8")
            result = ts.check_verify(config, verify, projects={":ui", ":domain", ":payment:api"})
        self.assertEqual(result["changed_mode_gaps"], [])

    def test_is_test_task_classifies_on_the_last_segment(self):
        self.assertTrue(ts.is_test_task(":domain:test"))
        self.assertTrue(ts.is_test_task(":app:test_prod_GMSReleaseUnitTest"))
        self.assertTrue(ts.is_test_task(":services:testReleaseUnitTest"))
        self.assertFalse(ts.is_test_task(":designsystem:lintRelease"))
        self.assertFalse(ts.is_test_task(":app:verifyEmvAssets"))
        self.assertFalse(ts.is_test_task(":app:depsDiff"))
