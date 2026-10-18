"""lib/render_agents.py: the Claude target is the current file byte for byte
(only __TOOLS_DEFAULT__ rendered) plus the subagent core, and the pi target
maps the tool names, drops what pi has no equivalent for, appends the same
core and writes what only the contract knows as prose, role marker last."""
import json
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import render_agents  # noqa: E402

AGENT = """---
name: generic-example
description: An example role, nothing more.
tools: Read, Grep, Glob, Task, Write, mcp__metodo__output_write, mcp__metodo__handoff_write
model: sonnet
maxTurns: 50
hooks:
  Stop:
    - hooks:
        - type: command
          command: ': metodo-hook; H="${METODO_TOOLS:-__TOOLS_DEFAULT__}/hooks"; exit 0'
---

You are the **Example**.

Body line two.
"""

CONTRACT = {
    "agent": "generic-example",
    "tools": ["Read", "Grep", "Glob", "Task", "Write", "mcp__metodo__output_write", "mcp__metodo__handoff_write"],
    "forbidden_paths": ["**/.claude/**"],
    "may_write": ["<scope-glob-from-change-card>", "out/**"],
    "handoff_targets": ["generic-judge"],
    "max_tool_calls": 40,
}

CORE = "- core rule one.\n- core rule two."
CORE_TAIL = "\n## Kit core\n\n" + CORE + "\n"


class RenderAgentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="render-agents-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.agent = self.tmp / "generic-example.md"
        self.agent.write_text(AGENT, encoding="utf-8")

    def render(self, target):
        return render_agents.render(self.agent, target, "/opt/tools", CONTRACT, CORE)

    def test_claude_target_renders_the_tools_token_and_appends_the_core(self):
        out = self.render("claude")
        self.assertEqual(out, AGENT.replace("__TOOLS_DEFAULT__", "/opt/tools") + CORE_TAIL)
        self.assertNotIn("__TOOLS_DEFAULT__", out)

    def test_claude_target_round_trips_when_there_is_no_token(self):
        plain = AGENT.replace("${METODO_TOOLS:-__TOOLS_DEFAULT__}", "$METODO_TOOLS")
        self.agent.write_text(plain, encoding="utf-8")
        self.assertEqual(self.render("claude"), plain + CORE_TAIL)

    def test_pi_target_carries_the_core_before_the_contract(self):
        out = self.render("pi")
        self.assertEqual(out.count(CORE), 1)
        self.assertLess(out.index("Body line two."), out.index("## Kit core"))
        self.assertLess(out.index(CORE), out.index("## Contract"))

    def test_core_comes_from_the_marked_section_only(self):
        source = self.tmp / "pack.md"
        source.write_text("# Pack\nintro\n<!-- subagent-core:start -->\n" + CORE + "\n<!-- subagent-core:end -->\nafter\n",
                          encoding="utf-8")
        self.assertEqual(render_agents.load_core(source), CORE)

    def test_a_missing_core_section_is_an_error(self):
        # negative control: an agent is never rendered without its cold-start rules
        source = self.tmp / "pack.md"
        source.write_text("# Pack without markers\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            render_agents.load_core(source)
        with self.assertRaises(ValueError):
            render_agents.load_core(self.tmp / "absent.md")

    def test_pi_target_maps_tool_names(self):
        out = self.render("pi")
        self.assertIn('  - "*": false', out)
        for expected in ("  - read", "  - grep", "  - find", "  - write",
                         "  - mcp__metodo__output_write", "  - mcp__metodo__handoff_write"):
            self.assertIn(expected, out)
        self.assertNotIn("  - Glob", out)
        self.assertNotIn("model: sonnet", out)
        self.assertNotIn("maxTurns", out)

    def test_pi_target_drops_unknown_tools_with_a_comment(self):
        out = self.render("pi")
        self.assertIn("# dropped, no pi equivalent: Task", out)
        self.assertNotIn("  - Task", out)

    def test_map_tools_returns_kept_and_dropped(self):
        kept, dropped = render_agents.map_tools(["Read", "Glob", "Task", "NotebookEdit", "mcp__metodo__docs_lint"])
        self.assertEqual(kept, ["read", "find", "mcp__metodo__docs_lint"])
        self.assertEqual(dropped, ["Task", "NotebookEdit"])

    def test_pi_target_writes_the_contract_as_prose(self):
        out = self.render("pi")
        self.assertIn("## Contract (partly enforced by the extension on this runtime)", out)
        self.assertIn("at most 40 tool calls", out)
        self.assertIn("`**/.claude/**`", out)
        self.assertIn("`out/**`", out)
        self.assertNotIn("<scope-glob-from-change-card>", out)
        self.assertIn("Hand off to: `generic-judge`", out)
        self.assertIn("You are the **Example**.", out)
        # the shared rules live in the core and the output call in the body: not repeated here
        section = out[out.index("## Contract"):]
        for gone in ("truncated", "Delivery", "shared build files", "FAIL"):
            self.assertNotIn(gone, section)

    def test_pi_target_carries_the_role_marker(self):
        # hooks/pi/metodo-hooks.ts reads this marker to know which contract the subagent runs under
        out = self.render("pi")
        self.assertEqual(out.count("<!-- metodo-role: generic-example -->"), 1)
        self.assertTrue(out.rstrip("\n").endswith("<!-- metodo-role: generic-example -->"))

    def test_claude_target_has_no_role_marker(self):
        self.assertNotIn("metodo-role", self.render("claude"))

    def test_pi_target_keeps_the_body(self):
        out = self.render("pi")
        self.assertIn("Body line two.", out)

    def test_a_file_without_frontmatter_is_an_error(self):
        self.agent.write_text("no frontmatter here\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.render("pi")


class LegacyFormatTests(unittest.TestCase):
    """The pre-core format (what the kit installed before the subagent core): uninstall
    must recognise it, so render can still produce it on request."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="render-legacy-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.agent = self.tmp / "generic-example.md"
        self.agent.write_text(AGENT, encoding="utf-8")

    def test_claude_without_core_is_the_source_with_the_token_rendered(self):
        out = render_agents.render(self.agent, "claude", "/opt/tools", CONTRACT, CORE, with_core=False)
        self.assertEqual(out, AGENT.replace("__TOOLS_DEFAULT__", "/opt/tools"))

    def test_pi_without_core_keeps_contract_and_marker(self):
        out = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT, CORE, with_core=False)
        self.assertNotIn("## Kit core", out)
        self.assertNotIn(CORE, out)
        self.assertIn("## Contract (partly enforced by the extension on this runtime)", out)
        self.assertTrue(out.rstrip("\n").endswith("<!-- metodo-role: generic-example -->"))
        # negative control: removing the core section from the current render gives the same text
        full = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT, CORE)
        self.assertEqual(out, full.replace(render_agents.core_section(CORE) + "\n", ""))

    def test_cli_no_core_flag(self):
        out = self.tmp / "out.md"
        code = render_agents.main([str(self.agent), "--target", "claude", "--tools-default", "/opt/tools",
                                   "--no-core", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(encoding="utf-8"), AGENT.replace("__TOOLS_DEFAULT__", "/opt/tools"))


# A renderer as an older kit shipped it: no core, its own output format. Uninstall
# must reproduce what THAT renderer wrote, not what today's renderer would write.
OLD_RENDERER = '''import argparse
from pathlib import Path
CORE_SOURCE = Path(__file__).resolve().parent / "unused"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("agent")
    p.add_argument("--target")
    p.add_argument("--tools-default")
    p.add_argument("--out")
    a = p.parse_args(argv)
    text = Path(a.agent).read_text(encoding="utf-8").replace("__TOOLS_DEFAULT__", a.tools_default)
    Path(a.out).write_text("OLD " + a.target + "\\n" + text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


class HistoryCandidatesTests(unittest.TestCase):
    """past_renders: every committed version of an agent, rendered by the renderer and
    core committed with it, so an uninstall after a kit upgrade still finds its file."""

    def setUp(self):
        import os
        import subprocess

        self.tmp = Path(tempfile.mkdtemp(prefix="render-history-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        gitconfig = self.tmp / "gitconfig"
        gitconfig.write_text("[user]\n\temail = t@example.com\n\tname = t\n[commit]\n\tgpgsign = false\n",
                             encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
        self.kit = self.tmp / "kit"
        self.agent = self.kit / "01-roles" / "agents" / "generic-example.md"
        self.agent.parent.mkdir(parents=True)
        (self.kit / "03-tools" / "lib").mkdir(parents=True)
        self.run_git = lambda *a: subprocess.run(["git", "-C", str(self.kit), *a], check=True,
                                                 capture_output=True, env=self.env)
        self.run_git("init", "-q")
        self.renderer = self.kit / "03-tools" / "lib" / "render_agents.py"
        self.pack = self.kit / "CONTEXT-PACK.md"
        self.contract = self.agent.with_name("generic-example.contract.json")
        self.v1 = AGENT.replace("Body line two.", "Version one.")
        self.v2 = AGENT.replace("Body line two.", "Version two.")
        self.v3 = AGENT.replace("Body line two.", "Version three, today.")
        # rev 1: an old renderer without a core
        self.commit({self.renderer: OLD_RENDERER, self.agent: self.v1, self.contract: json.dumps(CONTRACT),
                     self.pack: "# Pack\n"}, "v1")
        # rev 2: today's renderer and a core
        self.commit({self.renderer: (TOOLS_ROOT / "lib" / "render_agents.py").read_text(encoding="utf-8"),
                     self.agent: self.v2, self.pack: self.pack_with("- core v2.")}, "v2")
        # rev 3: the core changes, the agent does not
        self.commit({self.pack: self.pack_with("- core v3.")}, "v3")
        # working tree: the agent moves on, uncommitted
        self.agent.write_text(self.v3, encoding="utf-8")

    @staticmethod
    def pack_with(core: str) -> str:
        return f"# Pack\n<!-- subagent-core:start -->\n{core}\n<!-- subagent-core:end -->\n"

    def commit(self, files: dict, message: str) -> None:
        for path, text in files.items():
            path.write_text(text, encoding="utf-8")
        self.run_git("add", "-A")
        self.run_git("commit", "-q", "-m", message)

    def test_claude_history_covers_old_renderer_and_each_core(self):
        got = render_agents.past_renders(self.agent, "claude", "/opt/tools", self.kit)
        tok = lambda t: t.replace("__TOOLS_DEFAULT__", "/opt/tools")  # noqa: E731
        self.assertIn("OLD claude\n" + tok(self.v1), got)
        self.assertIn(render_agents.render_claude(self.v2, "/opt/tools", "- core v2."), got)
        self.assertIn(render_agents.render_claude(self.v2, "/opt/tools", "- core v3."), got)
        # negative control: the uncommitted working-tree version is not history
        self.assertFalse(any("Version three" in g for g in got))
        self.assertEqual(len(got), len(set(got)))

    def test_pi_history_uses_the_contract_committed_with_the_agent(self):
        got = render_agents.past_renders(self.agent, "pi", "/opt/tools", self.kit)
        self.assertIn("OLD pi\n" + self.v1.replace("__TOOLS_DEFAULT__", "/opt/tools"), got)
        self.assertIn(render_agents.render_pi(self.v2.replace("__TOOLS_DEFAULT__", "/opt/tools"), CONTRACT,
                                              "- core v3."), got)

    def test_a_kit_that_is_not_a_git_checkout_has_no_history(self):
        plain = self.tmp / "plain"
        shutil.copytree(self.kit, plain, ignore=shutil.ignore_patterns(".git"))
        agent = plain / "01-roles" / "agents" / "generic-example.md"
        self.assertEqual(render_agents.past_renders(agent, "claude", "/opt/tools", plain), [])

    def test_candidates_cli_writes_current_legacy_and_history(self):
        import contextlib
        import io

        out = self.tmp / "cands"
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = render_agents.main([str(self.agent), "--target", "claude", "--tools-default", "/opt/tools",
                                       "--core-source", str(self.pack), "--kit-root", str(self.kit),
                                       "--candidates-dir", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed.getvalue()), {"history": True})
        texts = {p.read_text(encoding="utf-8") for p in (out / "generic-example.md").iterdir()}
        today = self.v3.replace("__TOOLS_DEFAULT__", "/opt/tools")
        self.assertIn(render_agents.render_claude(self.v3, "/opt/tools", "- core v3."), texts)
        self.assertIn(today, texts)
        self.assertIn("OLD claude\n" + self.v1.replace("__TOOLS_DEFAULT__", "/opt/tools"), texts)


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class RealAgentsTests(unittest.TestCase):
    def test_every_kit_role_renders_for_both_targets(self):
        for path in sorted((TOOLS_ROOT.parent / "01-roles" / "agents").glob("generic-*.md")):
            with self.subTest(agent=path.name):
                claude = render_agents.render(path, "claude", "/opt/tools")
                source = path.read_text(encoding="utf-8").replace("__TOOLS_DEFAULT__", "/opt/tools")
                self.assertEqual(claude, source.rstrip("\n") + "\n\n" + render_agents.core_section(render_agents.load_core()))
                pi = render_agents.render(path, "pi", "/opt/tools")
                self.assertIn('  - "*": false', pi)
                self.assertIn("## Contract (partly enforced by the extension on this runtime)", pi)


if __name__ == "__main__":
    unittest.main()
