"""bin/install-claude.sh over a temporary git repo with a pre-existing
settings.local.json (permissions + skillOverrides) and a foreign agent: installs
the kit's own, keeps the rest, is idempotent, and --uninstall removes only its own."""
import json
import os
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
        # the user scope is this test's own: never the machine's ~/.claude/settings.json
        env = dict(os.environ, METODO_CLAUDE_HOME=str(self.tmp / "claude-home"))
        return subprocess.run(["bash", str(INSTALLER), str(self.repo), *extra], capture_output=True, text=True, env=env)

    def test_auto_compact_window_respects_the_user_scope_and_leaves_no_record(self):
        # T18 (A-003/B-009): a user-scope value wins; the kit adds nothing and records nothing
        (self.tmp / "claude-home").mkdir()
        (self.tmp / "claude-home" / "settings.json").write_text('{"autoCompactWindow": 200000}', encoding="utf-8")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("autoCompactWindow", json.loads(self.settings.read_text(encoding="utf-8")))
        self.assertFalse((self.repo / ".claude" / "metodo-settings-keys.json").exists())

    def test_auto_compact_window_added_by_the_kit_goes_on_uninstall_with_its_record(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["autoCompactWindow"], 300000)
        self.assertTrue((self.repo / ".claude" / "metodo-settings-keys.json").exists())
        gone = self._run("--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        self.assertNotIn("autoCompactWindow", json.loads(self.settings.read_text(encoding="utf-8")))
        self.assertFalse((self.repo / ".claude" / "metodo-settings-keys.json").exists())

    def _untracked(self):
        out = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain", "--untracked-files=all"],
                             capture_output=True, text=True, check=True).stdout
        return sorted(line[3:] for line in out.splitlines())

    def _exclude_lines(self):
        return (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()

    def test_install_hides_the_kit_files_from_git_and_leaves_the_repos_own_visible(self):
        # live probe 2026-11-13 (F1): an agent's `git add -A` committed 46 kit files into the user's repo
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._untracked(), [".claude/agents/domain-redteam.md"])
        # an agent or a skill the repo adds later is still the repo's to commit
        (self.repo / ".claude" / "agents" / "team-reviewer.md").write_text("---\nname: team-reviewer\n---\n", encoding="utf-8")
        (self.repo / ".claude" / "skills" / "our-own").mkdir()
        (self.repo / ".claude" / "skills" / "our-own" / "SKILL.md").write_text("---\nname: our-own\n---\n", encoding="utf-8")
        self.assertEqual(self._untracked(), [".claude/agents/domain-redteam.md", ".claude/agents/team-reviewer.md",
                                             ".claude/skills/our-own/SKILL.md"])
        before = self._exclude_lines()
        self.assertEqual(len(before), len(set(before)))
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self._exclude_lines(), before)

    def test_an_exclude_file_with_no_final_newline_keeps_the_users_last_pattern(self):
        # verifier B1, 2026-11-13: `echo >>` glued the first kit line onto the user's `*.log`
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("*.log", encoding="utf-8")
        (self.repo / "debug.log").write_text("x\n", encoding="utf-8")
        self.assertEqual(self._run().returncode, 0)
        lines = self._exclude_lines()
        for entry in ("*.log", ".mcp.json", ".claude/agents/generic-*.md"):
            self.assertIn(entry, lines)
        self.assertEqual(self._untracked(), [".claude/agents/domain-redteam.md"])
        # the same file, cut again after an install: the second pass must not glue either
        exclude.write_text(exclude.read_text(encoding="utf-8").replace(".claude/skills/cartography\n", "") + "*.tmp", encoding="utf-8")
        self.assertEqual(self._run().returncode, 0)
        lines = self._exclude_lines()
        self.assertIn("*.tmp", lines)
        self.assertIn(".claude/skills/cartography", lines)

    def test_uninstall_drops_each_exclude_line_once_its_path_is_gone(self):
        self.assertEqual(self._run().returncode, 0)
        skill = self.repo / ".claude" / "skills" / "receipt-review" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nedited by the repo\n", encoding="utf-8")
        gone = self._run("--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        lines = self._exclude_lines()
        # the edited skill stays, and so does the line that keeps it out of commits
        self.assertIn(".claude/skills/receipt-review", lines)
        self.assertIn("= info/exclude#.claude/skills/receipt-review (kept: .claude/skills/receipt-review still exists)", gone.stdout)
        # settings.local.json held the repo's own keys before the kit came: it stays, with its line
        self.assertIn(".claude/settings.local.json", lines)
        for entry in (".claude/agents/generic-*.md", ".claude/agents/generic-*.contract.json",
                      ".claude/metodo-settings-keys.json", ".claude/skills/cartography"):
            self.assertNotIn(entry, lines)
            self.assertIn(f"- info/exclude#{entry} (removed)", gone.stdout)
        self.assertEqual(self._untracked(), [".claude/agents/domain-redteam.md"])

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

    def test_a_build_file_is_never_installed_compared_or_removed(self):
        """02-skills/<skill>/BUILD.json says how the kit builds a skill: it is not a skill file."""
        skill = "change-card"
        self.assertTrue((SKILLS_SRC / skill / "BUILD.json").is_file())

        def pi(*extra):
            return subprocess.run(["bash", str(PI_INSTALLER), str(self.repo), *extra], capture_output=True, text=True)

        for proc in (self._run(), pi()):
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("BUILD.json", proc.stdout)
        self.assertEqual(sorted(p.relative_to(self.repo).as_posix() for p in self.repo.rglob("BUILD.json")), [])
        installed = [self.repo / runtime / "skills" / skill for runtime in (".claude", ".pi")]
        for folder in installed:
            # negative control: the skill itself is installed as before
            self.assertEqual((folder / "SKILL.md").read_bytes(), (SKILLS_SRC / skill / "SKILL.md").read_bytes())
            # a file of that name the owner put there is not the kit's to compare or remove
            (folder / "BUILD.json").write_text('{"mine": true}\n', encoding="utf-8")
        for proc in (self._run("--uninstall"), pi("--uninstall")):
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("BUILD.json", proc.stdout)
        for folder in installed:
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["BUILD.json"])
            self.assertEqual((folder / "BUILD.json").read_text(encoding="utf-8"), '{"mine": true}\n')

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

    def test_an_exclude_file_with_no_final_newline_keeps_the_users_last_pattern(self):
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("*.log", encoding="utf-8")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = exclude.read_text(encoding="utf-8").splitlines()
        for entry in ("*.log", ".mcp.json", ".pi/agents", ".pi/mcp.json"):
            self.assertIn(entry, lines)

    def test_pi_gets_the_whole_mcp_server_and_is_told_what_pi_needs(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        entry = json.loads((self.repo / ".pi" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["metodo"]
        self.assertEqual(entry["command"], "python3")
        self.assertTrue(entry["args"][0].endswith("/mcp/server.py"), entry)
        self.assertEqual(entry["env"]["METODO_REPO"], str(self.repo))
        self.assertEqual((entry["exposure"], entry["toolPrefix"]), ("direct", "mcp"))
        # F3: pi skips project files in an untrusted project, silently in print mode; the install says so
        self.assertIn("--approve", proc.stdout)
        self.assertIn("pi mcp list", proc.stdout)
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('"changed": false', second.stdout)
        gone = self._run("--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        self.assertFalse((self.repo / ".pi" / "mcp.json").exists())

    def test_an_owners_metodo_server_in_pi_mcp_json_survives_install_and_uninstall(self):
        theirs = json.dumps({"mcpServers": {"metodo": {"command": "node", "args": ["mine.js"], "env": {"X": "1"}}}})
        (self.repo / ".pi").mkdir()
        (self.repo / ".pi" / "mcp.json").write_text(theirs, encoding="utf-8")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("not the kit's", proc.stderr)
        self.assertEqual((self.repo / ".pi" / "mcp.json").read_text(encoding="utf-8"), theirs)
        self.assertEqual(self._run("--uninstall").returncode, 0)
        self.assertEqual((self.repo / ".pi" / "mcp.json").read_text(encoding="utf-8"), theirs)

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


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class InstalledTextRulesTests(unittest.TestCase):
    """Key lines the installers carry into every repo: the core's stop rule, the
    proposer's build lock and the review skills' routing steps (L13)."""

    def _skill(self, name: str) -> str:
        return (SKILLS_SRC / name / "SKILL.md").read_text(encoding="utf-8")

    def test_core_marks_any_early_stop_truncated(self):
        core = _source_core()
        self.assertIn("Whenever you stop before your STOP condition", core)
        for cause in ("budget deny", "context", "tool limit"):
            self.assertIn(cause, core)
        self.assertIn("`truncated: true`", core)
        self.assertIn("`not_covered`", core)
        # negative control: the safety lines stay in the core
        for line in ("Never edit shared build files or `.claude/**`", "never spawn agents", "the owner's; report"):
            self.assertIn(line, core)

    def test_proposer_builds_only_under_the_lock(self):
        body = (TOOLS_ROOT.parent / "01-roles" / "agents" / "generic-proposer.md").read_text(encoding="utf-8")
        self.assertIn("mcp__metodo__verify_sectors", body)
        # the exact lock directory bin/verify-sectors.sh takes
        self.assertIn('LOCK_DIR="$TOOLS_ROOT/out/.build.lock"',
                      (TOOLS_ROOT / "bin" / "verify-sectors.sh").read_text(encoding="utf-8"))
        self.assertIn("${METODO_TOOLS:-__TOOLS_DEFAULT__}/out/.build.lock", body)
        self.assertRegex(body, r"absent[^.]*\.[^.]*stop and report|exists, stop and report")

    def test_review_skills_route_fable_once_with_owner_named_and_budget(self):
        for name in ("receipt-review", "adversarial-round"):
            text = self._skill(name)
            with self.subTest(skill=name):
                for needed in ("owner_named", "requires_approval", "approvals", "max_context_tokens",
                               "generic-deep-reasoner", "BUDGET"):
                    self.assertIn(needed, text)
                self.assertRegex(text, r"before the first launch")
                self.assertRegex(text, r"only the newly approved entry")


class FrontMatterIsStrictYamlTests(unittest.TestCase):
    """pi parses skill and agent front matter with a strict YAML parser and drops
    the file on an error; Claude Code is lenient, so the defect only shows there.
    The kit ships no YAML parser: this checks the one rule plain scalars break."""

    PLAIN_BREAKERS = (": ", " #")

    def _plain_scalar_problems(self, path):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return []
        block = text.split("---\n", 2)[1]
        problems = []
        for number, line in enumerate(block.splitlines(), start=2):
            found = re.match(r"^([A-Za-z_][\w-]*):[ \t]+(.*)$", line)
            if not found:
                continue
            value = found.group(2).strip()
            if not value or value[0] in "\"'[{|>":
                continue
            for breaker in self.PLAIN_BREAKERS:
                if breaker in value:
                    problems.append(f"{path.parent.name}/{path.name}:{number} `{found.group(1)}` holds {breaker!r} unquoted")
        return problems

    def test_no_skill_or_agent_front_matter_breaks_a_strict_parser(self):
        files = sorted(SKILLS_SRC.glob("*/SKILL.md")) + sorted((TOOLS_ROOT.parent / "01-roles" / "agents").glob("*.md"))
        self.assertGreater(len(files), 20)
        problems = [p for f in files for p in self._plain_scalar_problems(f)]
        self.assertEqual(problems, [])

    def test_the_check_catches_an_unquoted_colon_and_accepts_the_quoted_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "SKILL.md"
            bad.write_text("---\nname: x\ndescription: Writes a comment: one paragraph.\n---\nbody: not front matter\n", encoding="utf-8")
            self.assertEqual(len(self._plain_scalar_problems(bad)), 1)
            bad.write_text('---\nname: x\ndescription: "Writes a comment: one paragraph."\ntools: [Read, Write]\n---\n', encoding="utf-8")
            self.assertEqual(self._plain_scalar_problems(bad), [])
