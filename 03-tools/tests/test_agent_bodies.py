"""The 11 generic-* agent bodies after the text audit (S8, C7): no boilerplate
block repeated across bodies, no Spanish leftovers in model-facing text, no
`../` pointer that breaks once installed, the subagent core from
CONTEXT-PACK.md appended byte for byte to every rendered agent (Claude Code
and pi, the pi role marker still last), and the lines no hook covers still
present per role (IRON LAW, evidence rule, output_write with its schema)."""
import json
import re
import unittest
from pathlib import Path

from lib import render_agents, round_files
from mcp import catalog

TOOLS_ROOT = Path(__file__).resolve().parent.parent
KIT_ROOT = TOOLS_ROOT.parent
AGENTS = KIT_ROOT / "01-roles" / "agents"
CONTEXT_PACK = KIT_ROOT / "CONTEXT-PACK.md"
CORE_START = "<!-- subagent-core:start -->"
CORE_END = "<!-- subagent-core:end -->"
SPANISH = re.compile(r"\b(Medido|Probado|Inferido|Asumido|Desconocido|Verificador|Confrontador)\b")
# Model-facing files outside the agent bodies that must speak English.
MODEL_FACING = ("04-templates/brief.md", "04-templates/findings.example.json", "07-communication/identity.en.md")
MIN_WORDS = 12
MAX_BODIES = 2
# Role-specific prohibitions that define the role (text-audit section 6, "Do not cut").
ROLE_LINES = {
    "generic-challenger": "Never propose the fix",
    "generic-blind-spot-adversary": "Never propose the fix",
    "generic-verifier": "Never accept the proposer's",
    "generic-mechanic": "Never resolve an ambiguity by judgment",
    "generic-cartographer": "Never issue a verdict",
}


def source_core() -> str:
    """The core as CONTEXT-PACK.md holds it, extracted here independently of
    render_agents so the byte-identity check is not circular."""
    text = CONTEXT_PACK.read_text(encoding="utf-8")
    start = text.index(CORE_START) + len(CORE_START)
    return text[start:text.index(CORE_END)].strip("\n")


def bodies() -> dict:
    out = {}
    for path in sorted(AGENTS.glob("generic-*.md")):
        out[path.stem] = render_agents.split_frontmatter(path.read_text(encoding="utf-8"))[1]
    return out


def sentences(text: str) -> set:
    found = set()
    for chunk in re.split(r"(?<=[.!?;:])\s+|\n+", text):
        words = re.sub(r"[`*_]", "", chunk).lower().split()
        if len(words) >= MIN_WORDS:
            found.add(" ".join(words))
    return found


def repeated(texts: dict) -> dict:
    seen = {}
    for role, text in texts.items():
        for sentence in sentences(text):
            seen.setdefault(sentence, set()).add(role)
    return {s: sorted(r) for s, r in seen.items() if len(r) > MAX_BODIES}


@unittest.skipUnless(AGENTS.is_dir(), "kit only: the instance does not carry 01-roles/")
class AgentBodiesTests(unittest.TestCase):
    def setUp(self):
        self.bodies = bodies()
        self.assertEqual(sorted(self.bodies), sorted(round_files.ROLES))

    def test_no_long_sentence_repeats_in_three_bodies(self):
        self.assertEqual(repeated(self.bodies), {})

    def test_negative_control_catches_a_copied_paragraph(self):
        line = "Budget: max_tool_calls comes from your contract and the harness denies the next call once you reach it."
        planted = {role: body + "\n" + line + "\n" for role, body in list(self.bodies.items())[:3]}
        self.assertTrue(repeated(planted))

    def test_no_boilerplate_blocks_left(self):
        for role, body in self.bodies.items():
            with self.subTest(role=role):
                for gone in ("harness denies the next call", "moved out of this body", "never spawn other agents",
                             "settings.gradle", "libs.versions.toml"):
                    self.assertNotIn(gone, body)

    def test_generic_roles_carry_no_gradle_android_or_v3_text(self):
        for path in sorted(AGENTS.glob("generic-*.md")):
            with self.subTest(role=path.stem):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"gradle|android|\bv3\b", text, re.IGNORECASE))

    def test_no_spanish_tags_in_model_facing_text(self):
        for path in sorted(AGENTS.glob("generic-*.md")):
            with self.subTest(file=path.name):
                self.assertIsNone(SPANISH.search(path.read_text(encoding="utf-8")))
        for rel in MODEL_FACING:
            with self.subTest(file=rel):
                self.assertIsNone(SPANISH.search((KIT_ROOT / rel).read_text(encoding="utf-8")))
        for spec in catalog.TOOLS:
            with self.subTest(tool=spec.name):
                self.assertIsNone(SPANISH.search(spec.description))

    def test_do_not_cut_lines_stay_per_role(self):
        for role, body in self.bodies.items():
            contract = json.loads((AGENTS / f"{role}.contract.json").read_text(encoding="utf-8"))
            with self.subTest(role=role):
                self.assertIn("**IRON LAW**:", body)
                self.assertIn("Evidence rule:", body)
                self.assertIn("mcp__metodo__output_write", body)
                self.assertIn(f"schema `{round_files.ROLE_SCHEMA[role]}`", body)
                if "mcp__metodo__handoff_write" in contract["tools"]:
                    self.assertIn("mcp__metodo__handoff_write", body)
                if role in ROLE_LINES:
                    self.assertIn(ROLE_LINES[role], body)


@unittest.skipUnless(AGENTS.is_dir(), "kit only: the instance does not carry 01-roles/")
class RenderedAgentsTests(unittest.TestCase):
    def setUp(self):
        self.core = source_core()
        self.rendered = {}
        for path in sorted(AGENTS.glob("generic-*.md")):
            self.rendered[path.stem] = {target: render_agents.render(path, target, "/opt/tools") for target in ("claude", "pi")}

    def test_core_is_small_and_has_the_cold_start_rules(self):
        self.assertLessEqual(-(-len(self.core) // 4), 320)
        for needed in ("Measured", "Tested", "Inferred", "Assumed", "Unknown", "mcp__metodo__output_write",
                       "truncated", "not_covered", "owner", "spawn", "statement"):
            self.assertIn(needed, self.core)

    def test_every_rendered_agent_carries_the_core_once_byte_identical(self):
        for role, targets in self.rendered.items():
            for target, text in targets.items():
                with self.subTest(role=role, target=target):
                    self.assertEqual(text.count(self.core), 1)

    def test_pi_role_marker_stays_the_last_line(self):
        for role, targets in self.rendered.items():
            with self.subTest(role=role):
                self.assertEqual(targets["pi"].rstrip("\n").splitlines()[-1], f"<!-- metodo-role: {role} -->")

    def test_no_rendered_agent_points_outside_the_target_repo(self):
        for role, targets in self.rendered.items():
            for target, text in targets.items():
                with self.subTest(role=role, target=target):
                    self.assertNotIn("../", text)
                    self.assertNotIn("schema.json", text)
                    self.assertNotIn("00-principles", text)
                    self.assertNotIn("07-communication", text)

    def test_pi_contract_section_does_not_repeat_the_body_or_the_core(self):
        for role, targets in self.rendered.items():
            pi = targets["pi"]
            section = pi[pi.index("## Contract"):]
            with self.subTest(role=role):
                self.assertNotIn("truncated", section)
                self.assertNotIn("Delivery", section)
                self.assertNotIn("shared build files", section)
                self.assertNotIn("FAIL", section)
                self.assertEqual(pi.count("budget deny"), 1)
                self.assertEqual(pi.count("FAIL writes"), 1)


if __name__ == "__main__":
    unittest.main()
