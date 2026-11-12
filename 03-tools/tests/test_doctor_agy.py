"""lib/doctor.py --runtime agy: one throwaway repo gets the kit through
bin/install.sh --runtime agy in setUpClass; every breakage works on its own
copy, so each test proves that one missing piece of the agy plugin turns its
own check FAIL with a fix, and --absent proves the uninstall left nothing.
The claude and pi reports keep their check ids: agy never rides on `all`."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = TOOLS_ROOT / "lib" / "doctor.py"
DOCTOR_SH = TOOLS_ROOT / "bin" / "doctor.sh"
INSTALL = TOOLS_ROOT / "bin" / "install.sh"
ENV = dict(os.environ, METODO_MEMORY="off")
PLUGIN = Path(".agents") / "plugins" / "metodo"
AGY_CHECKS = ("agy.agents", "agy.contracts", "agy.skills", "agy.mcp", "agy.hooks")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class AgyDoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="doctor-agy-"))
        cls.fixture = cls.tmp / "fixture"
        cls.fixture.mkdir()
        _git(cls.fixture, "init", "-q")
        (cls.fixture / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(cls.fixture, "add", "README.md")
        _git(cls.fixture, "commit", "-q", "-m", "init")
        proc = subprocess.run(["bash", str(INSTALL), str(cls.fixture), "--runtime", "agy", "--tools", str(TOOLS_ROOT)],
                              capture_output=True, text=True, env=ENV)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout + proc.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_doctor(self, repo: Path, *extra: str, runtime: str = "agy"):
        proc = subprocess.run(["python3", str(DOCTOR), str(repo), "--runtime", runtime, *extra],
                              capture_output=True, text=True, env=ENV)
        return proc, json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None

    def copy_fixture(self, name: str) -> Path:
        """Copies the installed fixture and repoints the absolute repo path the
        installer baked into the plugin, so only the planted breakage differs."""
        dst = self.tmp / name
        shutil.copytree(self.fixture, dst, symlinks=True)
        for rel in ("hooks.json", "mcp_config.json"):
            path = dst / PLUGIN / rel
            path.write_text(path.read_text(encoding="utf-8").replace(str(self.fixture), str(dst)), encoding="utf-8")
        return dst

    def check(self, report: dict, check_id: str) -> dict:
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertIn(check_id, by_id, sorted(by_id))
        return by_id[check_id]

    def assert_breaks(self, repo: Path, check_id: str) -> dict:
        proc, report = self.run_doctor(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertFalse(report["kit_installed"])
        found = self.check(report, check_id)
        self.assertEqual(found["status"], "FAIL", found)
        self.assertTrue(found["fix"], found)
        if check_id.startswith("agy."):
            self.assertIn("--runtime agy", found["fix"])
        return found

    def test_installed_repo_passes_with_only_agy_checks(self):
        proc, report = self.run_doctor(self.fixture)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(report["kit_installed"])
        self.assertEqual(report["runtime"], "agy")
        ids = [c["id"] for c in report["checks"]]
        for check_id in AGY_CHECKS:
            self.assertIn(check_id, report["required"])
            self.assertEqual(self.check(report, check_id)["status"], "PASS")
        self.assertFalse([i for i in ids if i.startswith(("claude.", "pi."))], ids)
        self.assertEqual(self.check(report, "git.exclude")["status"], "PASS")
        self.assertIn(PLUGIN.as_posix(), self.check(report, "git.exclude")["detail"])
        self.assertNotIn(str(self.fixture), proc.stdout)

    def test_copy_fixture_is_still_wired(self):
        proc, report = self.run_doctor(self.copy_fixture("copy"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_doctor_sh_accepts_the_agy_runtime(self):
        out = self.tmp / "report.json"
        proc = subprocess.run(["bash", str(DOCTOR_SH), str(self.fixture), "--runtime", "agy", "--out", str(out)],
                              capture_output=True, text=True, env=ENV)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("runtime agy", proc.stdout)
        self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["kit_installed"])
        usage = subprocess.run(["bash", str(DOCTOR_SH)], capture_output=True, text=True, env=ENV)
        self.assertEqual(usage.returncode, 2)
        self.assertIn("claude|pi|agy|all", usage.stderr)

    def test_all_and_the_other_runtimes_never_carry_agy_checks(self):
        for runtime in ("all", "claude", "pi"):
            for extra in ((), ("--absent",)):
                with self.subTest(runtime=runtime, extra=extra):
                    _, report = self.run_doctor(self.fixture, *extra, runtime=runtime)
                    ids = [c["id"] for c in report["checks"]]
                    self.assertFalse([i for i in ids if i.startswith("agy.")], ids)
                    self.assertFalse([i for i in report.get("required", []) if i.startswith("agy.")])
        _, report = self.run_doctor(self.fixture, runtime="all")
        self.assertIn(".mcp.json", self.check(report, "git.exclude")["detail"])

    def test_edited_hooks_fail(self):
        repo = self.copy_fixture("edited-hooks")
        hooks = repo / PLUGIN / "hooks.json"
        text = hooks.read_text(encoding="utf-8")
        self.assertIn("bridge.py\\\" Stop", text)
        hooks.write_text(text.replace("bridge.py\\\" Stop", "bridge.py\\\" Nope"), encoding="utf-8")
        self.assert_breaks(repo, "agy.hooks")

    def test_missing_manifest_fails_the_hooks_check(self):
        repo = self.copy_fixture("no-manifest")
        (repo / PLUGIN / "plugin.json").unlink()
        self.assertIn("plugin.json", self.assert_breaks(repo, "agy.hooks")["detail"])

    def test_missing_server_config_fails(self):
        repo = self.copy_fixture("no-mcp")
        (repo / PLUGIN / "mcp_config.json").unlink()
        self.assert_breaks(repo, "agy.mcp")

    def test_server_config_for_another_repo_fails(self):
        repo = self.copy_fixture("other-repo")
        path = repo / PLUGIN / "mcp_config.json"
        path.write_text(path.read_text(encoding="utf-8").replace(str(repo), str(self.tmp)), encoding="utf-8")
        self.assertIn("METODO_REPO", self.assert_breaks(repo, "agy.mcp")["detail"])

    def test_missing_skill_and_agent_fail(self):
        repo = self.copy_fixture("no-skill")
        shutil.rmtree(next((repo / PLUGIN / "skills").iterdir()))
        (repo / PLUGIN / "agents" / "generic-judge.md").unlink()
        self.assert_breaks(repo, "agy.skills")
        self.assert_breaks(repo, "agy.agents")

    def test_missing_contract_fails(self):
        repo = self.copy_fixture("no-contract")
        (repo / PLUGIN / "contracts" / "generic-judge.contract.json").unlink()
        found = self.assert_breaks(repo, "agy.contracts")
        self.assertIn("missing", found["detail"])
        self.assertIn("generic-judge.contract.json", found["detail"])

    def test_modified_contract_fails(self):
        repo = self.copy_fixture("edited-contract")
        path = repo / PLUGIN / "contracts" / "generic-proposer.contract.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["max_tool_calls"] = 600000
        path.write_text(json.dumps(data), encoding="utf-8")
        found = self.assert_breaks(repo, "agy.contracts")
        self.assertIn("differs", found["detail"])
        self.assertIn("generic-proposer.contract.json", found["detail"])
        self.assertNotIn("generic-judge.contract.json", found["detail"])

    def test_absent_fails_on_a_leftover_contract(self):
        repo = self.copy_fixture("leftover-contract")
        shutil.rmtree(repo / ".agents")
        leftover = repo / PLUGIN / "contracts" / "generic-judge.contract.json"
        leftover.parent.mkdir(parents=True)
        leftover.write_text("{}\n", encoding="utf-8")
        proc, report = self.run_doctor(repo, "--absent")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual({c["id"] for c in report["checks"] if c["status"] == "FAIL"}, {"agy.contracts"})
        self.assertIn("--uninstall --runtime agy", self.check(report, "agy.contracts")["fix"])

    def test_missing_exclude_line_fails(self):
        repo = self.copy_fixture("no-exclude")
        exclude = repo / ".git" / "info" / "exclude"
        exclude.write_text("".join(l for l in exclude.read_text(encoding="utf-8").splitlines(True)
                                   if l.strip() != PLUGIN.as_posix()), encoding="utf-8")
        found = self.assert_breaks(repo, "git.exclude")
        self.assertIn(PLUGIN.as_posix(), found["detail"])
        self.assertIn(PLUGIN.as_posix(), found["fix"])

    def test_claude_and_pi_reports_keep_their_personal_check_as_before(self):
        """.agents/ is scanned for the agy runtime only: the other reports read as they did."""
        repo = self.copy_fixture("personal-other-runtimes")
        (repo / PLUGIN / "skills" / "output-lint.personal.json").write_text("[]\n", encoding="utf-8")
        for runtime in ("claude", "pi", "all"):
            with self.subTest(runtime=runtime):
                _, report = self.run_doctor(repo, runtime=runtime)
                found = self.check(report, "personal.absent")
                self.assertEqual((found["status"], found["detail"]), ("PASS", "no personal asset under .claude/ or .pi/"))

    def test_the_agy_report_names_the_agents_folder_in_its_personal_check(self):
        _, report = self.run_doctor(self.fixture)
        found = self.check(report, "personal.absent")
        self.assertEqual((found["status"], found["detail"]), ("PASS", "no personal asset under .claude/, .pi/ or .agents/"))

    def test_personal_asset_under_agents_fails(self):
        repo = self.copy_fixture("personal")
        (repo / PLUGIN / "skills" / "output-lint.personal.json").write_text("[]\n", encoding="utf-8")
        found = self.assert_breaks(repo, "personal.absent")
        self.assertIn(".agents/plugins/metodo/skills/output-lint.personal.json", found["detail"])

    def test_untracked_agents_folder_does_not_make_the_repo_dirty(self):
        # .agents/ is agy's agent-config folder, as .claude/ is Claude Code's
        repo = self.copy_fixture("own-agents")
        _, report = self.run_doctor(repo)
        self.assertIs(report["repo_dirty"], False)
        (repo / ".agents" / "skills" / "own").mkdir(parents=True)
        (repo / ".agents" / "skills" / "own" / "SKILL.md").write_text("x\n", encoding="utf-8")
        _, report = self.run_doctor(repo)
        self.assertIs(report["repo_dirty"], False)
        (repo / "notes.txt").write_text("x\n", encoding="utf-8")
        _, report = self.run_doctor(repo)
        self.assertIs(report["repo_dirty"], True)

    def test_absent_after_uninstall_passes_and_a_leftover_fails(self):
        repo = self.copy_fixture("uninstalled")
        proc = subprocess.run(["bash", str(INSTALL), str(repo), "--uninstall", "--runtime", "agy", "--tools", str(TOOLS_ROOT)],
                              capture_output=True, text=True, env=ENV)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        proc, report = self.run_doctor(repo, "--absent")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(report["kit_absent"])
        self.assertEqual(sorted(c["id"] for c in report["checks"]), sorted(AGY_CHECKS))
        leftover = repo / PLUGIN / "hooks.json"
        leftover.parent.mkdir(parents=True)
        leftover.write_text("{}\n", encoding="utf-8")
        proc, report = self.run_doctor(repo, "--absent")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertFalse(report["kit_absent"])
        found = self.check(report, "agy.hooks")
        self.assertEqual(found["status"], "FAIL")
        self.assertIn("--uninstall --runtime agy", found["fix"])

    def test_absent_on_an_installed_repo_fails_every_agy_check(self):
        proc, report = self.run_doctor(self.fixture, "--absent")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual({c["id"]: c["status"] for c in report["checks"]}, {i: "FAIL" for i in AGY_CHECKS})


if __name__ == "__main__":
    unittest.main()
