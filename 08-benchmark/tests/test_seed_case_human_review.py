"""Tests for the validator of the seed case human-review/smoke-reviewer-brief.

The validator is run as the runner runs it: as a script, `check_reviewer_brief.py WORKSPACE
TESTDATA`, under `python3 -I`, on a workspace each test builds in a temporary folder: the reply the
case stages (`setup/round/003-reply.md`) and a `round/004-brief.md`. The case's own `testdata/` is
the answer key. One test per rule the validator names, each pinning the line it prints, plus the
shapes a faithful brief can take: the kit's template, bold labels, a table.
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "human-review" / "smoke-reviewer-brief"
VALIDATOR = CASE / "validators" / "check_reviewer_brief.py"
REPLY = (CASE / "setup" / "round" / "003-reply.md").read_text(encoding="utf-8")
INPUTS = "INPUTS: round/003-reply.md, 07-communication/rules.md\n"
CONSTRAINTS = "CONSTRAINTS: judge only COM-07, COM-12, COM-13, COM-16, COM-17; reader: public; do not rewrite the reply\n"
OUTPUT = "OUTPUT: human-reviewer-output, written with output_write into round/; JSON only, no prose\n"
BUDGET = "BUDGET: max_context_tokens=15000; max_tool_calls=10\n"
BRIEF = (
    "ROLE: generic-human-reviewer\n"
    "OBJECTIVE: A table of findings on round/003-reply.md against the five judgment rules.\n"
    "SPECS: none\n"
    "ACCEPTANCE: output_write accepts the review as human-reviewer-output\n"
    + INPUTS +
    "SCOPE: no edits; read round/\n"
    "ALREADY READ: round/003-reply.lint.json verdict PASS\n"
    + CONSTRAINTS + OUTPUT +
    "STOP: acceptance passes, budget deny, or a blocking unknown\n"
    + BUDGET +
    "EVIDENCE: cite the reply's line for every finding; tag every claim\n"
)
BOLD = (
    "# Brief for generic-human-reviewer\n\n"
    "**INPUTS**: `round/003-reply.md` and `07-communication/rules.md`\n\n"
    "**CONSTRAINTS**:\n- Rules COM-07, COM-12/13, COM-16 and COM-17 only\n- Declared reader: public\n\n"
    "**OUTPUT**: the round directory (`round/`), schema `human-reviewer-output`\n\n"
    "**BUDGET**: 15,000 tokens, 10 calls\n"
)
TABLE = (
    "| Field | Value |\n|---|---|\n"
    "| ROLE | generic-human-reviewer |\n"
    "| INPUTS | round/003-reply.md; 07-communication/rules.md |\n"
    "| CONSTRAINTS | COM-07, COM-12, COM-13, COM-16, COM-17; reader public |\n"
    "| OUTPUT | round/ |\n"
    "| BUDGET | 15k tokens, 10 tool calls |\n"
)
HEADINGS = (
    "## ROLE\ngeneric-human-reviewer\n\n## INPUTS\n- round/003-reply.md\n- 07-communication/rules.md\n\n"
    "## CONSTRAINTS\nCOM-07, COM-12, COM-13, COM-16, COM-17. Reader: public.\n\n"
    "## OUTPUT\nround/\n\n## BUDGET\n15000 tokens and 10 calls\n"
)


class ValidatorTest(unittest.TestCase):
    def check(self, brief: str | None, reply: str | None = REPLY, name: str = "004-brief.md"):
        """Run the validator on a workspace with `round/<name>` and the reply (None: that file is absent)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = pathlib.Path(tmp.name) / "round"
        folder.mkdir()
        if brief is not None:
            (folder / name).write_text(brief, encoding="utf-8")
        if reply is not None:
            (folder / "003-reply.md").write_text(reply, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, brief: str):
        res = self.check(brief)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), brief)

    def assert_breaks(self, brief: str | None, *lines: str, reply: str | None = REPLY):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(brief, reply)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Faithful(ValidatorTest):
    def test_a_brief_in_the_shape_of_the_kits_template_passes(self):
        self.assert_passes(BRIEF)

    def test_a_brief_with_bold_labels_passes(self):
        self.assert_passes(BOLD)

    def test_a_brief_written_as_a_table_passes(self):
        self.assert_passes(TABLE)

    def test_a_brief_with_a_heading_per_field_passes(self):
        self.assert_passes(HEADINGS)


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: round/004-brief.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(BRIEF, name="brief.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_field_missing(self):
        self.assert_breaks(BRIEF.replace(BUDGET, ""), "field-missing: the brief has no BUDGET field")
        self.assert_breaks(BRIEF.replace(INPUTS, "INPUTS:\n"), "field-missing: the brief has no INPUTS field")

    def test_role_missing(self):
        self.assert_breaks(BRIEF.replace("generic-human-reviewer", "style-reviewer model=haiku"),
                           "role-missing: the brief does not name generic-human-reviewer")

    def test_inputs_missing(self):
        self.assert_breaks(BRIEF.replace(INPUTS, "INPUTS: round/003-reply.md\n"),
                           "inputs-missing: INPUTS does not name rules.md")
        self.assert_breaks(BRIEF.replace(INPUTS, "INPUTS: the reply, 07-communication/rules.md\n"),
                           "inputs-missing: INPUTS does not name round/003-reply.md")

    def test_rules_missing(self):
        self.assert_breaks(BRIEF.replace("COM-13, ", ""), "rules-missing: CONSTRAINTS does not name COM-13")

    def test_rule_outside_the_five(self):
        self.assert_breaks(BRIEF.replace("COM-07, ", "COM-05, COM-07, "),
                           "rule-outside-the-five: CONSTRAINTS names COM-05; the reviewer judges only "
                           "COM-07, COM-12, COM-13, COM-16, COM-17")

    def test_reader_missing(self):
        self.assert_breaks(BRIEF.replace("reader: public; ", ""),
                           "reader-missing: CONSTRAINTS does not declare the reader (public)")

    def test_output_not_round(self):
        self.assert_breaks(BRIEF.replace(OUTPUT, "OUTPUT: a table of findings in the chat\n"),
                           "output-not-round: OUTPUT does not name the round directory (round/)")

    def test_budget_wrong(self):
        said = "budget-wrong: BUDGET does not carry 15000 tokens and 10 calls"
        self.assert_breaks(BRIEF.replace(BUDGET, "BUDGET: max_context_tokens=60000; max_tool_calls=40\n"), said)
        self.assert_breaks(BRIEF.replace(BUDGET, "BUDGET: max_context_tokens=15000; max_tool_calls=100\n"), said)
        self.assert_breaks(BRIEF.replace(BUDGET, "BUDGET: 10 calls\n"), said)

    def test_reply_rewritten(self):
        self.assert_breaks(BRIEF, "reply-rewritten: round/003-reply.md changed; its author fixes it after the "
                           "findings, never the run that briefs the reviewer",
                           reply=REPLY.replace("what failed 3.", "what failed three times."))
        self.assert_breaks(BRIEF, "reply-rewritten: round/003-reply.md is gone; its author fixes it after the "
                           "findings, never the run that briefs the reviewer", reply=None)

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        brief = BRIEF.replace("generic-human-reviewer", "reviewer").replace(BUDGET, "BUDGET: 20 calls\n")
        self.assert_breaks(brief,
                           "role-missing: the brief does not name generic-human-reviewer",
                           "budget-wrong: BUDGET does not carry 15000 tokens and 10 calls",
                           "2 rules broken: role-missing, budget-wrong")


if __name__ == "__main__":
    unittest.main()
