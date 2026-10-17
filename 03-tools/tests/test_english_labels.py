"""English is the canonical label set for every machine check that reads card
labels, epistemic tags or round verdicts; the Spanish forms stay accepted as
aliases so existing cards, receipts and round outputs keep validating.
One test per rule, plus a regression snapshot of the Spanish behaviour."""
import json
import tempfile
import unittest
from pathlib import Path

from lib import change_card_validator as ccv
from lib import cite_check, findings_schema_validator as fsv, output_lint, rdd_risk
from lib import rdd_receipt as rr
from tests.test_rdd_receipt import (BLIND_CLOSED, BLIND_OPEN, CARD_HIGH, CARD_LOW, CARD_MEDIUM, FINDINGS_OK, FINDINGS_ROTO,
                                    VERIFICATION_PASS, ReceiptFixture, _rulings)

TOOLS = Path(__file__).resolve().parent.parent
SCHEMAS = TOOLS / "schemas"
LINT_CONFIG = json.loads((TOOLS / "config" / "output-lint.json").read_text(encoding="utf-8"))

# Spanish alias -> English canonical, for every enum value a round schema declares.
ENUM_ALIASES = {
    "Medido": "Measured", "Probado": "Tested", "Inferido": "Inferred", "Asumido": "Assumed", "Desconocido": "Unknown",
    "MATIZ": "NUANCE", "ROTO": "BROKEN",
    "CERRADO": "CLOSED", "ABIERTO CON DUEÑO": "OPEN WITH OWNER", "CONTENIDO": "CONTAINED",
}

SPANISH_CAPACITY = """## Ficha de cambio

**Por qué**: la cancelación se quedaba colgada en el proveedor de reservas [Medido]
**Para qué**: Capacidad [Medido]
**Qué arriesga**: doble cancelación si se reintenta a ciegas [Probado]
**Cuándo**: en cada cancelación con timeout de red [Medido]
**Cómo**: se añade un guard de idempotencia antes de reintentar [Probado]
**Hasta dónde**: solo cubre el camino de cancelación, no el de reserva nueva [Asumido]
**Cómo lo sabremos**: el test de guard falla si se quita el fix [Probado]
**Invariante**: INV-07
**Ticket**: DEV-123
"""

ENGLISH_CAPACITY = """## Change card

**Why**: the cancellation hung at the booking provider [Measured]
**For what**: Capacity [Measured]
**What it risks**: double cancellation on a blind retry [Tested]
**When**: on every cancellation with a network timeout [Measured]
**How**: an idempotency guard before retrying [Tested]
**How far**: only the cancellation path, not the new-booking one [Assumed]
**How we'll know**: the guard test fails if the fix is removed [Tested]
**Invariant**: INV-07
**Ticket**: DEV-123
"""

ENGLISH_LOW = """## Change card
**Why**: the test asks for it [Measured]
**For what**: UX [Measured]
**What it risks**: none [Measured]
**When**: now [Measured]
**How**: one change [Measured]
**How far**: domain/** [Measured]
**How we'll know**: green test [Measured]
**Invariant**: n/a
**Ticket**: no ticket
"""

ENGLISH_MEDIUM = ENGLISH_LOW.replace("**What it risks**: none [Measured]", "**What it risks**: UX, one screen [Measured]")

# The template in 00-principles/change-card.md, verbatim.
DOC_TEMPLATE = """## Change card
**Why**: Store.kt:73-78 @ a1b2c3d declares the obligation lives only in memory [Measured]
**For what**: Recoverability [Measured]
**What it risks**: UX, one extra write before the external call [Assumed]
**When**: before the feature's first real deployment [Inferred]
**How**: write-ahead log of the terms before the external call and reconcile() on startup [Inferred]
**How far**: doesn't touch legacy providers; undone by reverting the commit and deleting the log [Measured]
**How we'll know**: process-death test across the three windows; real-environment minutes [Tested]
**Invariant**: INV-04
**Ticket**: no ticket
"""

# The critical-flow example hierarchy (config/examples/critical-flow/project.json):
# the capacity cards above need it, the kit default hierarchy is domain-neutral.
CAPACITY_CONFIG = {"property_order": ["Capacity", "Booking status", "Request identity", "Integrity", "Auditability",
                                      "Recoverability", "Security", "UX"]}
FINDINGS_BROKEN = dict(FINDINGS_ROTO, findings=[dict(FINDINGS_ROTO["findings"][0], verdict="BROKEN", epistemic="Tested")])
BLIND_OPEN_EN = dict(BLIND_OPEN, blind_spots=[dict(BLIND_OPEN["blind_spots"][0], state="OPEN WITH OWNER", epistemic="Inferred")])
BLIND_CLOSED_EN = dict(BLIND_CLOSED, blind_spots=[dict(BLIND_CLOSED["blind_spots"][0], state="CLOSED", epistemic="Inferred")])


