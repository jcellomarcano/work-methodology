"""bin/install-claude.sh over a temporary git repo with a pre-existing
settings.local.json (permissions + skillOverrides) and a foreign agent: installs
the kit's own, keeps the rest, is idempotent, and --uninstall removes only its own."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = TOOLS_ROOT / "bin" / "install-claude.sh"
PI_INSTALLER = TOOLS_ROOT / "bin" / "install-pi.sh"
SKILLS_SRC = TOOLS_ROOT.parent / "02-skills"
PUBLISH_SKILL = "post-review-comment"


def _bash_array(name: str) -> list[str]:
    """Entries of a top-level NAME=( ... ) array in install-claude.sh, one per line."""
    text = INSTALLER.read_text(encoding="utf-8")
    match = re.search(rf"^{name}=\((.*?)^\)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        return []
    return [line.split("#")[0].strip() for line in match.group(1).splitlines() if line.split("#")[0].strip()]


def _assert_second_pass_unchanged(test: unittest.TestCase, stdout: str) -> None:
    changed = [line for line in stdout.splitlines() if re.match(r"^\s+[+~] ", line)]
    test.assertEqual(changed, [], stdout)
    test.assertIn("summary: 0 copied/updated", stdout)
    test.assertNotIn('"changed": true', stdout)


def _source_core() -> str:
    """The subagent core as CONTEXT-PACK.md holds it, read here on its own."""
    text = (TOOLS_ROOT.parent / "CONTEXT-PACK.md").read_text(encoding="utf-8")
    start = text.index("<!-- subagent-core:start -->") + len("<!-- subagent-core:start -->")
    return text[start:text.index("<!-- subagent-core:end -->")].strip("\n")


def _assert_agents_carry_the_core(test: unittest.TestCase, agents_dir: Path) -> None:
    core = _source_core()
    installed = sorted(agents_dir.glob("generic-*.md"))
    test.assertEqual(len(installed), len(list((TOOLS_ROOT.parent / "01-roles" / "agents").glob("generic-*.md"))))
    for path in installed:
        text = path.read_text(encoding="utf-8")
        test.assertEqual(text.count(core), 1, path.name)
        test.assertNotIn("../", text, path.name)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class InstallClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="install-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        (self.repo / ".claude" / "agents").mkdir(parents=True)
        (self.repo / ".claude" / "agents" / "domain-redteam.md").write_text("---\nname: domain-redteam\n---\nother\n", encoding="utf-8")
        self.settings = self.repo / ".claude" / "settings.local.json"
        self.original = {"permissions": {"allow": ["Bash(git status)", "Read(//x/**)"], "deny": []}, "skillOverrides": {"a": 1}}
        self.settings.write_text(json.dumps(self.original, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        return subprocess.run(["bash", str(INSTALLER), str(self.repo), *extra], capture_output=True, text=True)

    def test_install_is_complete_idempotent_and_reversible(self):
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        agents = self.repo / ".claude" / "agents"
        judge = (agents / "generic-judge.md").read_text(encoding="utf-8")
        self.assertIn("${METODO_TOOLS:-$HOME/metodologia-de-trabajo/03-tools}/hooks", judge)
        self.assertNotIn("__TOOLS_DEFAULT__", judge)
        self.assertTrue((agents / "generic-judge.contract.json").exists())
        _assert_agents_carry_the_core(self, agents)
        self.assertEqual((agents / "domain-redteam.md").read_text(encoding="utf-8"), "---\nname: domain-redteam\n---\nother\n")
        self.assertTrue((self.repo / ".claude" / "skills" / "receipt-review" / "SKILL.md").exists())
        mcp = json.loads((self.repo / ".mcp.json").read_text(encoding="utf-8"))
        self.assertIn("mcp/server.py", mcp["mcpServers"]["metodo"]["args"][0])
        self.assertEqual(mcp["mcpServers"]["metodo"]["env"]["METODO_REPO"], str(self.repo))
        exclude = (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertEqual(exclude.count(".mcp.json\n"), 1)
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"], self.original["permissions"])
        self.assertEqual(settings["skillOverrides"], {"a": 1})
        self.assertIn("PreToolUse", settings["hooks"])
        commands = [h["command"] for entries in settings["hooks"].values() for e in entries for h in e["hooks"]]
        self.assertTrue(all("metodo-hook" in c for c in commands))
        self.assertTrue(all("__TOOLS_DEFAULT__" not in c for c in commands))
        self.assertIn('"problems": []', first.stdout)

        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn(" + ", second.stdout.split("== servidor MCP")[0])
        self.assertNotIn(" ~ ", second.stdout.split("== servidor MCP")[0])
        self.assertEqual(exclude, (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8"))

        gone = self._run("--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stderr)
        after = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("hooks", after)
        self.assertEqual(after["permissions"], self.original["permissions"])
        self.assertFalse((self.repo / ".mcp.json").exists())
        # T13: the kit's own agents and skills go too (byte-identical to the render)
        self.assertFalse((agents / "generic-judge.md").exists())
        self.assertFalse((self.repo / ".claude" / "skills" / "receipt-review").exists())
        # negative control: a foreign agent stays, byte for byte
        self.assertEqual((agents / "domain-redteam.md").read_text(encoding="utf-8"), "---\nname: domain-redteam\n---\nother\n")
        self.assertNotIn(".mcp.json", (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines())

    def test_publish_comment_skill_is_installed_with_tools_root(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        skill = (self.repo / ".claude" / "skills" / PUBLISH_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("${METODO_TOOLS:-$HOME/metodologia-de-trabajo/03-tools}/lib/review_comment_post.py", skill)
        self.assertNotIn("__TOOLS_DEFAULT__", skill)
        # negative control: no bare relative call left, its root is unclear once installed
        self.assertNotIn("`lib/review_comment_post.py", skill)

    def test_second_pass_is_all_unchanged(self):
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        _assert_second_pass_unchanged(self, second.stdout)

    def test_tools_flag_renders_instance_path(self):
        instance = self.tmp / "instance-tools"
        shutil.copytree(TOOLS_ROOT / "mcp", instance / "mcp")
        shutil.copytree(TOOLS_ROOT / "lib", instance / "lib")
        shutil.copytree(TOOLS_ROOT / "config", instance / "config")
        (instance / "schemas").symlink_to(TOOLS_ROOT / "schemas")
        proc = self._run("--tools", str(instance))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        judge = (self.repo / ".claude" / "agents" / "generic-judge.md").read_text(encoding="utf-8")
        self.assertIn(f"${{METODO_TOOLS:-{instance}}}/hooks", judge.replace("$HOME", str(Path.home())))
        mcp = json.loads((self.repo / ".mcp.json").read_text(encoding="utf-8"))
        self.assertIn("instance-tools", mcp["mcpServers"]["metodo"]["env"]["METODO_TOOLS"])
        skill = (self.repo / ".claude" / "skills" / PUBLISH_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"${{METODO_TOOLS:-{instance}}}/lib/review_comment_post.py", skill.replace("$HOME", str(Path.home())))

    def test_drift_check_blocks_unknown_tasks(self):
        verify = self.repo / "tools" / "verify"
        verify.mkdir(parents=True)
        (verify / "verify.sh").write_text("CHECK_TASKS=(\n  :other:test\n)\n", encoding="utf-8")
        instance = self.tmp / "inst"
        shutil.copytree(TOOLS_ROOT / "lib", instance / "lib")
        (instance / "config").mkdir()
        (instance / "config" / "project.json").write_text(json.dumps(
            {"test_sectors": {"sectors": [{"paths": ["domain/"], "tasks": [":domain:test"]}]}}), encoding="utf-8")
        proc = self._run("--tools", str(instance))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("unknown_tasks", proc.stdout)


@unittest.skipUnless(SKILLS_SRC.is_dir(), "kit only: the instance does not carry 02-skills/")
class SkillListDriftTests(unittest.TestCase):
    """Every skill directory the kit ships is either in SKILLS (installed by
    both runtimes) or in SKILLS_EXCLUDED (on purpose), never neither."""

    def test_every_shipped_skill_is_installed_or_explicitly_excluded(self):
        shipped = sorted(p.name for p in SKILLS_SRC.iterdir() if (p / "SKILL.md").is_file())
        installed = _bash_array("SKILLS")
        excluded = _bash_array("SKILLS_EXCLUDED")
        self.assertTrue(installed)
        self.assertEqual(sorted(set(shipped) - set(installed) - set(excluded)), [])
        self.assertIn(PUBLISH_SKILL, installed)

    def test_lists_name_only_real_skills_and_do_not_overlap(self):
        installed = _bash_array("SKILLS")
        excluded = _bash_array("SKILLS_EXCLUDED")
        self.assertEqual(sorted(set(installed) & set(excluded)), [])
        self.assertEqual(len(installed), len(set(installed)))
        self.assertEqual([s for s in installed + excluded if not (SKILLS_SRC / s / "SKILL.md").is_file()], [])


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class InstallPiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="install-pi-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        return subprocess.run(["bash", str(PI_INSTALLER), str(self.repo), *extra], capture_output=True, text=True)

    def test_publish_comment_skill_is_installed_and_second_pass_unchanged(self):
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        skill = (self.repo / ".pi" / "skills" / PUBLISH_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"${{METODO_TOOLS:-{TOOLS_ROOT}}}/lib/review_comment_post.py", skill)
        self.assertNotIn("__TOOLS_DEFAULT__", skill)
        agents = self.repo / ".pi" / "agents"
        _assert_agents_carry_the_core(self, agents)
        for path in agents.glob("generic-*.md"):
            # the extension reads the role marker as the last line
            self.assertEqual(path.read_text(encoding="utf-8").rstrip("\n").splitlines()[-1], f"<!-- metodo-role: {path.stem} -->")
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        _assert_second_pass_unchanged(self, second.stdout)
