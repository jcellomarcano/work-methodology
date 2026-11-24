"""Tests for the validator of the seed case pr-message/smoke-skipped-check.

The validator is run as the runner runs it: as a script, `check_pr_body.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `pr-body.md` each test builds in a temporary folder and with the case's
own `testdata/` as the answer key. One test per rule the validator names, each pinning the line it
prints. Every value the faithful body quotes is a line of the run log the case stages, which one
test checks, so the answer key cannot drift from what the run is given.

The two tools the scenario calls are mocked: `mocks/metodo/change_card_validate.md` and
`mocks/metodo/receipt_status.md` are what the kit's tools answered, through the kit's MCP server,
on the staged card and on a scratch repository with the change committed and no receipt opened.
`done_check` has no mock: its answer depends on the reply the run writes.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "pr-message" / "smoke-skipped-check"
VALIDATOR = CASE / "validators" / "check_pr_body.py"
RUN_LOG = (CASE / "setup" / "run-log.md").read_text(encoding="utf-8")
MOCKS = CASE / "mocks" / "metodo"
TOOLS = ROOT.parent / "03-tools"

WHAT = "## What and why\n\nRetries a dropped payment webhook and skips one already applied, so a paid order is recorded once (DEV-212).\n"
HEADER = ("| Observable | Before (develop @ de565a2) | After (feature/retry-webhook @ abd810c) | Evidence |\n"
          "|---|---|---|---|\n")
TEST_ROW = ("| Replayed webhook test | 3 tests completed, 2 failed | 3 tests completed, 0 failed "
            "| `./gradlew :billing:test --tests '*WebhookReplayTest'` |\n")
BENCH_ROW = "| Handler latency | not measured | p95 212 ms | `scripts/bench_webhook.sh` |\n"
BLOCK = "<!--\nCard: card.md, DEV-212, validator PASS, routing opus\nReceipt: none for this tree\n-->\n"
SKIPPED = "- The commit was made with `git commit --no-verify`: the pre-commit hook (detekt over the whole repo) did not run.\n"
GAP = "- Handler latency on develop: `scripts/bench_webhook.sh` exists only on the branch, so that side has no number.\n"
ORDER = '"What and why", "Before and after", "What was NOT tested"'
QUOTED = "a value is quoted as the command produced it"


def before_after(rows: str = TEST_ROW + BENCH_ROW, header: str = HEADER) -> str:
    return f"## Before and after\n\n{header}{rows}"


def untested(items: str = SKIPPED + GAP, heading: str = "## What was NOT tested") -> str:
    return f"{heading}\n\n{items}"


def body(what: str = WHAT, table: str | None = None, block: str = BLOCK, rest: str | None = None) -> str:
    """The pull request description in the skill's order; each piece can be replaced."""
    pieces = (what, before_after() if table is None else table, block, untested() if rest is None else rest)
    return "\n".join(piece for piece in pieces if piece)


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "pr-body.md"):
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


class Faithful(ValidatorTest):
    def test_the_body_these_tests_build_on_passes(self):
        self.assert_passes(body())

    def test_headings_in_bold_or_in_another_letter_case_pass(self):
        text = body(what=WHAT.replace("## What and why", "**What and why**"),
                    table=before_after().replace("## Before and after", "### Before and After"),
                    rest=untested(heading="**What was not tested**"))
        self.assert_passes(text)

    def test_more_rows_and_more_untested_items_pass(self):
        extra_row = "| Duplicate orders in the records | not measured | not measured | no query was run |\n"
        self.assert_passes(body(table=before_after(TEST_ROW + BENCH_ROW + extra_row),
                                rest=untested(SKIPPED + GAP + "- No review receipt exists for this tree.\n")))

    def test_the_answer_key_quotes_the_staged_run_log(self):
        key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        quoted = [value for row in key["rows"] for value in (row["before"], row["after"]) if value]
        for value in (*quoted, *key["skipped_checks"], *key["gap_marks"]):
            self.assertIn(value, RUN_LOG)
        for row in (TEST_ROW, BENCH_ROW):  # the cells of the faithful table are lines of the log, not paraphrases
            for cell in row.split("|")[2:4]:
                if cell.strip() != key["unmeasured_says"]:
                    self.assertIn(cell.strip(), RUN_LOG)


