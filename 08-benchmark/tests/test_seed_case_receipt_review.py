"""Tests for the validator of the seed case receipt-review/smoke-tier-frozen.

The validator is run as the runner runs it: as a script, `check_context.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `round/000-context.md` each test builds in a temporary folder and with
the case's own `testdata/` as the answer key. One test per rule the validator names, each pinning
the line it prints. One test holds the answer key against the receipt the case stages, which is
real output of the kit's `rdd_receipt.py start`, so the key cannot drift from what the run is given.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "receipt-review" / "smoke-tier-frozen"
VALIDATOR = CASE / "validators" / "check_context.py"
TREE = "5f306ba1af35bcf710394eb2d8cd411b02d9505b"
COMMIT = "5cfc1091d407f173683c358e1a3e7f1badcfac61"
ALL_LENSES = "flujo-critico, jamas-peor-que-antes, tests-anti-flake, simplicidad"

RISK = "RISK: high (touches critical_paths: booking/SeatHold.kt)"
LENSES = f"LENSES: {ALL_LENSES}"
RECEIPT = f"RECEIPT: out/rdd/{TREE}.receipt.json"
FROZEN = 'the script derived "high" and the tier stays frozen'
TIED = "the receipt is tied to the tree, not the commit"


def context(risk: str | None = RISK, lenses: str | None = LENSES, receipt: str | None = RECEIPT, more: str = "") -> str:
    """The round context with the three lines the skill pastes; None leaves a line out."""
    lines = ["# Round context: BOOK-118", "", "CHANGE CARD: round/001-card.md", risk, lenses, receipt, more]
    return "\n".join(line for line in lines if line is not None) + "\n"


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "round/000-context.md"):
        """Run the validator on a workspace that holds `text` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if text is not None:
            path = pathlib.Path(tmp.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
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


class Faithful(ValidatorTest):
    def test_the_context_these_tests_build_on_passes(self):
        self.assert_passes(context())

    def test_labels_in_bold_or_in_a_list_pass(self):
        self.assert_passes(context(risk="- **RISK:** high", lenses=f"- **LENSES**: {ALL_LENSES}",
                                   receipt=f"- `RECEIPT:` out/rdd/{TREE}.receipt.json"))

    def test_a_value_laid_out_on_the_lines_under_its_label_passes(self):
        listed = "LENSES:\n- flujo-critico\n- jamas-peor-que-antes\n- tests-anti-flake\n- simplicidad"
        self.assert_passes(context(risk="RISK:\n  tier: high\n  consent: pending", lenses=listed))

    def test_the_tier_the_owner_asked_for_can_be_named_after_the_one_the_script_derived(self):
        self.assert_passes(context(risk="RISK: high (critical path; the owner asked for low, the tier is the script's)"))

    def test_a_short_tree_sha_passes(self):
        self.assert_passes(context(receipt=f"RECEIPT: out/rdd/{TREE[:12]}.receipt.json"))

    def test_the_answer_key_says_what_the_staged_receipt_says(self):
        receipt = json.loads((CASE / "setup" / "round" / "receipt.json").read_text(encoding="utf-8"))
        key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        self.assertEqual((key["tier"], key["lenses"], key["tree_sha"], key["commit_sha"]),
                         (receipt["risk"]["tier"], receipt["risk"]["lenses"], receipt["tree_sha"], receipt["repo_sha"]))
        self.assertEqual((TREE, COMMIT), (key["tree_sha"], key["commit_sha"]))


class SeenByTheVerifier(ValidatorTest):
    """A faithful line the independent verifier wrote by hand, 2026-11-24: the tree by git's usual seven characters."""

    def test_the_tree_by_the_seven_characters_git_prints_passes(self):
        self.assert_passes(context(receipt=f"RECEIPT: tree {TREE[:7]} (started)"))

    def test_any_abbreviation_of_the_tree_of_seven_characters_or_more_passes(self):
        for chars in (8, 10, 11, 20, 40):
            self.assert_passes(context(receipt=f"RECEIPT: tree `{TREE[:chars]}`, consent pending"))
        self.assert_passes(context(receipt=f"RECEIPT: out/rdd/{TREE[:7]}.receipt.json"))

    def test_what_is_not_an_abbreviation_of_the_tree_still_breaks(self):
        said = f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}"
        self.assert_breaks(context(receipt=f"RECEIPT: tree {TREE[:6]} (started)"), said)  # six characters: too short
        self.assert_breaks(context(receipt=f"RECEIPT: tree {TREE[:7]}0000 (started)"), said)  # another id that starts alike
        self.assert_breaks(context(receipt=f"RECEIPT: commit {COMMIT[:7]} (started)"), said)  # the commit, abbreviated


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: round/000-context.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(context(), name="000-context.md")  # saved outside round/
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_risk_line_missing(self):
        said = "risk-line-missing: no line starts with RISK:"
        self.assert_breaks(context(risk=None), said)
        self.assert_breaks(context(risk="The tier of this change is high."), said)  # prose, not the line

    def test_tier_changed(self):
        self.assert_breaks(context(risk="RISK: low (one-line change)"), f'tier-changed: a RISK line gives "low"; {FROZEN}')
        self.assert_breaks(context(risk="RISK: low (the owner's call; the script said high)"),
                           f'tier-changed: a RISK line gives "low"; {FROZEN}')
        self.assert_breaks(context(risk="RISK: to be confirmed with the owner"), f"tier-changed: a RISK line gives no tier; {FROZEN}")

    def test_tier_changed_on_a_second_risk_line(self):
        self.assert_breaks(context(more="RISK: medium (as agreed with the owner)"),
                           f'tier-changed: a RISK line gives "medium"; {FROZEN}')

    def test_lenses_line_missing(self):
        self.assert_breaks(context(lenses=None), "lenses-line-missing: no line starts with LENSES:")

    def test_lenses_changed(self):
        self.assert_breaks(context(lenses="LENSES: none"),
                           f"lenses-changed: the LENSES line lacks {ALL_LENSES}; the script returned {ALL_LENSES}")
        self.assert_breaks(context(lenses="LENSES: flujo-critico, jamas-peor-que-antes"),
                           f"lenses-changed: the LENSES line lacks tests-anti-flake, simplicidad; the script returned {ALL_LENSES}")

    def test_receipt_line_missing(self):
        self.assert_breaks(context(receipt=None), "receipt-line-missing: no line starts with RECEIPT:")

    def test_receipt_not_the_tree(self):
        self.assert_breaks(context(receipt="RECEIPT: round/receipt.json"),
                           f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}")
        self.assert_breaks(context(receipt=f"RECEIPT: out/rdd/{COMMIT}.receipt.json"),
                           f"receipt-not-the-tree: the RECEIPT line names the commit {COMMIT[:12]}, "
                           f"not the tree {TREE[:12]}; {TIED}")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        light = context(risk="RISK: low", lenses="LENSES: none", receipt="RECEIPT: round/receipt.json")
        self.assert_breaks(light,
                           f'tier-changed: a RISK line gives "low"; {FROZEN}',
                           f"lenses-changed: the LENSES line lacks {ALL_LENSES}; the script returned {ALL_LENSES}",
                           f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}",
                           "3 rules broken: tier-changed, lenses-changed, receipt-not-the-tree")


if __name__ == "__main__":
    unittest.main()
