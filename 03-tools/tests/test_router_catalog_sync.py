"""Frontmatter <-> catalog drift (model-router R9, decision L4): the router
decides model and effort at launch and agent frontmatter is only the
fallback, so the fallback must never disagree with the router's default.
Every generic-* role's `model:` (frontmatter and contract) equals the
admitted Anthropic model the catalog lists for the role's default tier
(router.ROLE_TIER), the role is listed in that tier's `roles`, and no role
names Fable 5.1 (L6: approval-only, never a default)."""
import copy
import json
import re
import unittest
from pathlib import Path

from lib import baseline, round_files, router

TOOLS = Path(__file__).resolve().parent.parent
KIT_ROOT = TOOLS.parent
AGENTS = KIT_ROOT / "01-roles" / "agents"
CATALOG = baseline.load_json(TOOLS / "config" / "model-tiers.json")
FABLE = router.ROUTER_DEFAULTS["fable"]["model"]


def _frontmatter_model(text: str) -> str | None:
    end = text.index("\n---\n", 4)
    for line in text[4:end].splitlines():
        match = re.match(r"^model:\s*(\S+)\s*$", line)
        if match:
            return match.group(1)
    return None


def drift(catalog: dict, pairs: dict) -> list[str]:
    """Every disagreement between a role's pinned model and the router's default."""
    problems = []
    for role, (fm_model, contract_model) in sorted(pairs.items()):
        expected = router.fallback_model(catalog, role)
        if expected is None:
            problems.append(f"{role}: no admitted anthropic model in tier {router.ROLE_TIER.get(role)}")
            continue
        for where, model in (("frontmatter", fm_model), ("contract", contract_model)):
            if model != expected:
                problems.append(f"{role}: {where} model {model} != catalog default {expected}")
    return problems


@unittest.skipUnless(AGENTS.is_dir(), "kit only: the instance does not carry 01-roles/")
class RouterCatalogSyncTests(unittest.TestCase):
    def setUp(self):
        self.pairs, self.texts = {}, {}
        for md in sorted(AGENTS.glob("generic-*.md")):
            text = md.read_text(encoding="utf-8")
            contract_text = (AGENTS / f"{md.stem}.contract.json").read_text(encoding="utf-8")
            self.pairs[md.stem] = (_frontmatter_model(text), json.loads(contract_text)["model"])
            self.texts[md.stem] = text + contract_text
        self.assertEqual(sorted(self.pairs), sorted(round_files.ROLES))

    def test_every_role_has_a_default_tier_listed_in_the_catalog(self):
        for role in self.pairs:
            with self.subTest(role=role):
                tier = router.ROLE_TIER.get(role)
                self.assertIn(tier, CATALOG["tiers"], role)
                self.assertIn(role, CATALOG["tiers"][tier]["roles"], role)

    def test_pinned_model_equals_the_router_default(self):
        self.assertEqual(drift(CATALOG, self.pairs), [])

    def test_fallback_is_the_admitted_anthropic_model_of_the_tier(self):
        for role, tier in router.ROLE_TIER.items():
            with self.subTest(role=role):
                model = router.fallback_model(CATALOG, role)
                entry = router._resolve(CATALOG, tier, model)
                self.assertEqual((entry["provider"], entry["status"]), ("anthropic", "admitted"))
                self.assertFalse(entry.get("local"))
        self.assertIsNone(router.fallback_model(CATALOG, "not-a-role"))

    def test_no_role_names_fable(self):
        for role, text in self.texts.items():
            self.assertNotIn(FABLE, text, role)

    def test_negative_control_detects_a_drifted_pin_and_a_drifted_catalog(self):
        broken = dict(self.pairs, **{"generic-judge": ("claude-opus-5-5", self.pairs["generic-judge"][1])})
        self.assertEqual(drift(CATALOG, broken), ["generic-judge: frontmatter model claude-opus-5-5 != catalog default claude-sonnet-5-5"])
        catalog = copy.deepcopy(CATALOG)
        for entry in catalog["tiers"]["small"]["candidates"]:
            if entry["id"] == "claude-haiku-5-5":
                entry["status"] = "candidate"
        self.assertTrue([p for p in drift(catalog, self.pairs) if "generic-mechanic" in p])


if __name__ == "__main__":
    unittest.main()
