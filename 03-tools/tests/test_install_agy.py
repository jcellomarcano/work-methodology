"""bin/install-agy.sh over a temporary git repo: the whole kit lands in one
agy workspace plugin, .agents/plugins/metodo/, rendered for the tools root;
a second pass changes no byte, --uninstall removes only what is
byte-identical to what it renders (keeping the owner's own .agents/ content)
and gives the repo back byte for byte, and nothing is written under HOME.
bin/install.sh keeps agy opt-in: `all` still means claude and pi."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = TOOLS_ROOT / "bin" / "install-agy.sh"
INSTALL_SH = TOOLS_ROOT / "bin" / "install.sh"
CLAUDE_INSTALLER = TOOLS_ROOT / "bin" / "install-claude.sh"
RENDERER = TOOLS_ROOT / "lib" / "render_agents.py"
TEMPLATES = TOOLS_ROOT / "hooks" / "agy"
ROLES = TOOLS_ROOT.parent / "01-roles" / "agents"
SKILLS_SRC = TOOLS_ROOT.parent / "02-skills"
PLUGIN = Path(".agents") / "plugins" / "metodo"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _skills() -> list[str]:
    text = CLAUDE_INSTALLER.read_text(encoding="utf-8")
    block = re.search(r"^SKILLS=\((.*?)^\)", text, re.MULTILINE | re.DOTALL).group(1)
    return [line.split("#")[0].strip() for line in block.splitlines() if line.split("#")[0].strip()]


def _snapshot(root: Path) -> dict:
    """Every path under root, .git included: a file by its sha256, a folder by 'dir'."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            out[rel] = "-> " + os.readlink(path)
        elif path.is_dir():
            out[rel] = "dir"
        else:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@unittest.skipUnless(ROLES.is_dir(), "kit only: the instance does not carry 01-roles/")
class InstallAgyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="install-agy-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        self.plugin = self.repo / PLUGIN
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), METODO_MEMORY="off")

    def _run(self, *extra, script: Path = INSTALLER):
        return subprocess.run(["bash", str(script), str(self.repo), *extra], capture_output=True, text=True, env=self.env)

    def _files(self) -> list[str]:
        return sorted(p.relative_to(self.repo).as_posix() for p in self.repo.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.repo).parts)

    def _server(self) -> dict:
        return json.loads((self.plugin / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]["metodo"]

    def test_install_renders_one_complete_plugin(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads((self.plugin / "plugin.json").read_text(encoding="utf-8"))["name"], "metodo")
        roles = sorted(p.name for p in ROLES.glob("generic-*.md"))
        self.assertTrue(roles)
        self.assertEqual(sorted(p.name for p in (self.plugin / "agents").glob("*.md")), roles)
        judge = (self.plugin / "agents" / "generic-judge.md").read_text(encoding="utf-8")
        self.assertIn("<!-- metodo-role: generic-judge -->", judge)
        self.assertEqual(sorted(p.name for p in (self.plugin / "skills").iterdir()), sorted(_skills()))
        server = self._server()
        self.assertEqual(server["args"], [f"{TOOLS_ROOT}/mcp/server.py"])
        self.assertEqual(server["env"], {"METODO_TOOLS": str(TOOLS_ROOT), "METODO_REPO": str(self.repo)})
        self.assertIn("call_mcp_tool", (self.plugin / "rules" / "AGENTS.md").read_text(encoding="utf-8"))
        for path in self._files():
            with self.subTest(path=path):
                self.assertTrue(path.startswith(PLUGIN.as_posix() + "/"), path)
                self.assertNotIn(b"__TOOLS_DEFAULT__", (self.repo / path).read_bytes())
                self.assertNotIn(b"__REPO_DEFAULT__", (self.repo / path).read_bytes())
        exclude = (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
        self.assertIn(PLUGIN.as_posix(), exclude)
        self.assertIn("== server smoke test ==", proc.stdout)
        self.assertIn('"problems": []', proc.stdout)

    def test_hooks_json_is_the_shipped_template_rendered_for_the_repo(self):
        self.assertEqual(self._run().returncode, 0)
        template = (TEMPLATES / "hooks.json").read_text(encoding="utf-8")
        rendered = template.replace("__TOOLS_DEFAULT__", str(TOOLS_ROOT)).replace("__REPO_DEFAULT__", str(self.repo))
        self.assertEqual((self.plugin / "hooks.json").read_text(encoding="utf-8"), rendered)
        self.assertIn(f"${{METODO_TOOLS:-{TOOLS_ROOT}}}/hooks", rendered)
        self.assertIn(f"${{METODO_REPO:-{self.repo}}}", rendered)

    def test_agents_are_the_agy_render_and_plain_skill_files_are_byte_copies(self):
        self.assertEqual(self._run().returncode, 0)
        for role in sorted(ROLES.glob("generic-*.md")):
            want = subprocess.run(["python3", str(RENDERER), str(role), "--target", "agy", "--tools-default", str(TOOLS_ROOT)],
                                  check=True, capture_output=True, text=True).stdout
            with self.subTest(role=role.name):
                self.assertEqual((self.plugin / "agents" / role.name).read_text(encoding="utf-8"), want)
        for skill in _skills():
            for src in sorted(p for p in (SKILLS_SRC / skill).iterdir() if p.is_file()):
                data = src.read_bytes()
                with self.subTest(skill=skill, file=src.name):
                    self.assertEqual((self.plugin / "skills" / skill / src.name).read_bytes(),
                                     data.replace(b"__TOOLS_DEFAULT__", str(TOOLS_ROOT).encode()))

    def test_nothing_is_written_under_home(self):
        self.assertEqual(self._run().returncode, 0)
        self.assertEqual(self._run("--uninstall").returncode, 0)
        self.assertEqual(sorted(p.relative_to(self.home).as_posix() for p in self.home.rglob("*")), [])

    def test_second_pass_changes_no_byte_and_uninstall_restores_the_repo(self):
        own = self.repo / ".agents" / "skills" / "own" / "SKILL.md"
        own.parent.mkdir(parents=True)
        own.write_text("---\nname: own\ndescription: mine\n---\nbody\n", encoding="utf-8")
        before = _snapshot(self.repo)
        self.assertEqual(self._run().returncode, 0)
        first = _snapshot(self.repo)
        self.assertNotEqual(first, before)
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(_snapshot(self.repo), first)
        self.assertEqual([l for l in second.stdout.splitlines() if re.match(r"^\s+[+~] ", l)], [], second.stdout)
        self.assertIn("summary: 0 copied/updated", second.stdout)
        back = self._run("--uninstall")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertEqual(_snapshot(self.repo), before)

    def test_tools_flag_renders_that_root_and_uninstall_finds_it_without_the_flag(self):
        tools = self.tmp / "instance"
        tools.mkdir()
        before = _snapshot(self.repo)
        proc = self._run("--tools", str(tools))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"${{METODO_TOOLS:-{tools}}}/hooks", (self.plugin / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(self._server()["env"]["METODO_TOOLS"], str(tools))
        back = self._run("--uninstall")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertEqual(_snapshot(self.repo), before)

    def test_uninstall_removes_only_the_kit_and_keeps_owner_content(self):
        own_skill = self.repo / ".agents" / "skills" / "own" / "SKILL.md"
        own_skill.parent.mkdir(parents=True)
        own_skill.write_text("---\nname: own\ndescription: mine\n---\nbody\n", encoding="utf-8")
        own_plugin = self.repo / ".agents" / "plugins" / "other" / "plugin.json"
        own_plugin.parent.mkdir(parents=True)
        own_plugin.write_text('{"name": "other"}\n', encoding="utf-8")
        self.assertEqual(self._run().returncode, 0)
        edited = self.plugin / "agents" / "generic-judge.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "owner note\n", encoding="utf-8")

        proc = self._run("--uninstall")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("! .agents/plugins/metodo/agents/generic-judge.md (kept: modified)", proc.stdout)
        self.assertEqual(self._files(), sorted(p.relative_to(self.repo).as_posix() for p in (own_skill, own_plugin, edited)))
        exclude = self.repo / ".git" / "info" / "exclude"
        self.assertIn(PLUGIN.as_posix(), exclude.read_text(encoding="utf-8").splitlines())

        edited.unlink()
        again = self._run("--uninstall")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertFalse(self.plugin.exists())
        self.assertNotIn(PLUGIN.as_posix(), exclude.read_text(encoding="utf-8").splitlines())
        self.assertTrue(own_skill.is_file() and own_plugin.is_file())

    def test_uninstall_removes_an_agent_an_older_kit_rendered(self):
        # the pre-core render is one of the candidates render_agents.py --candidates-dir writes
        self.assertEqual(self._run().returncode, 0)
        role = ROLES / "generic-judge.md"
        old = subprocess.run(["python3", str(RENDERER), str(role), "--target", "agy", "--tools-default", str(TOOLS_ROOT),
                              "--no-core"], check=True, capture_output=True, text=True).stdout
        installed = self.plugin / "agents" / role.name
        self.assertNotEqual(installed.read_text(encoding="utf-8"), old)
        installed.write_text(old, encoding="utf-8")
        proc = self._run("--uninstall")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("kept: modified", proc.stdout)
        self.assertFalse((self.repo / ".agents").exists())

    def test_uninstall_on_a_clean_repo_removes_nothing(self):
        before = _snapshot(self.repo)
        proc = self._run("--uninstall")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("summary: 0 removed, 0 kept (modified)", proc.stdout)
        self.assertEqual(_snapshot(self.repo), before)

    def test_bad_arguments_exit_2_and_write_nothing(self):
        for extra in (("--tools", str(self.tmp / "missing")), ("--nope",), ("--tools",)):
            with self.subTest(extra=extra):
                proc = self._run(*extra)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertEqual(self._files(), [])

    def test_install_sh_runtime_agy_installs_only_the_agy_plugin(self):
        proc = self._run("--runtime", "agy", script=INSTALL_SH)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("############ agy ############", proc.stdout)
        self.assertNotIn("############ claude code ############", proc.stdout)
        self.assertNotIn("############ pi ############", proc.stdout)
        self.assertTrue((self.plugin / "plugin.json").is_file())
        self.assertFalse((self.repo / ".claude").exists() or (self.repo / ".pi").exists() or (self.repo / ".mcp.json").exists())
        back = self._run("--uninstall", "--runtime", "agy", script=INSTALL_SH)
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertFalse((self.repo / ".agents").exists())

    def test_install_sh_all_still_means_claude_and_pi(self):
        # the runtimes that existed before agy behave as before: `all` installs both and no agy plugin
        proc = self._run(script=INSTALL_SH)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("############ claude code ############", proc.stdout)
        self.assertIn("############ pi ############", proc.stdout)
        self.assertNotIn("############ agy", proc.stdout)
        self.assertTrue((self.repo / ".claude" / "agents" / "generic-judge.md").is_file())
        self.assertTrue((self.repo / ".pi" / "agents" / "generic-judge.md").is_file())
        self.assertIn("metodo", json.loads((self.repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"])
        self.assertFalse((self.repo / ".agents").exists())
        exclude = (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
        self.assertNotIn(PLUGIN.as_posix(), exclude)

    def test_install_sh_rejects_an_unknown_runtime_naming_agy(self):
        proc = self._run("--runtime", "gemini", script=INSTALL_SH)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("claude, pi, agy, all", proc.stderr)

    @unittest.skipUnless(shutil.which("agy"), "agy is not installed")
    def test_agy_validates_the_installed_plugin_strictly(self):
        self.assertEqual(self._run().returncode, 0)
        proc = subprocess.run(["agy", "plugin", "validate", "--strict", "--json", str(self.plugin)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["components"]["agents"], len(list(ROLES.glob("generic-*.md"))))
        self.assertEqual(report["components"]["skills"], len(_skills()))
        self.assertEqual((report["components"]["hooks"], report["components"]["mcpServers"], report["components"]["rules"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
