"""S12: every Gradle build file is owner-only and forces the full battery.

One test per path family. Each family path is checked against the four
consumers of `shared_build_files`, under three configs (no config = the
built-in default, the kit template, the critical-flow example):

- hooks/guard_paths.py (Claude Code, and pi through the same hook): a
  subagent Edit/Write is denied, the main session gets `ask`;
- lib/role_contract_validator.py: a real commit range touching it FAILs;
- lib/rdd_risk.py: tier high with owner_gate;
- lib/test_sectors.py: full_required, through the shared_build_files rule
  and through full_required_globs on their own (a sector maps every path,
  so `unmapped` cannot be the reason).

Negative controls (source, docs, README) stay unguarded, and every exact
path of the old five-file default stays guarded."""
import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib import rdd_risk
from lib import role_contract_validator as rcv
from lib import test_sectors as ts

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOKS = TOOLS_ROOT / "hooks"
DETECT = TOOLS_ROOT / "lib" / "detect_repo.py"

FAMILIES = {
    "wrapper_scripts": ["gradlew", "gradlew.bat"],
    "wrapper_dir": ["gradle/wrapper/gradle-wrapper.jar", "gradle/wrapper/gradle-wrapper.properties"],
    "verification": ["gradle/verification-metadata.xml", "gradle/verification-keyring.keys",
                     "gradle/verification-keyring.gpg"],
    "buildsrc": ["buildSrc/build.gradle.kts", "buildSrc/src/main/kotlin/Conventions.kt"],
    "build_logic": ["build-logic/settings.gradle.kts", "build-logic/convention/build.gradle.kts",
                    "build-logic/convention/src/main/kotlin/AndroidLibraryConventionPlugin.kt"],
    "module_build": ["build.gradle.kts", "app/build.gradle.kts", "feature/login/build.gradle.kts",
                     "core/data/build.gradle"],
    "settings_kts": ["settings.gradle.kts"],
    "subproject_properties": ["feature/login/gradle.properties", "core/gradle.properties"],
    "version_catalog": ["gradle/libs.versions.toml", "gradle/plugins.versions.toml"],
}
OLD_DEFAULT = ["settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle"]
NEGATIVE = ["app/src/main/kotlin/Foo.kt", "docs/gradle.md", "README.md"]
MAP_ALL = [{"paths": [""], "tasks": [":app:test"]}]


def _load(rel: str) -> dict:
    return json.loads((TOOLS_ROOT / rel).read_text(encoding="utf-8"))