class Mocks(unittest.TestCase):
    def test_the_mock_of_change_card_validate_is_what_the_kits_validator_answers_on_the_staged_card(self):
        res = subprocess.run([sys.executable, str(TOOLS / "lib" / "change_card_validator.py"), "--config",
                              str(TOOLS / "config" / "project.json"), str(CASE / "setup" / "card.md")],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        mock = json.loads((MOCKS / "change_card_validate.md").read_text(encoding="utf-8"))
        self.assertEqual(mock, json.loads(res.stdout))
        self.assertEqual((mock["verdict"], mock["fields_missing"]), ("PASS", []))

    def test_the_mock_of_receipt_status_says_no_receipt_exists_for_the_tree(self):
        status = json.loads((MOCKS / "receipt_status.md").read_text(encoding="utf-8"))
        self.assertEqual((status["receipt"], status["next"], status["open_receipts"], status["repo_dirty"]),
                         (None, "START", [], False))
        self.assertEqual(sorted(status), ["next", "open_receipts", "receipt", "repo_dirty", "tree_sha"])

    def test_no_mock_says_what_the_answer_key_holds(self):  # the skipped check and the numbers come from the run log alone
        key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        quoted = [value for row in key["rows"] for value in (row["before"], row["after"]) if value]
        self.assertEqual(sorted(path.name for path in MOCKS.iterdir()), ["change_card_validate.md", "receipt_status.md"])
        for path in MOCKS.iterdir():
            text = path.read_text(encoding="utf-8")
            for value in (*quoted, *key["skipped_checks"], *key["gap_marks"], key["unmeasured_says"]):
                self.assertNotIn(value, text, path.name)


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: pr-body.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(body(), name="PR.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_section_missing(self):
        usual = ("## Summary\n\nRetries the payment webhook.\n\n## Testing\n\n- 3 tests completed, 0 failed\n"
                 "- committed with --no-verify\n")
        self.assert_breaks(usual, f"section-missing: the message has no section {ORDER}")
        self.assert_breaks(body(rest=""), 'section-missing: the message has no section "What was NOT tested"')

    def test_section_order(self):
        text = "\n".join((WHAT, untested(), before_after(), BLOCK))
        self.assert_breaks(text, f"section-order: the sections are not in the order {ORDER}")

    def test_card_block_missing(self):
        said = 'card-block-missing: no closed <!-- --> block between "Before and after" and "What was NOT tested"'
        self.assert_breaks(body(block=""), said)
        self.assert_breaks(body(block="", rest=untested() + "\n" + BLOCK), said)  # after the last section
        self.assert_breaks(body(block="<!--\nCard: card.md\n"), said)  # never closed

    def test_table_missing(self):
        bullets = "## Before and after\n\n- Replayed webhook test: 2 failed, then 0 failed\n- p95 212 ms after\n"
        self.assert_breaks(body(table=bullets),
                           'table-missing: "Before and after" has no table with a Before and an After column')

    def test_value_not_quoted(self):
        paraphrased = TEST_ROW.replace("3 tests completed, 2 failed", "two tests failed")
        self.assert_breaks(body(table=before_after(paraphrased + BENCH_ROW)),
                           'value-not-quoted: no row of the table carries "2 failed" under Before and '
                           f'"0 failed" under After; {QUOTED}')
        rounded = BENCH_ROW.replace("p95 212 ms", "about 0.2 s")
        self.assert_breaks(body(table=before_after(TEST_ROW + rounded)),
                           f'value-not-quoted: no row of the table carries "212 ms" under After; {QUOTED}')

    def test_value_not_quoted_when_the_two_sides_are_swapped(self):
        swapped = TEST_ROW.replace("2 failed", "X").replace("0 failed", "2 failed").replace("X", "0 failed")
        self.assert_breaks(body(table=before_after(swapped + BENCH_ROW)),
                           'value-not-quoted: no row of the table carries "2 failed" under Before and '
                           f'"0 failed" under After; {QUOTED}')

    def test_unmeasured_side_filled(self):
        for cell in ("about 200 ms", "n/a", "p95 212 ms"):
            self.assert_breaks(body(table=before_after(TEST_ROW + BENCH_ROW.replace("not measured", cell))),
                               f'unmeasured-side-filled: the row with "212 ms" under After says "{cell}" under Before; '
                               'that side was not measured and says "not measured"')

    def test_skipped_check_quiet(self):
        self.assert_breaks(body(rest=untested(GAP)),
                           'skipped-check-quiet: "What was NOT tested" does not carry --no-verify; '
                           "a skipped check is never kept quiet")
        elsewhere = WHAT + "\nCommitted with --no-verify.\n"  # said, but not where the skill puts it
        self.assert_breaks(body(what=elsewhere, rest=untested(GAP)),
                           'skipped-check-quiet: "What was NOT tested" does not carry --no-verify; '
                           "a skipped check is never kept quiet")

    def test_gap_quiet(self):
        self.assert_breaks(body(rest=untested(SKIPPED)),
                           'gap-quiet: "What was NOT tested" does not name the side that was not measured '
                           "(any of: bench_webhook, p95, latency)")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        text = body(table=before_after(TEST_ROW + BENCH_ROW.replace("not measured", "180 ms")), block="",
                    rest=untested("- Nothing: every check ran.\n"))
        self.assert_breaks(text,
                           'card-block-missing: no closed <!-- --> block between "Before and after" and "What was NOT tested"',
                           'unmeasured-side-filled: the row with "212 ms" under After says "180 ms" under Before; '
                           'that side was not measured and says "not measured"',
                           'skipped-check-quiet: "What was NOT tested" does not carry --no-verify; '
                           "a skipped check is never kept quiet",
                           'gap-quiet: "What was NOT tested" does not name the side that was not measured '
                           "(any of: bench_webhook, p95, latency)",
                           "4 rules broken: card-block-missing, unmeasured-side-filled, skipped-check-quiet, gap-quiet")


if __name__ == "__main__":
    unittest.main()
