"""Full-loop smoke (lib/smoke_loop.py) over a throwaway git repo: change card
-> receipt start -> captures -> finalize on a local clone, with the user's
repo compared before and after. One test per rule; the smoke runs once per
class and the determinism test runs it a second time."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SMOKE = TOOLS_ROOT / "lib" / "smoke_loop.py"
FIXTURE_CONFIG = TOOLS_ROOT / "tests" / "fixtures" / "smoke" / "project.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def make_user_repo(root: Path) -> Path:
    repo = root / "user-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "owner@example.com")
    _git(repo, "config", "user.name", "Owner")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "branch", "feature/other")
    # A dirty state the smoke must leave exactly as it found it.
    (repo / "notes.txt").write_text("untracked\n", encoding="utf-8")
    (repo / "README.md").write_text("# fixture\nlocal edit\n", encoding="utf-8")
    return repo


def snapshot(repo: Path) -> dict:
    return {
        "status": _git(repo, "--no-optional-locks", "status", "--porcelain"),
        "head": _git(repo, "rev-parse", "HEAD"),
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
    }


def run_smoke(repo: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, METODO_MEMORY="off", METODO_PROJECT_CONFIG=str(FIXTURE_CONFIG))
    return subprocess.run(["python3", str(SMOKE), str(repo), "--out", str(out), *extra],
                          capture_output=True, text=True, env=env, cwd=str(TOOLS_ROOT))


class SmokeLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="smoke-loop-test-"))
        cls.repo = make_user_repo(cls.tmp)
        cls.before = snapshot(cls.repo)
        cls.out = cls.tmp / "report-1.json"
        cls.proc = run_smoke(cls.repo, cls.out)
        cls.after = snapshot(cls.repo)
        cls.report = json.loads(cls.out.read_text(encoding="utf-8")) if cls.out.exists() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def scenario(self, name: str) -> dict:
        found = [s for s in self.report.get("scenarios", []) if s["name"] == name]
        self.assertEqual(len(found), 1, f"scenario {name} missing: {self.proc.stdout}\n{self.proc.stderr}")
        return found[0]

    def test_low_scenario_is_low_tier_and_approved(self):
        low = self.scenario("low")
        self.assertEqual(low["tier"], "low")
        self.assertEqual(low["expected_verdict"], "approved")
        self.assertEqual(low["verdict"], "approved")
        self.assertTrue(low["pass"], low["steps"])
        steps = {s["step"] for s in low["steps"]}
        for role in ("script:role_contract", "script:comment_gate", "script:docs_lint"):
            self.assertIn(f"capture {role}", steps)

    def test_medium_scenario_is_medium_tier_and_approved(self):
        medium = self.scenario("medium")
        self.assertEqual(medium["tier"], "medium")
        self.assertEqual(medium["verdict"], "approved")
        self.assertTrue(medium["pass"], medium["steps"])
        steps = {s["step"] for s in medium["steps"]}
        for role in ("generic-challenger", "generic-verifier"):
            self.assertIn(f"output_write {role}", steps)
            self.assertIn(f"capture {role}", steps)
        self.assertTrue(any("FIXTURE" in item for item in self.report["not_measured"]))

    def test_broken_control_is_rejected(self):
        control = self.scenario("medium-broken-control")
        self.assertEqual(control["tier"], "medium")
        self.assertEqual(control["expected_verdict"], "rejected")
        self.assertEqual(control["verdict"], "rejected")
        self.assertTrue(control["pass"], control["steps"])

    def test_role_contract_control_is_low_and_rejected(self):
        # negative control: the real role_contract script FAILs (scope declared away from the
        # committed path) and finalize must not approve what its own script rejected.
        control = self.scenario("low-role-contract-control")
        self.assertEqual(control["tier"], "low")
        self.assertEqual(control["expected_verdict"], "rejected")
        self.assertEqual(control["verdict"], "rejected")
        self.assertTrue(control["pass"], control["steps"])
        role_contract = [s for s in control["steps"] if s["step"] == "script:role_contract"]
        self.assertEqual([s["exit_code"] for s in role_contract], [1])

    def test_scenarios_are_the_three_existing_plus_the_control(self):
        self.assertEqual([s["name"] for s in self.report["scenarios"]],
                         ["low", "low-role-contract-control", "medium", "medium-broken-control"])
        low = [s for s in self.scenario("low")["steps"] if s["step"] == "script:role_contract"]
        self.assertEqual([s["exit_code"] for s in low], [0])

    def test_pass_verdict_and_exit_zero(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stdout + self.proc.stderr)
        self.assertEqual(self.report["verdict"], "PASS")
        self.assertTrue(self.report["loop_ran"])
        self.assertEqual(self.report["repo_sha"], self.before["head"].strip())

    def test_user_repo_untouched(self):
        self.assertEqual(self.before, self.after)
        self.assertNotIn("metodo-smoke", self.after["refs"])
        self.assertTrue(self.report["user_repo_untouched"])

    def test_report_is_deterministic_across_runs(self):
        out2 = self.tmp / "report-2.json"
        proc = run_smoke(self.repo, out2)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.out.read_bytes(), out2.read_bytes())

    def test_no_absolute_paths_in_report(self):
        text = self.out.read_text(encoding="utf-8")
        for needle in (str(self.tmp), str(self.tmp.resolve()), str(TOOLS_ROOT), str(Path.home()), tempfile.gettempdir()):
            self.assertNotIn(needle, text)
        self.assertNotIn('"/', text)
        self.assertNotIn('"~', text)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n")

    def test_temp_dir_is_removed_without_keep(self):
        leftovers = list(Path(tempfile.gettempdir()).glob("metodo-smoke-*"))
        kept = [p for p in leftovers if (p / "clone").exists() and _git(p / "clone", "config", "--get", "remote.origin.url").strip() == str(self.repo)]
        self.assertEqual(kept, [])


class SmokeLoopUsageTest(unittest.TestCase):
    def test_non_git_path_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            proc = run_smoke(Path(tmp), out)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertFalse(out.exists())

    def test_missing_repo_argument_is_usage_error(self):
        proc = subprocess.run(["python3", str(SMOKE)], capture_output=True, text=True, cwd=str(TOOLS_ROOT))
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
