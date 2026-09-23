import json
import unittest
from pathlib import Path

from lib import change_card_validator as ccv

CLEAN_CARD = """## Change Card

**Why**: the refund used to hang at the payment provider [Medido]
**For what**: Data integrity [Medido]
**What it risks**: double refund if blindly retried [Probado]
**When**: on every refund with a network timeout [Medido]
**How**: adds an idempotency guard before retrying [Probado]
**How far**: only covers the refund path, not the purchase path [Asumido]
**How we'll know**: the guard test fails if the fix is removed [Probado]
**Invariant**: INV-07
**Ticket**: DEV-123
"""


def _replace_line(text: str, label: str, new_line: str) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        if line.startswith(f"**{label}**"):
            out.append(new_line)
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _remove_line(text: str, label: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith(f"**{label}**")
    ) + "\n"


class CleanCardTests(unittest.TestCase):
    def test_passes(self):
        result = ccv.validate(CLEAN_CARD)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["fields_missing"], [])
        self.assertEqual(len(result["fields_found"]), 9)
        self.assertEqual(result["epistemic_coverage"], {"tag_required_fields": 7, "tagged_ok": 7})
        # For what=Data integrity: the adversary lane is opus.
        self.assertEqual(result["routing"], "opus")

    def test_determinism(self):
        first = ccv.validate(CLEAN_CARD)
        second = ccv.validate(CLEAN_CARD)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class MissingFieldTests(unittest.TestCase):
    def test_missing_ticket_fails(self):
        card = _remove_line(CLEAN_CARD, "Ticket")
        result = ccv.validate(card)
        # negative control: without Ticket the verdict must be FAIL, never PASS
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("Ticket", result["fields_missing"])


class EpistemicTagTests(unittest.TestCase):
    def test_missing_tag_fails(self):
        card = _replace_line(CLEAN_CARD, "Why", "**Why**: the refund used to hang")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Why" in e for e in result["errors"]))

    def test_invalid_tag_value_fails(self):
        card = _replace_line(CLEAN_CARD, "When", "**When**: on every refund [Certain]")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("When" in e for e in result["errors"]))


class ForWhatTests(unittest.TestCase):
    def test_unrecognized_value_fails(self):
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Throughput [Medido]")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("For what" in e for e in result["errors"]))

    def test_ux_does_not_require_invariant(self):
        # For what=UX alone is not enough: What it risks also has to declare
        # explicitly that there is nothing to protect ("none"), otherwise
        # n/a stays rejected (see InvariantTests.test_na_needs_both_fields_safe).
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: UX [Medido]")
        card = _replace_line(card, "What it risks", "**What it risks**: none [Probado]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["routing"], "sonnet")


class InvariantTests(unittest.TestCase):
    def test_na_fails_when_for_what_is_data_integrity(self):
        card = _replace_line(CLEAN_CARD, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        # negative control: For what=Data integrity requires a real invariant, not n/a
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))

    def test_na_needs_both_fields_safe(self):
        # negative control (adversarial round): For what=UX but What it risks
        # is real risk text (not "none") -> n/a still is not accepted,
        # even though For what alone does not trigger the critical set.
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: UX [Medido]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))

    def test_what_it_risks_data_integrity_forces_invariant_even_if_for_what_is_ux(self):
        # explicit negative control from the adversarial round: For what=UX +
        # What it risks=Data integrity + Invariant=n/a -> FAIL, and routing is
        # decided by What it risks even though For what says UX.
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: UX [Medido]")
        card = _replace_line(card, "What it risks", "**What it risks**: Data integrity [Probado]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))
        self.assertEqual(result["routing"], "opus")

    def test_malformed_invariant_id_fails(self):
        card = _replace_line(CLEAN_CARD, "Invariant", "**Invariant**: INV-7")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))

    def test_multiple_valid_invariants_pass(self):
        card = _replace_line(CLEAN_CARD, "Invariant", "**Invariant**: INV-07, INV-09")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")

    def test_arch_006_token_is_accepted(self):
        # ARCH-006 is the default extra_invariant_tokens (config/project.json).
        card = _replace_line(CLEAN_CARD, "Invariant", "**Invariant**: ARCH-006")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")

    def test_custom_prefix_is_honored(self):
        # negative control: with the default prefix (INV), a
        # LEGACY-INV-07 token does not match; with invariant_prefix="LEGACY-INV" it does.
        card = _replace_line(CLEAN_CARD, "Invariant", "**Invariant**: LEGACY-INV-07")
        default_result = ccv.validate(card)
        self.assertEqual(default_result["verdict"], "FAIL")
        custom_result = ccv.validate(card, invariant_prefix="LEGACY-INV")
        self.assertEqual(custom_result["verdict"], "PASS")

    def test_state_correctness_now_requires_invariant(self):
        # negative control: before the adversarial round, State correctness did
        # not require an invariant; now it does (it is in CRITICAL_ROUTING_SET).
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: State correctness [Medido]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))


