"""lib/doctor.py and bin/doctor.sh: the wiring doctor (kit-init T6, S5/S8/S10).

One throwaway git repo gets the whole kit (bin/install.sh --runtime all) in
setUpClass; every breakage works on its own copy of it, so each test proves
that exactly one missing piece turns its own check FAIL with a fix.

Non-git directory: the doctor does not refuse it as usage. It reports
repo.git FAIL (exit 1) and still emits the JSON, so the benchmark gets
evidence instead of a bare error. Exit 2 is reserved for a path that does
not exist or a bad flag.
"""
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


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class DoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="doctor-"))
        cls.fixture = cls.tmp / "fixture"
        cls.fixture.mkdir()
        _git(cls.fixture, "init", "-q")
        (cls.fixture / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(cls.fixture, "add", "README.md")
        _git(cls.fixture, "commit", "-q", "-m", "init")
        proc = subprocess.run(["bash", str(INSTALL), str(cls.fixture), "--runtime", "all", "--tools", str(TOOLS_ROOT)],
                              capture_output=True, text=True, env=ENV)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout + proc.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # helpers
    def run_doctor(self, repo: Path, *extra: str):
        proc = subprocess.run(["python3", str(DOCTOR), str(repo), *extra], capture_output=True, text=True, env=ENV)
        report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
        return proc, report

    def copy_fixture(self, name: str) -> Path:
        """Copies the installed fixture and repoints the absolute repo path the
        installers baked in (.mcp.json, the pi extension), so the copy is as
        wired as the original and only the planted breakage differs."""
        dst = self.tmp / name
        shutil.copytree(self.fixture, dst, symlinks=True)
        old, new = str(self.fixture), str(dst)
        for rel in (".mcp.json", ".pi/extensions/metodo-hooks.ts"):
            path = dst / rel
            path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        return dst

    def check(self, report: dict, check_id: str) -> dict:
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertIn(check_id, by_id, sorted(by_id))
        return by_id[check_id]

    def assert_breaks(self, repo: Path, check_id: str):
        proc, report = self.run_doctor(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["kit_installed"])
        found = self.check(report, check_id)
        self.assertEqual(found["status"], "FAIL", found)
        self.assertTrue(found["fix"], found)
        return report

    # the happy path
    def test_fully_installed_repo_passes(self):
        proc, report = self.run_doctor(self.fixture)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(report["verdict"], "PASS")
        self.assertTrue(report["kit_installed"])
        self.assertEqual(report["runtime"], "all")
        ids = [c["id"] for c in report["checks"]]
        self.assertEqual(ids, sorted(ids))
        for expected in ("repo.git", "tools.layout", "tools.is_kit", "config.project", "config.base_ref",
                         "claude.agents", "claude.skills", "claude.mcp", "claude.hooks", "hooks.fire",
                         "git.exclude", "pi.agents", "pi.skills", "pi.mcp", "pi.extension", "memory.engram",
                         "vendor.tools", "baseline.latest", "personal.absent", "router.catalog"):
            self.assertIn(expected, ids)
        for c in report["checks"]:
            self.assertEqual(set(c), {"id", "status", "detail", "fix"})
            self.assertIn(c["status"], {"PASS", "WARN", "FAIL", "SKIP"})
            if c["status"] == "PASS":
                self.assertIsNone(c["fix"], c)
        for key in ("schema_version", "tool_sha", "repo_sha", "repo_dirty"):
            self.assertIn(key, report)
        self.assertEqual(report["repo_sha"], _git(self.fixture, "rev-parse", "HEAD"))
        self.assertFalse(report["repo_dirty"])
        # the kit's own 03-tools carries the shared template, not an instance
        self.assertEqual(self.check(report, "tools.is_kit")["status"], "WARN")
        self.assertEqual(self.check(report, "memory.engram")["status"], "SKIP")
        self.assertEqual(self.check(report, "router.catalog")["status"], "PASS")

    def test_runtime_filter(self):
        _, claude = self.run_doctor(self.fixture, "--runtime", "claude")
        self.assertFalse([c for c in claude["checks"] if c["id"].startswith("pi.")])
        self.assertTrue(claude["kit_installed"])
        _, pi = self.run_doctor(self.fixture, "--runtime", "pi")
        self.assertFalse([c for c in pi["checks"] if c["id"].startswith("claude.")])
        self.assertTrue(pi["kit_installed"])
        self.assertEqual(pi["runtime"], "pi")

    # one breakage per rule
    def test_missing_agent_fails_claude_agents(self):
        repo = self.copy_fixture("no-agent")
        (repo / ".claude" / "agents" / "generic-judge.md").unlink()
        report = self.assert_breaks(repo, "claude.agents")
        self.assertIn("generic-judge.md", self.check(report, "claude.agents")["detail"])

    def test_unrendered_agent_token_fails_claude_agents(self):
        repo = self.copy_fixture("token-agent")
        agent = repo / ".claude" / "agents" / "generic-proposer.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\n__TOOLS_DEFAULT__/hooks\n", encoding="utf-8")
        self.assert_breaks(repo, "claude.agents")

    def test_missing_skill_fails_claude_skills(self):
        repo = self.copy_fixture("no-skill")
        shutil.rmtree(repo / ".claude" / "skills" / "cartography")
        report = self.assert_breaks(repo, "claude.skills")
        self.assertIn("cartography", self.check(report, "claude.skills")["detail"])

    def test_missing_pi_skill_fails_pi_skills(self):
        repo = self.copy_fixture("no-pi-skill")
        shutil.rmtree(repo / ".pi" / "skills" / "post-review-comment")
        self.assert_breaks(repo, "pi.skills")

    def test_missing_metodo_server_fails_mcp(self):
        repo = self.copy_fixture("no-mcp")
        mcp = repo / ".mcp.json"
        data = json.loads(mcp.read_text(encoding="utf-8"))
        del data["mcpServers"]["metodo"]
        mcp.write_text(json.dumps(data), encoding="utf-8")
        self.assert_breaks(repo, "claude.mcp")
        _, pi = self.run_doctor(repo, "--runtime", "pi")
        self.assertEqual(self.check(pi, "pi.mcp")["status"], "FAIL")

    def test_moved_repo_without_reinstall_fails_mcp(self):
        # METODO_REPO still names the original repo: the server would serve the wrong one
        repo = self.tmp / "moved"
        shutil.copytree(self.fixture, repo, symlinks=True)
        self.assert_breaks(repo, "claude.mcp")

    def test_missing_marked_hook_fails_claude_hooks(self):
        repo = self.copy_fixture("no-hook")
        settings_path = repo / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        del settings["hooks"]["SessionStart"]
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        report = self.assert_breaks(repo, "claude.hooks")
        self.assertIn("SessionStart", self.check(report, "claude.hooks")["detail"])

    def test_missing_pi_extension_fails(self):
        repo = self.copy_fixture("no-ext")
        (repo / ".pi" / "extensions" / "metodo-hooks.ts").unlink()
        self.assert_breaks(repo, "pi.extension")

    def test_edited_pi_extension_fails(self):
        repo = self.copy_fixture("edited-ext")
        ext = repo / ".pi" / "extensions" / "metodo-hooks.ts"
        ext.write_text(ext.read_text(encoding="utf-8") + "\n// edited\n", encoding="utf-8")
        self.assert_breaks(repo, "pi.extension")

    def test_missing_mcp_exclude_fails(self):
        repo = self.copy_fixture("no-exclude")
        exclude = repo / ".git" / "info" / "exclude"
        exclude.write_text("".join(l for l in exclude.read_text(encoding="utf-8").splitlines(True)
                                   if l.strip() != ".mcp.json"), encoding="utf-8")
        self.assert_breaks(repo, "git.exclude")

    def test_personal_asset_fails(self):
        repo = self.copy_fixture("personal")
        (repo / ".claude" / "skills" / "personal").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "skills" / "personal" / "language.md").write_text("x\n", encoding="utf-8")
        (repo / ".pi" / "output-lint.personal.json").write_text("[]\n", encoding="utf-8")
        (repo / ".claude" / "skills" / "personal-notes.md").write_text("x\n", encoding="utf-8")
        report = self.assert_breaks(repo, "personal.absent")
        detail = self.check(report, "personal.absent")["detail"]
        self.assertIn(".claude/skills/personal", detail)
        self.assertNotIn(".claude/skills/personal/language.md", detail, "the outermost match covers its contents")
        self.assertIn(".pi/output-lint.personal.json", detail)
        # negative control: the word alone, outside the convention, is not personal
        self.assertNotIn("personal-notes.md", detail)

    # non-git, usage
    def test_non_git_dir_reports_repo_git_fail(self):
        plain = self.tmp / "plain"
        plain.mkdir(exist_ok=True)
        proc, report = self.run_doctor(plain)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        repo_git = self.check(report, "repo.git")
        self.assertEqual(repo_git["status"], "FAIL")
        self.assertTrue(repo_git["fix"])
        self.assertIsNone(report["repo_sha"])
        self.assertFalse(report["kit_installed"])

    def test_usage_errors_exit_2(self):
        proc, _ = self.run_doctor(self.tmp / "does-not-exist")
        self.assertEqual(proc.returncode, 2)
        proc, _ = self.run_doctor(self.fixture, "--runtime", "vscode")
        self.assertEqual(proc.returncode, 2)

    # determinism and privacy of the evidence
    def test_two_runs_are_byte_identical(self):
        a, b = self.tmp / "a.json", self.tmp / "b.json"
        first, _ = self.run_doctor(self.fixture, "--out", str(a))
        second, _ = self.run_doctor(self.fixture, "--out", str(b))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(first.stdout, second.stdout)
        text = a.read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n")

    def test_no_absolute_paths_in_output(self):
        broken = self.copy_fixture("abs-check")
        (broken / ".claude" / "agents" / "generic-judge.md").unlink()
        for repo in (self.fixture, broken, self.tmp):
            proc, report = self.run_doctor(repo)
            text = proc.stdout
            for needle in (str(self.tmp), str(self.tmp.resolve()), str(TOOLS_ROOT), str(Path.home())):
                self.assertNotIn(needle, text)
            for s in _strings(report):
                self.assertFalse(s.startswith("/"), s)

    # tools root variants
    def test_tools_copy_without_git_and_broken_hook(self):
        tools = self.tmp / "tools-copy"
        shutil.copytree(TOOLS_ROOT, tools, ignore=shutil.ignore_patterns("out", "vendor", "baselines", "__pycache__", "*.pyc"))
        (tools / "hooks" / "guard_gates.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        config = json.loads((tools / "config" / "project.json").read_text(encoding="utf-8"))
        del config["property_order"]
        (tools / "config" / "project.json").write_text(json.dumps(config), encoding="utf-8")
        proc = subprocess.run(["bash", str(tools / "bin" / "doctor.sh"), str(self.fixture)],
                              capture_output=True, text=True, env=ENV)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("hooks.fire", proc.stdout)  # the human table
        default_out = tools / "out" / "doctor" / f"{_git(self.fixture, 'rev-parse', 'HEAD')}.json"
        self.assertTrue(default_out.exists(), proc.stdout + proc.stderr)
        report = json.loads(default_out.read_text(encoding="utf-8"))
        if subprocess.run(["git", "-C", str(tools), "rev-parse", "HEAD"], capture_output=True).returncode != 0:
            self.assertIsNone(report["tool_sha"])
            self.assertEqual(self.check(report, "tools.git")["status"], "WARN")
        self.assertEqual(self.check(report, "hooks.fire")["status"], "FAIL")
        self.assertEqual(self.check(report, "config.project")["status"], "FAIL")
        self.assertIn("property_order", self.check(report, "config.project")["detail"])
        self.assertEqual(self.check(report, "tools.is_kit")["status"], "PASS")
        for needle in (str(self.tmp), str(TOOLS_ROOT)):
            self.assertNotIn(needle, default_out.read_text(encoding="utf-8"))


class RouterCatalogCheckTests(unittest.TestCase):
    """router.catalog (model-router R9): the catalog parses, carries a version,
    every admitted model has a price at the catalog's own date (no clock), and
    the router returns ok for a canonical B5 review. In-process, no install."""

    def setUp(self):
        from lib import doctor
        self.doctor = doctor
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-router-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.catalog = json.loads((TOOLS_ROOT / "config" / "model-tiers.json").read_text(encoding="utf-8"))

    def _check(self, catalog_text: str | None) -> dict:
        tools = self.tmp / f"tools-{len(list(self.tmp.iterdir()))}"
        (tools / "config").mkdir(parents=True)
        if catalog_text is not None:
            (tools / "config" / "model-tiers.json").write_text(catalog_text, encoding="utf-8")
        return self.doctor.check_router_catalog(self.doctor.Ctx(self.tmp, tools, "all"))

    def test_kit_catalog_passes(self):
        found = self.doctor.check_router_catalog(self.doctor.Ctx(self.tmp, TOOLS_ROOT, "all"))
        self.assertEqual(found["status"], "PASS", found)
        self.assertIsNone(found["fix"])
        self.assertIn(self.catalog["version"], found["detail"])
        self.assertIn("B5", found["detail"])

    def test_broken_catalog_fails_with_a_fix(self):
        no_version = dict(self.catalog)
        del no_version["version"]
        no_price = json.loads(json.dumps(self.catalog))
        for entry in no_price["tiers"]["medium"]["candidates"]:
            if entry["status"] == "admitted":
                entry["price_schedule"] = [{"from": "2099-01-01", "usd_in": 1.0, "usd_out": 1.0}]
        no_admitted = json.loads(json.dumps(self.catalog))
        for entry in no_admitted["tiers"]["medium"]["candidates"]:
            entry["status"] = "candidate"
        cases = {"missing": None, "unparseable": "{not json", "no version": json.dumps(no_version),
                 "no price at the catalog date": json.dumps(no_price), "router not ok": json.dumps(no_admitted)}
        for name, text in cases.items():
            with self.subTest(case=name):
                found = self._check(text)
                self.assertEqual(found["status"], "FAIL", found)
                self.assertTrue(found["fix"])
                self.assertNotIn(str(self.tmp), found["detail"])
        # negative control: the same copy, unbroken, passes
        self.assertEqual(self._check(json.dumps(self.catalog))["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
