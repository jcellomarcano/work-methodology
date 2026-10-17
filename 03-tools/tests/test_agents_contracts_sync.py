"""The 11 generic-* agents and their contracts say the same thing: tools, model,
maxTurns/max_turns; every mcp__metodo__X tool exists in the catalog;
the roles the catalog lists for a tool carry it in their
frontmatter; Bash only in proposer and verifier; every role carries the
output hook; no body carries an em dash."""
import json
import re
import unittest
from pathlib import Path

from lib import round_files
from mcp import catalog

KIT_ROOT = Path(__file__).resolve().parent.parent.parent
# The instance does not carry `01-roles/`: it keeps the same pairs in `claude/agents/`.
# Without this second path the guard was skipped whole, right where the drift lives,
# and on 15-sep two adversaries were left with no way to write their artifact
# because the instance's contract said Bash and the installed agent said
# mcp__metodo__output_write. Measured: 7 skipped in the instance, 7 passed in the kit.
AGENTS = KIT_ROOT / "01-roles" / "agents"
if not AGENTS.is_dir():
    AGENTS = Path(__file__).resolve().parent.parent / "claude" / "agents"
BASH_ROLES = {"generic-proposer", "generic-verifier"}


def frontmatter(text: str) -> dict:
    end = text.index("\n---\n", 4)
    fields = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^(\w+):\s*(.*)$", line)
        if match and not line.startswith(" "):
            fields[match.group(1)] = match.group(2).strip()
    fields["_raw"] = text[4:end]
    return fields


@unittest.skipUnless(AGENTS.is_dir(), "kit only: the instance does not carry 01-roles/")
class AgentsContractsSyncTests(unittest.TestCase):
    def setUp(self):
        self.pairs = {}
        for md in sorted(AGENTS.glob("generic-*.md")):
            contract = json.loads((AGENTS / f"{md.stem}.contract.json").read_text(encoding="utf-8"))
            self.pairs[md.stem] = (frontmatter(md.read_text(encoding="utf-8")), contract, md.read_text(encoding="utf-8"))
        self.assertEqual(sorted(self.pairs), sorted(round_files.ROLES))

    def test_tools_model_and_turns_match(self):
        for role, (fm, contract, _) in self.pairs.items():
            tools = [t.strip() for t in fm["tools"].split(",") if t.strip()]
            self.assertEqual(sorted(tools), sorted(contract["tools"]), role)
            self.assertEqual(fm["model"], contract["model"], role)
            self.assertEqual(int(fm["maxTurns"]), contract["max_turns"], role)
            self.assertGreater(contract["max_turns"], contract["max_tool_calls"], role)

    def test_every_mcp_tool_exists_in_catalog(self):
        for role, (_, contract, _) in self.pairs.items():
            for tool in contract["tools"]:
                if tool.startswith("mcp__metodo__"):
                    self.assertIn(tool[len("mcp__metodo__"):], catalog.BY_NAME, f"{role}: {tool}")

    def test_catalog_roles_are_reflected_in_frontmatter(self):
        for spec in catalog.TOOLS:
            for short in spec.roles:
                role = f"generic-{short}"
                self.assertIn(f"mcp__metodo__{spec.name}", self.pairs[role][1]["tools"], f"{spec.name} -> {role}")

    def test_bash_only_where_gradle_is_needed(self):
        for role, (_, contract, _) in self.pairs.items():
            has_bash = "Bash" in contract["tools"]
            self.assertEqual(has_bash, role in BASH_ROLES, role)

    def test_write_is_always_fenced_to_the_round_directory(self):
        """Write exists as an emergency exit for when the MCP is not up.

        What cannot exist is an unfenced Write: guard_paths.py can only
        veto a path if the contract declares may_write, so a role with Write
        and empty may_write would write wherever it wanted.
        """
        for role, (_, contract, _) in self.pairs.items():
            if "Write" not in contract["tools"]:
                continue
            allow = contract.get("may_write") or []
            self.assertTrue(allow, f"{role}: Write sin may_write")
            for glob in allow:
                self.assertTrue(
                    "round-" in glob or "scratchpad" in glob,
                    f"{role}: may_write {glob} sale del directorio de ronda")

    def test_every_role_declares_the_output_hook_and_output_write(self):
        for role, (fm, contract, _) in self.pairs.items():
            self.assertIn("validate_subagent_output.py", fm["_raw"], role)
            self.assertIn("metodo-hook", fm["_raw"], role)
            self.assertIn("mcp__metodo__output_write", contract["tools"], role)

    def test_bodies_point_to_schema_files_and_have_no_em_dash(self):
        for role, (_, _, text) in self.pairs.items():
            self.assertNotIn("—", text, role)
            self.assertNotIn("Inline schema", text, role)
            self.assertIn(f"schemas/{round_files.ROLE_SCHEMA[role]}.schema.json", text, role)

    def test_negative_control_detects_a_missing_tool(self):
        fm, contract, _ = self.pairs["generic-judge"]
        tools = [t.strip() for t in fm["tools"].split(",")]
        broken = dict(contract, tools=[t for t in contract["tools"] if t != "Read"])
        self.assertNotEqual(sorted(tools), sorted(broken["tools"]))