class RoutingTests(unittest.TestCase):
    def test_security_routes_to_opus(self):
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Security [Medido]")
        result = ccv.validate(card)
        self.assertEqual(result["routing"], "opus")

    def test_auditability_and_none_routes_to_sonnet(self):
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Auditability [Medido]")
        card = _replace_line(card, "What it risks", "**What it risks**: none [Probado]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["routing"], "sonnet")
        self.assertEqual(result["verdict"], "PASS")

    def test_routing_is_computed_even_on_broken_card(self):
        # best-effort: with no epistemic tag, routing is still computed over the raw text.
        broken = "**For what**: Data integrity\n"
        result = ccv.validate(broken)
        self.assertEqual(result["routing"], "opus")


class TicketTests(unittest.TestCase):
    def test_lowercase_ticket_fails(self):
        card = _replace_line(CLEAN_CARD, "Ticket", "**Ticket**: dev-123")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Ticket" in e for e in result["errors"]))

    def test_no_ticket_literal_passes(self):
        card = _replace_line(CLEAN_CARD, "Ticket", "**Ticket**: no ticket")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")


class DuplicateFieldTests(unittest.TestCase):
    def test_duplicate_field_is_an_error(self):
        card = CLEAN_CARD + "\n**Ticket**: DEV-999\n"
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("duplicate" in e for e in result["errors"]))


class ExtractModeTests(unittest.TestCase):
    def test_extract_never_raises_on_broken_card(self):
        broken = "this is not a change card at all"
        result = ccv.validate(broken)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(len(result["fields_missing"]), 9)

    def test_main_extract_mode_exits_zero_on_broken_card(self):
        import io
        import contextlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("not a change card\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ccv.main(["--extract", str(path)])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["verdict"], "FAIL")
            self.assertTrue(payload["extract_mode"])

    def test_main_non_extract_mode_exits_one_on_fail(self):
        import io
        import contextlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("not a change card\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ccv.main([str(path)])
            self.assertEqual(code, 1)

    def test_main_exits_zero_on_pass(self):
        import io
        import contextlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.md"
            path.write_text(CLEAN_CARD, encoding="utf-8")
            config = Path(tmp) / "project.json"
            config.write_text('{"invariant_prefix": "INV", "extra_invariant_tokens": ["ARCH-006"]}', encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ccv.main(["--config", str(config), str(path)])
            self.assertEqual(code, 0)


class LeadingPropertySeparatorTests(unittest.TestCase):
    def test_for_what_with_note_after_comma_passes(self):
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: UX, more ceremony per change [Asumido]")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")
        self.assertNotIn("For what", " ".join(result["errors"]))

    def test_for_what_leading_token_not_a_property_fails(self):
        # negative control: 'Throughput' is not a property even with a
        # separator and a note after it, same as without a separator.
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Throughput, not a real category [Medido]")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("For what" in e for e in result["errors"]))

    def test_what_it_risks_none_with_separator_satisfies_na_invariant(self):
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Auditability [Medido]")
        card = _replace_line(card, "What it risks", "**What it risks**: none; it's a document [Probado]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["routing"], "sonnet")

    def test_word_between_token_and_separator_does_not_count(self):
        # negative control: "UX from the team, ..." is NOT "UX" + separator (there
        # is a word in between) -> What it risks is still not 'none'.
        card = _replace_line(CLEAN_CARD, "For what", "**For what**: Auditability [Medido]")
        card = _replace_line(card, "What it risks", "**What it risks**: UX from the team, more ceremony [Asumido]")
        card = _replace_line(card, "Invariant", "**Invariant**: n/a")
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("Invariant" in e for e in result["errors"]))


class WrappedContinuationTests(unittest.TestCase):
    def test_wrapped_field_joins_and_validates_tag_at_end(self):
        card = _replace_line(
            CLEAN_CARD, "What it risks",
            "**What it risks**: double refund if blindly retried\n  with no guard in place [Probado]",
        )
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")

    def test_wrapped_field_missing_tag_still_fails(self):
        # negative control: joining lines must not invent a tag that is not there.
        card = _replace_line(
            CLEAN_CARD, "What it risks",
            "**What it risks**: double refund if blindly retried\n  with no guard in place",
        )
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("What it risks" in e for e in result["errors"]))

    def test_continuation_without_leading_spaces_also_joins(self):
        # "is a non-empty line without **Field**:" also counts, not only
        # 2+ space indentation.
        card = _replace_line(
            CLEAN_CARD, "How far",
            "**How far**: only covers the refund path,\nnot the purchase path [Asumido]",
        )
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "PASS")