class ChangeCardEnglishTests(unittest.TestCase):
    def setUp(self):
        ccv.configure_properties(CAPACITY_CONFIG)

    def tearDown(self):
        ccv.configure_properties({})

    def test_english_card_validates_with_the_same_lane_as_spanish(self):
        english, spanish = ccv.validate(ENGLISH_CAPACITY), ccv.validate(SPANISH_CAPACITY)
        self.assertEqual(english["verdict"], "PASS", english)
        self.assertEqual(english["routing"], spanish["routing"])
        self.assertEqual(english["routing"], "opus")

    def test_english_low_card_takes_the_low_lane(self):
        english, spanish = ccv.validate(ENGLISH_LOW), ccv.validate(CARD_LOW)
        self.assertEqual(english["verdict"], "PASS", english)
        self.assertEqual(english["routing"], spanish["routing"])
        self.assertEqual(english["routing"], "sonnet")

    def test_english_tags_count_for_epistemic_coverage(self):
        result = ccv.validate(ENGLISH_CAPACITY)
        self.assertEqual(result["epistemic_coverage"], {"tag_required_fields": 7, "tagged_ok": 7})
        self.assertEqual(result["errors"], [])

    def test_doc_template_validates(self):
        result = ccv.validate(DOC_TEMPLATE)
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertEqual(result["routing"], "opus")

    def test_english_card_under_an_english_heading_inside_a_larger_doc(self):
        doc = "# Plan\n\nSome prose.\n\n" + DOC_TEMPLATE + "\n## Next section\n\nunrelated prose that must not join a field\n"
        fields, _ = ccv.parse_fields(doc)
        self.assertEqual(fields["Ticket"], "no ticket")

    def test_english_labels_map_to_the_same_field_keys(self):
        # rdd_risk and benchmark_release read parse_fields by the stable keys.
        english, _ = ccv.parse_fields(ENGLISH_LOW)
        spanish, _ = ccv.parse_fields(CARD_LOW)
        self.assertEqual(sorted(english), sorted(spanish))

    def test_english_and_spanish_label_for_the_same_field_is_a_duplicate(self):
        result = ccv.validate(ENGLISH_LOW + "**Por qué**: otra vez [Medido]\n")
        self.assertIn("duplicate field: Why", result["errors"])
        self.assertEqual(result["verdict"], "FAIL")

    def test_none_in_what_it_risks_is_the_no_risk_token_for_rdd_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.md"
            path.write_text(ENGLISH_LOW, encoding="utf-8")
            facts = rdd_risk.card_facts(path, {})
        self.assertEqual(facts["what_it_risks"], "none")
        self.assertEqual(facts["card_verdict"], "PASS")

    def test_project_with_english_property_names_accepts_spanish_values(self):
        ccv.configure_properties({"property_order": ["Capacity", "Recoverability", "UX"],
                                  "critical_properties": ["Capacity", "Recoverability"]})
        result = ccv.validate(SPANISH_CAPACITY)
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertEqual(result["routing"], "opus")

    def test_unknown_english_word_is_still_rejected(self):
        # negative control: aliases are a closed set, not "anything in English"
        bad = ENGLISH_CAPACITY.replace("**For what**: Capacity [Measured]", "**For what**: Speed [Measured]")
        self.assertEqual(ccv.validate(bad)["verdict"], "FAIL")
        bad_tag = ENGLISH_CAPACITY.replace("[Assumed]", "[Guessed]")
        self.assertEqual(ccv.validate(bad_tag)["verdict"], "FAIL")
        self.assertEqual(ccv.validate(bad_tag)["epistemic_coverage"]["tagged_ok"], 6)


class SchemaEnglishTests(unittest.TestCase):
    def test_every_spanish_enum_value_has_its_english_canonical(self):
        def enums(node):
            if isinstance(node, dict):
                if "enum" in node:
                    yield node["enum"]
                for value in node.values():
                    yield from enums(value)
            elif isinstance(node, list):
                for value in node:
                    yield from enums(value)

        checked = 0
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            for enum in enums(json.loads(path.read_text(encoding="utf-8"))):
                for value in enum:
                    if value in ENUM_ALIASES:
                        checked += 1
                        self.assertIn(ENUM_ALIASES[value], enum, f"{path.name}: {value}")
        self.assertGreater(checked, 0)

    def test_english_round_outputs_validate(self):
        cases = {
            "findings": FINDINGS_BROKEN,
            "blindspots": BLIND_OPEN_EN,
            "verdict": dict(_rulings(**{"F-02": "REFUTED"}), rulings=[
                dict(_rulings(**{"F-02": "REFUTED"})["rulings"][0], epistemic="Unknown")]),
            "claims": {"claims": [{"id": "C-1", "statement": "s", "assumption": "a", "files": [], "evidence_needed": "e",
                                   "epistemic": "Inferred"}]},
        }
        for name, doc in cases.items():
            schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(fsv.validate(doc, schema)["verdict"], "PASS", name)


