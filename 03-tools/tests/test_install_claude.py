"""bin/install-claude.sh over a temporary git repo with a pre-existing
settings.local.json (permissions + skillOverrides) and a foreign agent: installs
the kit's own, keeps the rest, is idempotent, and --uninstall removes only its own."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = TOOLS_ROOT / "bin" / "install-claude.sh"


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
        (self.repo / ".claude" / "agents" / "emv-redteam.md").write_text("---\nname: emv-redteam\n---\nother\n", encoding="utf-8")
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
        self.assertEqual((agents / "emv-redteam.md").read_text(encoding="utf-8"), "---\nname: emv-redteam\n---\nother\n")
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
        # negative control: agents and skills remain (they are listed, not deleted)
        self.assertTrue((agents / "generic-judge.md").exists())

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