class BulletFormTests(unittest.TestCase):
    def test_all_fields_as_bullets_passes(self):
        bullet_card = "\n".join(
            f"- {line}" if line.startswith("**") else line for line in CLEAN_CARD.splitlines()
        )
        result = ccv.validate(bullet_card)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["fields_found"]), 9)


class MultiFieldPerLineTests(unittest.TestCase):
    def test_invariant_and_ticket_share_a_line(self):
        lines = [line for line in CLEAN_CARD.splitlines() if not line.startswith("**Invariant**") and not line.startswith("**Ticket**")]
        lines.append("**Invariant**: INV-07. **Ticket**: no ticket.")
        result = ccv.validate("\n".join(lines))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["fields_found"].count("Invariant"), 1)

    def test_duplicate_detected_even_when_split_from_shared_line(self):
        card = CLEAN_CARD + "\n**Invariant**: INV-09. **Ticket**: DEV-999.\n"
        result = ccv.validate(card)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("duplicate" in e for e in result["errors"]))


class CardSectionExtractionTests(unittest.TestCase):
    def test_card_embedded_in_a_larger_document(self):
        doc = f"""# Some study

Introductory text that is not part of the card at all.

## Change Card
{CLEAN_CARD.split("## Change Card", 1)[1].strip()}

## Next section

This paragraph must NOT leak into 'Ticket' via the continuation join.
"""
        result = ccv.validate(doc)
        self.assertEqual(result["verdict"], "PASS")
        # negative control: the next section's text did not stick to Ticket.
        self.assertEqual(result["errors"], [])

    def test_bulleted_card_under_numbered_heading(self):
        bulleted = "\n".join(
            f"- {line}" if line.startswith("**") else line
            for line in CLEAN_CARD.split("## Change Card", 1)[1].strip().splitlines()
        )
        doc = f"""# Doc

## 0. Change Card for this study

{bulleted}

## 1. Next section

prose that must not affect parsing.
"""
        result = ccv.validate(doc)
        self.assertEqual(result["verdict"], "PASS")


class RealCardFilesTests(unittest.TestCase):
    """Real change cards from an audit in progress, if the project owner already
    has them written under config/project.json:docs_root. Skipped if the
    file does not exist (the normal case on a fresh kit checkout); if
    they exist, their real verdict is validated: this does NOT require them to
    pass: a What it risks in free prose that does not explicitly declare 'none'
    still requires a real Invariant, on purpose."""

    def _validate_file(self, path_str: str):
        path = Path(path_str).expanduser()
        if not path.exists():
            self.skipTest(f"{path} does not exist yet")
        return ccv.validate(path.read_text(encoding="utf-8"))

    def test_work_methodology(self):
        result = self._validate_file("~/architecture-audit-example/work-methodology.md")
        self.assertIn(result["verdict"], {"PASS", "FAIL"})
        self.assertEqual(len(result["fields_found"]), 9)


if __name__ == "__main__":
    unittest.main()


class ProjectPropertiesTest(unittest.TestCase):
    def tearDown(self):
        ccv.configure_properties({})

    def test_project_hierarchy_replaces_builtin_defaults(self):
        ccv.configure_properties({
            "property_order": ["Evidence", "Recoverability", "UX"],
            "critical_properties": ["Evidence", "Recoverability"],
        })
        self.assertIn("Evidence", ccv.FOR_WHAT_VALUES)
        self.assertNotIn("Data integrity", ccv.FOR_WHAT_VALUES)
        self.assertEqual(ccv.CRITICAL_ROUTING_SET, frozenset({"Evidence", "Recoverability"}))
        self.assertIn("none", ccv.RECOGNIZED_LEADING_TOKENS)

    def test_empty_config_keeps_defaults(self):
        ccv.configure_properties({})
        self.assertIn("Data integrity", ccv.FOR_WHAT_VALUES)
        self.assertNotIn("Evidence", ccv.FOR_WHAT_VALUES)
