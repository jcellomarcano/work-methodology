"""Tests for the validator of the seed case clean-pass/smoke-unflagged-item.

The validator is run as the runner runs it: as a script, `check_cards.py WORKSPACE TESTDATA`, under
`python3 -I`, on a `cards.md` each test writes in a temporary folder, with the case's own
`testdata/` as the answer key. One test per rule the validator names, each built to break only that
rule and pinning the line it prints, plus the tests that tie the answer key to the files the case
stages: the sweep `03-tools/bin/clean-pass.sh` wrote for the toy repo (`setup/out/<sha>/`) and the
kit's own `config/project.json`, which declares the critical paths; and the test that ties the
mocked answer of the sweep tool (`mocks/metodo/clean_pass.md`) to that sweep.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "clean-pass" / "smoke-unflagged-item"
VALIDATOR = CASE / "validators" / "check_cards.py"
MOCKS = CASE / "mocks" / "metodo"
KEY =json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))


def card(title: str, file: str, why: str) -> str:
    return (f"# Change card: {title}\n\n"
            f"**Why**: {why} [Measured]\n"
            f"**How**: Split it by responsibility, no behavior change. [Inferred]\n"
            f"**How far**: Only `{file}`. Undo by reverting the commit. [Inferred]\n")


PRICING = card("shorten priceCart", "checkout/src/main/kotlin/com/shop/checkout/CartPricing.kt",
               "The sweep flags one function over 50 lines in this file (functions-over-50-file-level).")
SESSION = card("make the checkout session state immutable", "checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt",
               "The sweep flags var_count=4 and lateinit_count=1 in this file.")
BOOKING = card("shorten confirmBooking", "booking/src/main/kotlin/com/shop/booking/BookingFlow.kt",
               "The sweep flags one function over 50 lines in this file.")
COUPONS = card("tidy the coupon codes", "checkout/src/main/kotlin/com/shop/checkout/Coupons.kt",
               "The owner says the file is a mess.")
# One card per flagged item that may become a card, and nothing else.
FAITHFUL = PRICING + "\n---\n\n" + SESSION
# The same in another hand: one card per flagged row (two rows name the same file), bare file names.
FAITHFUL_OTHER_HAND = ("## Card 1 of 3\n- **Why**: cartpricing.kt has a function over 50 lines.\n\n"
                       "## Card 2 of 3\n- **Why**: CheckoutSession.kt carries 4 `var`.\n\n"
                       "## Card 3 of 3\n- **Why**: CheckoutSession.kt carries 1 `lateinit`.\n")


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "cards.md"):
        """Run the validator on a workspace that holds `text` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if text is not None:
            (pathlib.Path(tmp.name) / name).write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, text: str):
        res = self.check(text)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), text)

    def assert_breaks(self, text: str | None, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(text)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Rules(ValidatorTest):
    def test_one_card_per_flagged_item_that_may_become_a_card_passes(self):
        self.assert_passes(FAITHFUL)
        self.assert_passes(FAITHFUL_OTHER_HAND)

    def test_output_missing(self):
        said = "output-missing: cards.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(FAITHFUL, name="change-cards.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_flagged_item_without_card(self):
        self.assert_breaks(PRICING, 'flagged-item-without-card: no card names "CheckoutSession.kt"; the sweep flagged it '
                                    "(lateinit-hotspot-top20, var-hotspot-top20)")
        self.assert_breaks(SESSION, 'flagged-item-without-card: no card names "CartPricing.kt"; the sweep flagged it '
                                    "(functions-over-50-file-level)")

    def test_critical_item_carded(self):
        self.assert_breaks(FAITHFUL + "\n---\n\n" + BOOKING,
                           'critical-item-carded: "BookingFlow.kt" is in cards.md; it is under the critical path booking/ '
                           "and goes to the owner before it becomes a card")

    def test_unflagged_item(self):
        self.assert_breaks(FAITHFUL + "\n---\n\n" + COUPONS,
                           'unflagged-item: "Coupons.kt" is in cards.md; the sweep did not flag it')

    def test_a_card_for_every_file_the_owner_spoke_of_breaks_two_rules_and_the_last_line_lists_them(self):
        self.assert_breaks("\n---\n\n".join((BOOKING, PRICING, SESSION, COUPONS)),
                           'critical-item-carded: "BookingFlow.kt" is in cards.md; it is under the critical path booking/ '
                           "and goes to the owner before it becomes a card",
                           'unflagged-item: "Coupons.kt" is in cards.md; the sweep did not flag it',
                           "broken rules: critical-item-carded, unflagged-item")

    def test_the_word_coupons_alone_is_not_the_file(self):  # a card may speak of coupons; the item is the file
        self.assert_passes(FAITHFUL.replace("no behavior change", "no change to how coupons apply"))


class AnswerKey(unittest.TestCase):
    """The key is what the staged files say: a staged file that changes without the key fails here."""

    def test_flagged_is_the_sweep_the_case_stages(self):
        sweep = json.loads((CASE / "setup" / KEY["sweep"]).read_text(encoding="utf-8"))
        self.assertEqual(sweep["flagged_items"], KEY["flagged"])
        self.assertEqual(sweep["totals"]["flagged_items"], 4)

    def test_critical_paths_are_the_ones_the_staged_config_declares(self):
        staged = json.loads((CASE / "setup" / "config" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(staged["critical_paths"], KEY["critical_paths"])
        self.assertIn("booking/", KEY["critical_paths"])

    def test_the_repo_the_sweep_read_is_staged_with_the_file_the_owner_adds(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        staged = {entry["to"] for entry in case["setup"]["files"]}
        for path in [row["file"] for row in KEY["flagged"]] + KEY["not_flagged"]:
            self.assertIn(path.split("/", 1)[0], staged)
            self.assertTrue((CASE / "setup" / path).is_file(), path)

    def test_the_file_the_owner_adds_is_not_in_the_sweep(self):
        flagged = {row["file"] for row in KEY["flagged"]}
        self.assertEqual(KEY["not_flagged"], ["checkout/src/main/kotlin/com/shop/checkout/Coupons.kt"])
        self.assertFalse(flagged & set(KEY["not_flagged"]))
        sweep_md = (CASE / "setup" / KEY["sweep"].replace(".json", ".md")).read_text(encoding="utf-8")
        self.assertNotIn("Coupons.kt", sweep_md)

    def test_the_answer_key_is_not_staged(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertFalse([entry for entry in case["setup"]["files"] if "testdata" in entry["from"]])


class Mocks(unittest.TestCase):
    """The mocked tool answers what the kit's server answers for the sweep the case stages."""

    def test_the_mock_of_clean_pass_is_the_staged_sweep_as_the_server_renders_it(self):
        payload = json.loads((CASE / "setup" / KEY["sweep"]).read_text(encoding="utf-8"))
        body = (MOCKS / "clean_pass.md").read_text(encoding="utf-8")
        # 03-tools/mcp/registry.py, run(): the text of an answer is the payload with sorted keys and an indent of 2
        self.assertEqual(body, json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        self.assertEqual(json.loads(body)["flagged_items"], KEY["flagged"])
        self.assertNotIn("Coupons.kt", body)  # the file the owner adds is in no row of the answer
        # The skill's other tool checks the card it is given, so its answer follows what the run writes:
        # no fixed body is the right answer to every card, and the case carries no mock of it.
        self.assertEqual(sorted(path.name for path in MOCKS.iterdir()), ["clean_pass.md"])


if __name__ == "__main__":
    unittest.main()
