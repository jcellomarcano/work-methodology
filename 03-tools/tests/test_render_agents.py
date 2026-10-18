"""lib/render_agents.py: the Claude target is the current file byte for byte
(only __TOOLS_DEFAULT__ rendered) plus the subagent core, and the pi target
maps the tool names, drops what pi has no equivalent for, appends the same
core and writes what only the contract knows as prose, role marker last."""
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