class OutputLintEnglishTests(unittest.TestCase):
    def test_com09_accepts_english_tags(self):
        text = "Answer.\n\n## Technical detail\n\n- p50 320 ms over 5 runs [Measured]\n- guard test [Tested]\n- no impact [Inferred]\n- [Assumed] same load\n- [Unknown] cold start\n"
        rule = next(r for r in output_lint.check(text, LINT_CONFIG)["rules"] if r["id"] == "COM-09")
        self.assertEqual(rule["status"], "PASS", rule)

    def test_cite_check_warns_on_english_measured_without_a_cite(self):
        text = "Answer.\n\n## Technical detail\n\n- pasted output: 26 tests OK [Measured]\n- a bullet [Tested]\n- a guess [Inferred]\n"
        result = cite_check.check(text, LINT_CONFIG, repo=None)
        self.assertEqual(len(result["uncited_measured"]), 2)


class FinalizeEnglishTests(ReceiptFixture):
    def _medium(self, card=CARD_MEDIUM):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(card))
        self._capture_scripts(tree)
        return tree

    def _high(self):
        tree = self._commit("booking/Book.kt", "class Book\n")
        self._start(self._card(CARD_HIGH))
        rr.acknowledge(tree, "consent", "ok")
        self._capture_scripts(tree)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        return tree

    def test_english_card_starts_a_receipt_in_the_same_tier(self):
        self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self.assertEqual(self._start(self._card(ENGLISH_LOW))["risk"]["tier"], "low")
        self._commit("domain/Foo.kt", "class Foo { val x = 2 }\n")
        self.assertEqual(self._start(self._card(ENGLISH_MEDIUM))["risk"]["tier"], "medium")

    def test_broken_rejects_like_roto(self):
        tree = self._medium()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_BROKEN), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "rejected")
        self.assertIn("F-02", receipt["verdict_reasons"][0])

    def test_broken_refuted_by_judge_is_approved(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_BROKEN), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_CLOSED_EN), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-02": "REFUTED"})), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")

    def test_open_with_owner_without_ruling_escalates_like_abierto(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_OPEN_EN), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-01": "CONFIRMED"})), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "escalated")
        self.assertIn("B-02", receipt["verdict_reasons"][0])

    def test_open_with_owner_with_a_ruling_is_approved(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_OPEN_EN), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-01": "CONFIRMED", "B-02": "CONFIRMED"})), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")


class SpanishRegressionTests(unittest.TestCase):
    """The Spanish forms validate exactly as before (snapshot taken before the change)."""

    def setUp(self):
        ccv.configure_properties(CAPACITY_CONFIG)

    def tearDown(self):
        ccv.configure_properties({})

    def test_spanish_cards_validate_exactly_as_before(self):
        # Fields are reported by their English key whichever language the card uses.
        found = ["For what", "How", "How far", "How we'll know", "Invariant", "Ticket", "What it risks", "When", "Why"]
        base = {"epistemic_coverage": {"tag_required_fields": 7, "tagged_ok": 7}, "errors": [], "fields_found": found,
                "fields_missing": [], "verdict": "PASS"}
        self.assertEqual(ccv.validate(SPANISH_CAPACITY), dict(base, routing="opus"))
        self.assertEqual(ccv.validate(CARD_LOW), dict(base, routing="sonnet"))
        self.assertEqual(ccv.validate("nothing here")["fields_missing"], sorted(found))

    def test_spanish_round_outputs_still_validate(self):
        for name, doc in (("findings", FINDINGS_ROTO), ("blindspots", BLIND_OPEN)):
            schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(fsv.validate(doc, schema)["verdict"], "PASS", name)

    def test_spanish_tags_still_pass_com09(self):
        text = "Respuesta.\n\n## Detalle técnico\n\n- dato [Medido]\n- test [Probado]\n- [Inferido] x\n"
        rule = next(r for r in output_lint.check(text, LINT_CONFIG)["rules"] if r["id"] == "COM-09")
        self.assertEqual(rule["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