CONFIGS = {
    "default": {},
    "kit-template": _load("config/project.json"),
    "critical-flow-example": _load("config/examples/critical-flow/project.json"),
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _sectors_config(config: dict) -> dict:
    """The same config, with one sector mapping every path: full_required can
    then come only from shared_build_files or full_required_globs."""
    out = copy.deepcopy(config)
    out.setdefault("test_sectors", {})["sectors"] = copy.deepcopy(MAP_ALL)
    return out


class GradleGuardFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gradle-guard-"))
        cls.repo = cls.tmp / "repo"
        cls.repo.mkdir()
        _git(cls.repo, "init", "-q", "-b", "main")
        _git(cls.repo, "config", "user.email", "t@example.com")
        _git(cls.repo, "config", "user.name", "t")
        _git(cls.repo, "config", "commit.gpgsign", "false")
        (cls.repo / "base.txt").write_text("base\n", encoding="utf-8")
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-q", "-m", "base")
        cls.base = _git(cls.repo, "rev-parse", "HEAD")
        cls.configs_dir = cls.tmp / "configs"
        cls.configs_dir.mkdir()
        cls.config_paths = {}
        for name, config in CONFIGS.items():
            if not config:
                # a path that does not exist: load_config() / load_project_config() return {}
                cls.config_paths[name] = cls.configs_dir / "absent.json"
                continue
            path = cls.configs_dir / f"{name}.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            cls.config_paths[name] = path
        cls.commits: dict[str, str] = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------ consumers
    def commit_touching(self, paths: list[str]) -> str:
        key = "\n".join(sorted(paths))
        if key not in self.commits:
            _git(self.repo, "checkout", "-q", "--detach", self.base)
            for rel in paths:
                target = self.repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x\n", encoding="utf-8")
            _git(self.repo, "add", "-A")
            _git(self.repo, "commit", "-q", "-m", "touch")
            self.commits[key] = _git(self.repo, "rev-parse", "HEAD")
        return self.commits[key]

    def run_guard(self, rel: str, config_name: str, subagent: bool) -> dict:
        payload = {"session_id": f"s-{config_name}", "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                   "tool_name": "Edit", "tool_input": {"file_path": str(self.repo / rel)}}
        if subagent:
            payload.update({"agent_type": "generic-proposer", "agent_id": "a1"})
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_paths[config_name]),
                   METODO_HOOKS_DIR=str(self.tmp / "hooks-out"), METODO_RDD_DIR=str(self.tmp / "rdd"),
                   CLAUDE_PROJECT_DIR=str(self.repo))
        proc = subprocess.run([sys.executable, str(HOOKS / "guard_paths.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out

    @staticmethod
    def decision(out: dict):
        return (out.get("hookSpecificOutput") or {}).get("permissionDecision")

    def run_validator(self, paths: list[str], config_name: str) -> tuple[int, dict]:
        head = self.commit_touching(paths)
        contract = self.tmp / "permissive.contract.json"
        contract.write_text(json.dumps({"agent": "permissive", "may_write": []}), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rcv.main(["--contract", str(contract), "--repo", str(self.repo),
                             "--range", f"{self.base}..{head}", "--config", str(self.config_paths[config_name])])
        return code, json.loads(buf.getvalue())

    # ------------------------------------------------------------ assertions
    def assert_guarded(self, paths: list[str]):
        for name, config in CONFIGS.items():
            for rel in paths:
                with self.subTest(consumer="guard_paths", config=name, path=rel):
                    self.assertEqual(self.decision(self.run_guard(rel, name, subagent=True)), "deny")
                    self.assertEqual(self.decision(self.run_guard(rel, name, subagent=False)), "ask")
                with self.subTest(consumer="rdd_risk", config=name, path=rel):
                    risk = rdd_risk.derive({"touched_paths": [rel], "routing": "sonnet", "what_it_risks": "none",
                                            "added": 1, "removed": 0, "has_change_card": True}, config)
                    self.assertEqual(risk["tier"], "high")
                    self.assertTrue(risk["owner_gate"])
                with self.subTest(consumer="test_sectors", config=name, path=rel):
                    result = ts.select([{"path": rel, "source": "committed"}], _sectors_config(config))
                    rules = {r["rule"] for r in result["full_required_reasons"] if r["path"] == rel}
                    self.assertTrue(result["full_required"])
                    self.assertIn("shared_build_files", rules)
                    self.assertIn("full_required_globs", rules)
                    self.assertNotIn("unmapped", rules)
            with self.subTest(consumer="role_contract_validator", config=name, paths=paths):
                code, result = self.run_validator(paths, name)
                self.assertEqual(code, 1)
                self.assertEqual(result["verdict"], "FAIL")
                self.assertEqual(sorted(h["path"] for h in result["forbidden_hits"]), sorted(paths))


class GradleFamilyTests(GradleGuardFixture):
    def test_wrapper_scripts(self):
        self.assert_guarded(FAMILIES["wrapper_scripts"])

    def test_wrapper_dir(self):
        self.assert_guarded(FAMILIES["wrapper_dir"])

    def test_verification_metadata_and_keyring(self):
        self.assert_guarded(FAMILIES["verification"])

    def test_buildsrc(self):
        self.assert_guarded(FAMILIES["buildsrc"])

    def test_build_logic(self):
        self.assert_guarded(FAMILIES["build_logic"])

    def test_module_build_scripts(self):
        self.assert_guarded(FAMILIES["module_build"])

    def test_settings_gradle_kts(self):
        self.assert_guarded(FAMILIES["settings_kts"])

    def test_subproject_gradle_properties(self):
        self.assert_guarded(FAMILIES["subproject_properties"])

    def test_version_catalogs(self):
        self.assert_guarded(FAMILIES["version_catalog"])

    def test_old_default_exact_paths_still_guarded(self):
        # regression: the five exact paths of the previous default
        self.assert_guarded(OLD_DEFAULT)

    def test_dotted_and_case_variants_are_guarded(self):
        # a pi path is relative and may be dotted; macOS is case-insensitive
        for name in CONFIGS:
            for rel in ("./gradlew", "app/../gradlew", "GRADLEW", "Gradle/Wrapper/gradle-wrapper.jar"):
                with self.subTest(config=name, path=rel):
                    payload_out = self.run_guard_relative(rel, name)
                    self.assertEqual(self.decision(payload_out), "deny")

    def run_guard_relative(self, rel: str, config_name: str) -> dict:
        payload = {"session_id": "s-rel", "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                   "tool_name": "Write", "tool_input": {"file_path": rel},
                   "agent_type": "generic-proposer", "agent_id": "a1"}
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_paths[config_name]),
                   METODO_HOOKS_DIR=str(self.tmp / "hooks-out"), METODO_RDD_DIR=str(self.tmp / "rdd"),
                   CLAUDE_PROJECT_DIR=str(self.repo))
        proc = subprocess.run([sys.executable, str(HOOKS / "guard_paths.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}


class NegativeControlTests(GradleGuardFixture):
    def test_source_docs_and_readme_are_not_build_files(self):
        for name, config in CONFIGS.items():
            for rel in NEGATIVE:
                with self.subTest(consumer="guard_paths", config=name, path=rel):
                    self.assertNotIn(self.decision(self.run_guard(rel, name, subagent=True)), ("deny", "ask"))
                    self.assertEqual(self.run_guard(rel, name, subagent=False), {})
                with self.subTest(consumer="rdd_risk", config=name, path=rel):
                    risk = rdd_risk.derive({"touched_paths": [rel], "routing": "sonnet", "what_it_risks": "none",
                                            "added": 1, "removed": 0, "has_change_card": True}, config)
                    self.assertFalse(risk["owner_gate"])
                    self.assertNotEqual(risk["tier"], "high")
                with self.subTest(consumer="test_sectors", config=name, path=rel):
                    result = ts.select([{"path": rel, "source": "committed"}], _sectors_config(config))
                    self.assertFalse(result["full_required"], result["full_required_reasons"])
            with self.subTest(consumer="role_contract_validator", config=name):
                code, result = self.run_validator(NEGATIVE, name)
                self.assertEqual(code, 0)
                self.assertEqual(result["forbidden_hits"], [])

    def test_claude_rule_unchanged(self):
        for name in CONFIGS:
            with self.subTest(config=name):
                self.assertEqual(self.decision(self.run_guard(".claude/agents/x.md", name, subagent=True)), "deny")
                # the main session is not asked on .claude/ (unchanged)
                self.assertEqual(self.run_guard(".claude/agents/x.md", name, subagent=False), {})


class DetectedConfigTests(unittest.TestCase):
    """An adapted config gets the full set: detect_repo.py emits globs for a
    detected Gradle repo, and they guard every family."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gradle-detect-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detected_gradle_repo_guards_every_family(self):
        repo = self.tmp / "android"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        for rel in ("settings.gradle.kts", "build.gradle.kts", "app/build.gradle.kts", "app/src/main/kotlin/A.kt"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("\n", encoding="utf-8")
        _git(repo, "add", "-A")
        proc = subprocess.run([sys.executable, str(DETECT), str(repo)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        config = {"shared_build_files": json.loads(proc.stdout)["shared_build_files"]}
        for family, paths in FAMILIES.items():
            for rel in paths:
                with self.subTest(family=family, path=rel):
                    result = rcv.evaluate({"agent": "p", "may_write": []}, [rel], [],
                                          rcv.always_forbidden_patterns(config))
                    self.assertEqual(result["verdict"], "FAIL")
        for rel in NEGATIVE:
            with self.subTest(path=rel):
                result = rcv.evaluate({"agent": "p", "may_write": []}, [rel], [], rcv.always_forbidden_patterns(config))
                self.assertEqual(result["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()

class GuardSurvivesAPartialInstance(unittest.TestCase):
    """Verifier advisory 1: an instance missing lib/build_files.py must not turn
    the absolute subagent deny into a crash (fail open)."""

    def test_subagent_build_file_deny_holds_without_build_files_module(self):
        tmp = Path(tempfile.mkdtemp(prefix="gradle-guard-partial-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        inst = tmp / "inst"
        shutil.copytree(TOOLS_ROOT / "hooks", inst / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(TOOLS_ROOT / "lib", inst / "lib", ignore=shutil.ignore_patterns("__pycache__", "build_files.py"))
        repo = tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        for rel in ("build.gradle", "gradlew", "buildSrc/src/main/kotlin/X.kt"):
            payload = {"session_id": "s", "cwd": str(repo), "hook_event_name": "PreToolUse", "tool_name": "Edit",
                       "tool_input": {"file_path": str(repo / rel)}, "agent_type": "generic-proposer", "agent_id": "a1"}
            env = dict(os.environ, METODO_TOOLS=str(inst), METODO_PROJECT_CONFIG=str(tmp / "absent.json"),
                       METODO_HOOKS_DIR=str(tmp / "hooks-out"), METODO_RDD_DIR=str(tmp / "rdd"), CLAUDE_PROJECT_DIR=str(repo))
            proc = subprocess.run([sys.executable, str(inst / "hooks" / "guard_paths.py")], input=json.dumps(payload),
                                  capture_output=True, text=True, env=env)
            with self.subTest(path=rel):
                self.assertEqual(proc.returncode, 0, proc.stderr)
                out = json.loads(proc.stdout) if proc.stdout.strip() else {}
                self.assertEqual((out.get("hookSpecificOutput") or {}).get("permissionDecision"), "deny", out)


class FullRequiredGlobsUseTheSharedMatcher(unittest.TestCase):
    """Verifier advisory 3: full_required_globs matches like shared_build_files
    (normalized, case-insensitive), so the reason is reported for both rules."""

    def test_odd_spellings_hit_full_required_globs(self):
        config = {"shared_build_files": ["nothing-matches"],
                  "test_sectors": {"full_required_globs": ["**/gradlew", "**/gradle/wrapper/**"], "sectors": MAP_ALL}}
        for path in ("GRADLEW", "app/../gradlew", "gradle\\wrapper\\x"):
            with self.subTest(path=path):
                result = ts.select([{"path": path, "added": 1, "removed": 0}], config)
                self.assertIn("full_required_globs", [r["rule"] for r in result["full_required_reasons"]], result)


class FallbackMirrorsTheModule(unittest.TestCase):
    def test_hook_fallback_glob_set_equals_build_files(self):
        from lib import build_files
        import ast
        tree = ast.parse((HOOKS / "_common.py").read_text(encoding="utf-8"))
        fallback = [ast.literal_eval(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_GLOBS" for t in n.targets)]
        self.assertEqual(fallback, [tuple(build_files.GRADLE_BUILD_GLOBS)])
