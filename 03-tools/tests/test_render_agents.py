"""lib/render_agents.py: the Claude target is the current file byte for byte
(only __TOOLS_DEFAULT__ rendered), and the pi target maps the tool names,
drops what pi has no equivalent for, and writes the contract as prose."""
import sys
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


class RenderAgentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="render-agents-"))
        self.agent = self.tmp / "generic-example.md"
        self.agent.write_text(AGENT, encoding="utf-8")

    def test_claude_target_only_renders_the_tools_token(self):
        out = render_agents.render(self.agent, "claude", "/opt/tools", CONTRACT)
        self.assertEqual(out, AGENT.replace("__TOOLS_DEFAULT__", "/opt/tools"))
        self.assertNotIn("__TOOLS_DEFAULT__", out)

    def test_claude_target_round_trips_when_there_is_no_token(self):
        plain = AGENT.replace("${METODO_TOOLS:-__TOOLS_DEFAULT__}", "$METODO_TOOLS")
        self.agent.write_text(plain, encoding="utf-8")
        self.assertEqual(render_agents.render(self.agent, "claude", "/opt/tools", CONTRACT), plain)

    def test_pi_target_maps_tool_names(self):
        out = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT)
        self.assertIn('  - "*": false', out)
        for expected in ("  - read", "  - grep", "  - find", "  - write",
                         "  - mcp__metodo__output_write", "  - mcp__metodo__handoff_write"):
            self.assertIn(expected, out)
        self.assertNotIn("  - Glob", out)
        self.assertNotIn("model: sonnet", out)
        self.assertNotIn("maxTurns", out)

    def test_pi_target_drops_unknown_tools_with_a_comment(self):
        out = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT)
        self.assertIn("# dropped, no pi equivalent: Task", out)
        self.assertNotIn("  - Task", out)

    def test_map_tools_returns_kept_and_dropped(self):
        kept, dropped = render_agents.map_tools(["Read", "Glob", "Task", "NotebookEdit", "mcp__metodo__docs_lint"])
        self.assertEqual(kept, ["read", "find", "mcp__metodo__docs_lint"])
        self.assertEqual(dropped, ["Task", "NotebookEdit"])

    def test_pi_target_writes_the_contract_as_prose(self):
        out = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT)
        self.assertIn("## Contract (enforced by prose on this runtime)", out)
        self.assertIn("at most 40 tool calls", out)
        self.assertIn("`**/.claude/**`", out)
        self.assertIn("`out/**`", out)
        self.assertNotIn("<scope-glob-from-change-card>", out)
        self.assertIn("mcp__metodo__output_write", out)
        self.assertIn("`generic-judge`", out)
        self.assertIn("You are the **Example**.", out)

    def test_pi_target_keeps_the_body(self):
        out = render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT)
        self.assertIn("Body line two.", out)

    def test_a_file_without_frontmatter_is_an_error(self):
        self.agent.write_text("no frontmatter here\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            render_agents.render(self.agent, "pi", "/opt/tools", CONTRACT)


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class RealAgentsTests(unittest.TestCase):
    def test_every_kit_role_renders_for_both_targets(self):
        for path in sorted((TOOLS_ROOT.parent / "01-roles" / "agents").glob("generic-*.md")):
            with self.subTest(agent=path.name):
                claude = render_agents.render(path, "claude", "/opt/tools")
                self.assertEqual(claude, path.read_text(encoding="utf-8").replace("__TOOLS_DEFAULT__", "/opt/tools"))
                pi = render_agents.render(path, "pi", "/opt/tools")
                self.assertIn('  - "*": false', pi)
                self.assertIn("## Contract (enforced by prose on this runtime)", pi)


if __name__ == "__main__":
    unittest.main()
