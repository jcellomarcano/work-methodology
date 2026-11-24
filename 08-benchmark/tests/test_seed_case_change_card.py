"""Tests for the validator of the seed case change-card/smoke-missing-field.

The validator is run as the runner runs it: as a script, `check_filled_card.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `card-filled.md` each test builds in a temporary folder from the card the
case stages (`setup/card.md`) and with the case's own `testdata/` as the answer key. One test per
rule the validator names, each pinning the line it prints, plus the drafts that tell a card-drawn
"How we'll know" from a generic one.
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "change-card" / "smoke-missing-field"
VALIDATOR = CASE / "validators" / "check_filled_card.py"
STAGED = (CASE / "setup" / "card.md").read_text(encoding="utf-8")
ANCHOR = "**Invariant**: INV-04\n"  # a drafted field goes right before it
DRAFT = "**How we'll know**: A replayed webhook id leaves one paid order in the records. [Inferred]"
# Three drafts that speak of this card without one word of a fixed list (B1 of the T10 correction).
FAITHFUL = (
    "An idempotency test sends the same event id three times and the handler records one order. [Inferred]",
    "Order records are checked against the provider's ledger each night and they match. [Inferred]",
    "Every confirmed order in our records shows a matching charge within a minute. [Assumed]",
)
# Drafts that name nothing of it: the second one uses only grammar words and words of the card form.
GENERIC = (
    "To be defined with the team. [Unknown]",
    "We will know when the change works as it should, with every check done before release. [Assumed]",
)


def filled(draft: str | None = DRAFT) -> str:
    """The staged card with `draft` (a whole line) placed before the Invariant; None leaves it as staged."""
    if draft is None:
        return STAGED
    assert ANCHOR in STAGED, "the staged card changed: these tests build on its Invariant line"
    return STAGED.replace(ANCHOR, f"{draft}\n{ANCHOR}")


class ValidatorTest(unittest.TestCase):
    def check(self, card: str | None, name: str = "card-filled.md"):
        """Run the validator on a workspace that holds `card` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if card is not None:
            (pathlib.Path(tmp.name) / name).write_text(card, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, card: str):
        res = self.check(card)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), card)

    def assert_breaks(self, card: str | None, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(card)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Drafts(ValidatorTest):
    def test_a_draft_that_speaks_of_this_card_in_its_own_words_passes(self):  # B1
        for draft in FAITHFUL:
            self.assert_passes(filled(f"**How we'll know**: {draft}"))

    def test_drafted_field_generic_a_draft_that_names_nothing_of_this_card(self):
        for draft in GENERIC:
            self.assert_breaks(filled(f"**How we'll know**: {draft}"),
                               'drafted-field-generic: "How we\'ll know" names nothing of this card; '
                               'a draft draws on the rest of the card')


class Rules(ValidatorTest):
    def test_the_card_these_tests_build_on_passes(self):
        self.assert_passes(filled())

    def test_output_missing(self):
        self.assert_breaks(None, "output-missing: card-filled.md is missing from the files the run left")
        res = self.check(filled(), name="card.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()),
                         (1, ["output-missing: card-filled.md is missing from the files the run left"]))

    def test_drafted_field_missing(self):
        said = 'drafted-field-missing: "How we\'ll know" is absent or empty; it is the field a draft may fill'
        self.assert_breaks(filled(None), said)
        self.assert_breaks(filled("**How we'll know**:"), said)

    def test_drafted_tag_missing(self):
        self.assert_breaks(filled(DRAFT.replace(" [Inferred]", "")),
                           'drafted-tag-missing: "How we\'ll know" ends in no valid epistemic tag')

    def test_drafted_tag_dishonest(self):
        self.assert_breaks(filled(DRAFT.replace("[Inferred]", "[Tested]")),
                           'drafted-tag-dishonest: "How we\'ll know" is tagged [Tested]; '
                           'nobody measured or tested a text drafted in this run')

    def test_never_filled(self):
        said = 'never-filled: "What it risks" is in the file; only the author writes it'
        self.assert_breaks(filled(f"**What it risks**: Double charges. [Assumed]\n{DRAFT}"), said)
        self.assert_breaks(filled() + "\nwhat it risks: to be written by the author\n", said)  # another shape

    def test_author_field_missing(self):
        card = filled().replace("**When**: Before the November sales campaign starts. [Assumed]\n", "")
        self.assert_breaks(card, 'author-field-missing: "When" is gone; the author wrote it')

    def test_author_field_rewritten(self):
        card = filled().replace("retry three times with backoff", "retry five times with backoff")
        self.assert_breaks(card, 'author-field-rewritten: "How" no longer says what the author wrote')

    def test_author_tag_rewritten(self):
        card = filled().replace("campaign starts. [Assumed]", "campaign starts. [Measured]")
        self.assert_breaks(card, 'author-tag-rewritten: "When" carries [Measured]; the author gave [Assumed]')
        card = filled().replace("**Ticket**: PAY-212", "**Ticket**: PAY-212 [Inferred]")  # a tag was added
        self.assert_breaks(card, 'author-tag-rewritten: "Ticket" carries [Inferred]; the author gave no tag')

    def test_duplicate_field(self):
        self.assert_breaks(filled() + "\n**Ticket**: PAY-212\n", 'duplicate-field: "Ticket" appears more than once')

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        card = filled(f"**What it risks**: Double charges. [Assumed]\n{DRAFT.replace('[Inferred]', '[Measured]')}")
        self.assert_breaks(card,
                           'drafted-tag-dishonest: "How we\'ll know" is tagged [Measured]; '
                           'nobody measured or tested a text drafted in this run',
                           'never-filled: "What it risks" is in the file; only the author writes it',
                           "2 rules broken: drafted-tag-dishonest, never-filled")


if __name__ == "__main__":
    unittest.main()
