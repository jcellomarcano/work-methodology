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

    def test_an_exclude_file_with_no_final_newline_keeps_the_users_last_pattern(self):
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("*.log", encoding="utf-8")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = exclude.read_text(encoding="utf-8").splitlines()
        self.assertIn("*.log", lines)
        self.assertIn(PLUGIN.as_posix(), lines)

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
            # BUILD.json is the kit's build declaration of the skill, not one of its files
            for src in sorted(p for p in (SKILLS_SRC / skill).iterdir() if p.is_file() and p.name != "BUILD.json"):
                data = src.read_bytes()
                with self.subTest(skill=skill, file=src.name):
                    self.assertEqual((self.plugin / "skills" / skill / src.name).read_bytes(),
                                     data.replace(b"__TOOLS_DEFAULT__", str(TOOLS_ROOT).encode()))

    def test_a_build_file_never_enters_the_plugin(self):
        skill = "change-card"
        self.assertTrue((SKILLS_SRC / skill / "BUILD.json").is_file())
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("BUILD.json", proc.stdout)
        self.assertEqual([path for path in self._files() if path.endswith("BUILD.json")], [])
        # negative control: the skill itself is in the plugin as before
        self.assertEqual((self.plugin / "skills" / skill / "SKILL.md").read_bytes(),
                         (SKILLS_SRC / skill / "SKILL.md").read_bytes())

    def test_contracts_ship_in_a_folder_of_their_own_byte_for_byte(self):
        self.assertEqual(self._run().returncode, 0)
        contracts = sorted(ROLES.glob("generic-*.contract.json"))
        self.assertTrue(contracts)
        self.assertEqual(sorted(p.name for p in (self.plugin / "contracts").iterdir()), [p.name for p in contracts])
        for src in contracts:
            with self.subTest(contract=src.name):
                self.assertEqual((self.plugin / "contracts" / src.name).read_bytes(), src.read_bytes())
        # agy reads agents/ as subagents: a contract never lands there
        self.assertEqual([p.name for p in (self.plugin / "agents").iterdir() if p.suffix != ".md"], [])

    def test_uninstall_keeps_a_modified_contract_and_removes_the_rest(self):
        self.assertEqual(self._run().returncode, 0)
        edited = self.plugin / "contracts" / "generic-proposer.contract.json"
        edited.write_text(edited.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        proc = self._run("--uninstall")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("! .agents/plugins/metodo/contracts/generic-proposer.contract.json (kept: modified)", proc.stdout)
        self.assertIn("- .agents/plugins/metodo/contracts/generic-judge.contract.json (removed)", proc.stdout)
        self.assertEqual(self._files(), [edited.relative_to(self.repo).as_posix()])

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
        # agy 1.5.8 asks for a version (a warning, which --strict fails on) and notes a missing
        # logo (cosmetic): the manifest carries the first, the second is not a defect
        self.assertEqual([f for f in report["findings"] if f.get("severity") != "note"], [])
        self.assertEqual(report["components"]["agents"], len(list(ROLES.glob("generic-*.md"))))
        self.assertEqual(report["components"]["skills"], len(_skills()))
        self.assertEqual((report["components"]["hooks"], report["components"]["mcpServers"], report["components"]["rules"]), (1, 1, 1))


@unittest.skipUnless(ROLES.is_dir(), "kit only: the instance does not carry 01-roles/")
class AgyOnlyInstanceTests(unittest.TestCase):
    """An agy-only repo (no .claude/) whose tools root is a synced instance: the
    instance carries no 01-roles/, so the role contracts the plugin ships are the
    only ones the guards can find. Every call runs the PreToolUse command of the
    installed hooks.json with the stdin agy 1.4.7 sends, in block mode."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="agy-instance-"))
        cls.instance = cls.root / "instance"
        cls.instance.mkdir()
        proc = subprocess.run(["bash", str(TOOLS_ROOT / "bin" / "sync-instance.sh"), str(cls.instance)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout[-2000:] + proc.stderr[-2000:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        from tests.test_agy_bridge import BRIEF
        self.brief = BRIEF
        self.tmp = Path(tempfile.mkdtemp(prefix="agy-only-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        (self.repo / "app").mkdir(parents=True)
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app" / "Foo.kt").write_text("class Foo\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init")
        base = {k: v for k, v in os.environ.items() if not k.startswith("METODO_") and k != "CLAUDE_PROJECT_DIR"}
        proc = subprocess.run(["bash", str(INSTALLER), str(self.repo), "--tools", str(self.instance)],
                              capture_output=True, text=True, env=dict(base, METODO_MEMORY="off"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.instance.parent / "01-roles").exists())
        hooks = json.loads((self.repo / PLUGIN / "hooks.json").read_text(encoding="utf-8"))["metodo"]
        self.command = hooks["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(str(self.instance), self.command)
        config = self.tmp / "project.json"
        config.write_text(json.dumps({"shared_build_files": ["settings.gradle", "app/build.gradle"],
                                      "rdd": {"enabled": True, "mode": "block", "hook_modes": {}, "exempt_globs": ["**/*.md"]}}),
                          encoding="utf-8")
        self.hooks_dir = self.tmp / "hooks-out"
        self.env = dict(base, METODO_MEMORY="off", METODO_PROJECT_CONFIG=str(config), METODO_HOOKS_DIR=str(self.hooks_dir),
                        METODO_RDD_DIR=str(self.tmp / "rdd"), METODO_ROUTING_LOG=str(self.tmp / "runs" / "routing.jsonl"),
                        METODO_RUNS_DIR=str(self.tmp / "runs-dir"))

    def _transcript(self, conversation: str, first: dict) -> str:
        path = self.tmp / "brain" / conversation / "transcript_full.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(first) + "\n", encoding="utf-8")
        return str(path)

    def _owner(self) -> tuple[str, str]:
        return "owner-1", self._transcript("owner-1", {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                                                       "content": "<USER_REQUEST>do it</USER_REQUEST>"})

    def _child(self, prompt: str) -> tuple[str, str]:
        content = ("The following is a <SYSTEM_MESSAGE> not actually sent by the user.\n\n<SYSTEM_MESSAGE>\n"
                   "[Message] timestamp=2026-10-26T16:34:16Z sender=owner-1 priority=MESSAGE_PRIORITY_HIGH "
                   f"content={prompt}\n</SYSTEM_MESSAGE>")
        return "child-1", self._transcript("child-1", {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE",
                                                       "content": content})

    def _pre(self, who: tuple[str, str], name: str, args: dict) -> dict | None:
        """The installed hook's verdict: None when it stays neutral (empty stdout)."""
        body = {"workspacePaths": [str(self.repo)], "modelName": "auto", "conversationId": who[0], "transcriptPath": who[1],
                "stepIdx": 3, "toolCall": {"name": name, "args": args}}
        proc = subprocess.run(["bash", "-c", self.command], input=json.dumps(body), capture_output=True, text=True,
                              env=self.env, cwd=str(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def _launch(self, who, type_name: str) -> dict | None:
        return self._pre(who, "invoke_subagent", {"TypeName": type_name, "Prompt": self.brief, "Role": "r"})

    def test_a_valid_launch_of_a_kit_role_is_silent(self):
        self.assertIsNone(self._launch(self._owner(), "generic-proposer"))
        self.assertFalse((self.hooks_dir / "owner-1" / "ledger.jsonl").exists())

    def test_a_role_mismatch_is_denied(self):
        out = self._launch(self._owner(), "generic-challenger")
        self.assertEqual(out["decision"], "deny")
        self.assertIn("the launched role is generic-challenger", out["reason"])

    def test_a_proposer_child_may_not_launch_the_challenger(self):
        self.assertIsNone(self._launch(self._owner(), "generic-proposer"))
        out = self._launch(self._child(self.brief), "generic-challenger")
        self.assertEqual(out["decision"], "deny")
        self.assertIn("may_spawn", out["reason"])

    def test_budget_counts_and_denies_past_the_role_cap(self):
        cap = json.loads((ROLES / "generic-proposer.contract.json").read_text(encoding="utf-8"))["max_tool_calls"]
        self.assertIsNone(self._launch(self._owner(), "generic-proposer"))
        child = self._child(self.brief)
        read = {"Path": str(self.repo / "app" / "Foo.kt")}
        self.assertIsNone(self._pre(child, "read_file", read))
        counter = self.hooks_dir / "child-1" / "budget-generic-proposer-child-1.count"
        self.assertEqual(counter.read_text(encoding="utf-8").strip(), "1")
        counter.write_text(f"{cap}\n", encoding="utf-8")
        out = self._pre(child, "read_file", read)
        self.assertEqual(out["decision"], "deny")
        self.assertIn(f"budget exhausted ({cap} tool calls)", out["reason"])

    def test_the_child_cannot_rewrite_its_own_contract(self):
        self.assertIsNone(self._launch(self._owner(), "generic-proposer"))
        path = self.repo / PLUGIN / "contracts" / "generic-proposer.contract.json"
        out = self._pre(self._child(self.brief), "write_file", {"Path": str(path), "Content": "{}\n", "Overwrite": True})
        self.assertEqual(out["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
