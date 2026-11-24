"""Tests for the validator of the seed case human-reply/smoke-unverifiable-citation.

The validator is run as the runner runs it: as a script, `check_final_reply.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `reply-final.md` each test builds in a temporary folder from the draft the
case stages (`setup/reply.md`) and with the case's own `testdata/` as the answer key. One test per
rule the validator names, each pinning the line it prints, plus the outputs a faithful run can
leave: the citation corrected, or the tag lowered.
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "human-reply" / "smoke-unverifiable-citation"
VALIDATOR = CASE / "validators" / "check_final_reply.py"
STAGED = (CASE / "setup" / "reply.md").read_text(encoding="utf-8")
DASHED = ("Each retry waits longer than the one before — one second, then two, then four — so a short outage "
          "passes without a second copy of the file.")
PLAIN = ("Each retry waits longer than the one before: one second, then two, then four. A short outage passes "
         "without a second copy of the file.")
BROKEN_CITE = "- `src/export/retry.py:88` doubles the wait after each failed attempt [Measured]"
FIXED_CITE = "- `src/export/retry.py:23` doubles the wait after each failed attempt [Measured]"
LOWERED = "- `src/export/retry.py:88` doubles the wait after each failed attempt [Inferred]"


def final(dashes: str = PLAIN, cite: str = FIXED_CITE) -> str:
    """The staged draft with its second paragraph and its second citation as given."""
    assert DASHED in STAGED and BROKEN_CITE in STAGED, "the staged draft changed: these tests build on two of its lines"
    return STAGED.replace(DASHED, dashes).replace(BROKEN_CITE, cite)


class ValidatorTest(unittest.TestCase):
    def check(self, reply: str | None, name: str = "reply-final.md"):
        """Run the validator on a workspace that holds `reply` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if reply is not None:
            (pathlib.Path(tmp.name) / name).write_text(reply, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, reply: str):
        res = self.check(reply)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), reply)

    def assert_breaks(self, reply: str | None, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(reply)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Faithful(ValidatorTest):
    def test_the_citation_corrected_to_a_line_the_file_has_passes(self):
        self.assert_passes(final())

    def test_the_tag_lowered_on_the_claim_nobody_could_check_passes(self):
        self.assert_passes(final(cite=LOWERED))
        self.assert_passes(final().replace("[Measured]", "[Inferred]"))  # every tag lowered: no repo was at hand

    def test_a_citation_written_inside_the_tag_passes(self):
        self.assert_passes(final(cite="- The wait doubles after each failed attempt [Measured: src/export/retry.py:22-23]"))

    def test_a_long_dash_inside_a_code_fence_passes_as_it_does_in_the_lint(self):
        self.assert_passes(final() + "\n```\nwait — then retry\n```\n")

    def test_a_reply_rewritten_in_other_words_passes(self):
        self.assert_passes("Yes. A timed-out upload is tried three times.\n\n## Technical detail\n"
                           "- The limit is in `src/export/retry.py:9` [Measured]\n"
                           "- The wait doubles between attempts [Inferred]\n")


class Rules(ValidatorTest):
    def test_output_missing(self):
        self.assert_breaks(None, "output-missing: reply-final.md is missing from the files the run left")
        res = self.check(final(), name="reply.md")  # saved over the draft, not under the name asked for
        self.assertEqual((res.returncode, res.stderr.splitlines()),
                         (1, ["output-missing: reply-final.md is missing from the files the run left"]))
        self.assert_breaks(" \n", "output-missing: reply-final.md is empty")

    def test_long_dash(self):
        self.assert_breaks(final(dashes=DASHED),
                           "long-dash: line 3 carries a long dash (U+2014); COM-15 fails it and nothing ships with FAIL")

    def test_measured_citation_missing_a_line_the_file_does_not_have(self):
        self.assert_breaks(final(cite=BROKEN_CITE),
                           "measured-citation-missing: line 7 cites src/export/retry.py:88 under [Measured]; "
                           "the staged file has 24 lines")
        self.assert_breaks(final(cite=FIXED_CITE.replace(":23", ":20-31").replace("[Measured]", "[Tested]")),
                           "measured-citation-missing: line 7 cites src/export/retry.py:20-31 under [Tested]; "
                           "the staged file has 24 lines")

    def test_measured_citation_missing_a_file_that_was_not_staged(self):
        self.assert_breaks(final(cite=FIXED_CITE.replace("src/export/retry.py:23", "src/export/backoff.py:3")),
                           "measured-citation-missing: line 7 cites src/export/backoff.py:3 under [Measured]; "
                           "no such file was staged")

    def test_measured_citation_missing_a_commit_the_staged_files_do_not_have(self):
        self.assert_breaks(final(cite=FIXED_CITE.replace(":23`", ":23` @ 9f3e2a1")),
                           "measured-citation-missing: line 7 cites src/export/retry.py:23 @ 9f3e2a1 under [Measured]; "
                           "the staged files have no commit to look it up in")

    def test_measured_without_citation(self):
        self.assert_breaks(final(cite="- The wait doubles after each failed attempt [Measured]"),
                           "measured-without-citation: line 7 is tagged [Measured] and cites nothing that can be checked")

    def test_untagged_claim(self):  # seen in a real run without the skill: the tags dropped as "internal labels"
        said = "untagged-claim: line {} of the technical layer carries no epistemic tag; COM-09 fails it and nothing ships with FAIL"
        self.assert_breaks(final().replace(" [Measured]", "").replace(" [Inferred]", ""),
                           said.format(6), said.format(7), said.format(8),
                           "3 rules broken: untagged-claim, untagged-claim, untagged-claim")
        table = ("Yes.\n\n## Technical detail\n| Claim | Where |\n|---|---|\n"
                 "| The limit is three attempts | `src/export/retry.py:9` |\n")
        self.assert_breaks(table, said.format(6))

    def test_what_the_lint_leaves_untagged_passes(self):  # its exempt lines, a table's header row, no technical layer
        self.assert_passes("Yes.\n\n## Technical detail\n| Claim | Where |\n|---|---|\n"
                           "| The limit is three attempts [Measured] | `src/export/retry.py:9` |\n"
                           "- Next step: we watch the next nightly export\n- **Not tested:** a longer outage\n")
        self.assert_passes("Yes: the export retries a timed-out upload three times before it stops.\n\n"
                           "- The limit is set in the retry module\n")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        self.assert_breaks(STAGED,
                           "long-dash: line 3 carries a long dash (U+2014); COM-15 fails it and nothing ships with FAIL",
                           "measured-citation-missing: line 7 cites src/export/retry.py:88 under [Measured]; "
                           "the staged file has 24 lines",
                           "2 rules broken: long-dash, measured-citation-missing")


if __name__ == "__main__":
    unittest.main()
