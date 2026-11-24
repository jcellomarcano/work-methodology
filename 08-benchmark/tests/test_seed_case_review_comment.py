"""Tests for the validator of the seed case review-comment/smoke-base-drift.

The validator is run as the runner runs it: as a script, `check_comments.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `comments/` folder each test builds in a temporary folder and with the
case's own `testdata/` as the answer key. One test per rule the validator names, each pinning the
line it prints. The comment these tests build on is also given to the kit's own lint with the scope
the case mocks, so "faithful" here means what the skill's gate accepts.

The scope is not staged as a file: `mocks/metodo/pr_scope.md` is what the kit's `pr_scope` tool
answered, through the kit's MCP server, on a scratch repository whose tip is the code the case
stages. `review_comment_lint` has no mock: its answer depends on the comment the run writes.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "review-comment" / "smoke-base-drift"
VALIDATOR = CASE / "validators" / "check_comments.py"
MOCKS = CASE / "mocks" / "metodo"
SCOPE = MOCKS / "pr_scope.md"  # no front matter: the whole file is the JSON the tool answers
LINT = ROOT.parent / "03-tools" / "lib" / "review_comment_lint.py"

HEAD = "`billing/RetryPolicy.kt:11` @ abd810c362ac"
PARTS = (
    "What happens: the delay doubles on every attempt and nothing caps it.",
    "Why it happens: `delayMs` multiplies `baseDelayMs` by a power of two with no upper bound.",
    "Impact: a larger `maxAttempts` leaves a webhook thread asleep for minutes, and a paid order stays unrecorded.",
    "How to fix: clamp the delay to a maximum.",
)
BLOCK = "```kotlin\nreturn (baseDelayMs * factor).toLong().coerceAtMost(30_000)\n```"
ORDER = "(what happens: why it happens: impact: how to fix:)"


def comment(head: str = HEAD, parts=PARTS, block: str = BLOCK, between: str = " ") -> str:
    """One review comment as the skill's template lays it out: reference, one paragraph, proposal."""
    return f"{head}\n{between.join(parts)}\n\n{block}\n"


# A comment in the right shape on the file the base branch changed: the finding the notes get wrong.
ON_DRIFT = comment(
    head="`billing/LegacyExport.kt:7` @ abd810c362ac",
    parts=("What happens: the guard around the write is gone.",
           "Why it happens: the try/catch was removed.",
           "Impact: an IOException takes the export down.",
           "How to fix: put the guard back."),
    block="```kotlin\ntry { target.writeText(rows.joinToString(\"\\n\")) } catch (e: IOException) { throw e }\n```")


class ValidatorTest(unittest.TestCase):
    def check(self, files: dict):
        """Run the validator on a workspace that holds `files` ({path under the workspace: text})."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, text in files.items():
            path = pathlib.Path(tmp.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, files: dict):
        res = self.check(files)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), files)

    def assert_breaks(self, files: dict, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(files)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Faithful(ValidatorTest):
    def test_the_comment_these_tests_build_on_passes(self):
        self.assert_passes({"comments/01.md": comment()})

    def test_the_comment_these_tests_build_on_passes_the_kits_own_lint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "01.md"
            path.write_text(comment(), encoding="utf-8")
            res = subprocess.run([sys.executable, str(LINT), str(path), "--scope", str(SCOPE)],
                                 capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["verdict"], "PASS")

    def test_a_second_comment_on_another_file_of_the_pull_request_passes(self):
        other = comment(head="`billing/WebhookHandler.kt:8` @ abd810c362ac")
        self.assert_passes({"comments/01.md": comment(), "comments/02.md": other})

    def test_a_lint_result_saved_beside_the_comment_is_not_read_as_a_comment(self):
        self.assert_passes({"comments/01.md": comment(), "comments/01.lint.json": '{"verdict": "PASS"}'})

    def test_the_answer_key_names_the_files_the_mocked_scope_names(self):
        scope = json.loads(SCOPE.read_text(encoding="utf-8"))
        key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        self.assertEqual(key["pr_files"], [entry["path"] for entry in scope["pr_files"]])
        self.assertEqual(key["base_drift_files"], scope["base_drift_files"])


class Mocks(unittest.TestCase):
    def test_the_mock_of_pr_scope_answers_for_the_pull_request_and_the_code_the_case_stages(self):
        scope = json.loads(SCOPE.read_text(encoding="utf-8"))
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        staged = {entry["to"] for entry in case["setup"]["files"]}
        notes = (CASE / "setup" / "notes.md").read_text(encoding="utf-8")
        self.assertIn(f"{scope['head']} into {scope['base']}", notes)  # the branches the owner names
        named = [entry["path"] for entry in scope["pr_files"]] + scope["base_drift_files"] + scope["mixed_files"]
        self.assertEqual(sorted(named), sorted(path for path in staged if path.startswith("billing/")))
        self.assertEqual((scope["mixed_files"], scope["repo_dirty"]), ([], False))
        self.assertEqual(scope["summary"], {"base_drift": 1, "commits": 1, "mixed": 0, "pr_files": 2})

    def test_the_scope_reaches_the_run_through_the_mock_alone(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["to"] for entry in case["setup"]["files"] if "scope" in entry["to"]], [])
        self.assertFalse((CASE / "setup" / "round" / "001-pr-scope.json").exists())
        self.assertEqual(sorted(path.name for path in MOCKS.iterdir()), ["pr_scope.md"])  # the lint has none


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: comments/ holds no .md file among the files the run left"
        self.assert_breaks({}, said)
        self.assert_breaks({"comments.md": comment()}, said)  # one file beside the folder, not in it
        self.assert_breaks({"comments/01.lint.json": "{}"}, said)

    def test_base_drift_commented(self):
        said = ("base-drift-commented: comments/02.md comments on billing/LegacyExport.kt, "
                "which the base branch changed, not the pull request")
        self.assert_breaks({"comments/01.md": comment(), "comments/02.md": ON_DRIFT}, said)

    def test_base_drift_commented_inside_a_comment_on_another_file(self):  # one long comment with everything
        merged = comment(parts=(*PARTS[:3], PARTS[3] + " Also restore the guard in LegacyExport.kt."))
        self.assert_breaks({"comments/01.md": merged},
                           "base-drift-commented: comments/01.md comments on billing/LegacyExport.kt, "
                           "which the base branch changed, not the pull request")

    def test_reference_missing(self):
        self.assert_breaks({"comments/01.md": comment(head="RetryPolicy, the delay function")},
                           "reference-missing: comments/01.md cites no path:line",
                           "finding-uncommented: no comment cites billing/RetryPolicy.kt, "
                           "the pull request file the notes raise a finding on",
                           "2 rules broken: reference-missing, finding-uncommented")

    def test_not_in_pr(self):
        self.assert_breaks({"comments/01.md": comment(),
                            "comments/02.md": comment(head="`billing/Ledger.kt:3` @ abd810c362ac")},
                           "not-in-pr: comments/02.md comments on billing/Ledger.kt, "
                           "which is not among the pull request's files")

    def test_four_parts(self):
        said = f"four-parts: comments/01.md does not carry the four parts in order {ORDER}"
        self.assert_breaks({"comments/01.md": comment(parts=(PARTS[0], PARTS[1], PARTS[3]))}, said)  # no Impact
        self.assert_breaks({"comments/01.md": comment(parts=(PARTS[0], PARTS[2], PARTS[1], PARTS[3]))}, said)
        free = comment(parts=("The delay doubles on every attempt and nothing caps it, please clamp it.",))
        self.assert_breaks({"comments/01.md": free}, said)  # a free-form comment

    def test_one_paragraph(self):
        self.assert_breaks({"comments/01.md": comment(between="\n\n")},
                           "one-paragraph: comments/01.md has a blank line between its parts")

    def test_caps(self):
        long_part = "Impact: " + "x" * 201
        self.assert_breaks({"comments/01.md": comment(parts=(PARTS[0], PARTS[1], long_part, PARTS[3]))},
                           "caps: comments/01.md goes over the caps (impact: 201 > 200)")
        wide = tuple(f"{label} " + "y" * 160 for label in ("What happens:", "Why it happens:", "Impact:", "How to fix:"))
        self.assert_breaks({"comments/01.md": comment(parts=wide)},
                           "caps: comments/01.md goes over the caps (total 640 > 600)")

    def test_proposal_language(self):
        said = ("proposal-language: comments/01.md has no closed code block tagged kotlin, "
                "the language of billing/RetryPolicy.kt")
        self.assert_breaks({"comments/01.md": comment(block="Clamp it with coerceAtMost.")}, said)  # no block
        self.assert_breaks({"comments/01.md": comment(block="```java\nreturn Math.min(delay, 30000);\n```")}, said)
        self.assert_breaks({"comments/01.md": comment(block="```\nclamp the delay\n```")}, said)  # pseudocode
        self.assert_breaks({"comments/01.md": comment(block="```kotlin\nreturn delay")}, said)  # never closed

    def test_finding_uncommented(self):
        only_other = comment(head="`billing/WebhookHandler.kt:8` @ abd810c362ac")
        self.assert_breaks({"comments/01.md": only_other},
                           "finding-uncommented: no comment cites billing/RetryPolicy.kt, "
                           "the pull request file the notes raise a finding on")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        free = "billing/LegacyExport.kt:7 the try/catch around writeText is gone, put the guard back.\n"
        self.assert_breaks({"comments/01.md": comment(), "comments/02.md": free},
                           "base-drift-commented: comments/02.md comments on billing/LegacyExport.kt, "
                           "which the base branch changed, not the pull request",
                           f"four-parts: comments/02.md does not carry the four parts in order {ORDER}",
                           "proposal-language: comments/02.md has no closed code block tagged kotlin, "
                           "the language of billing/LegacyExport.kt",
                           "3 rules broken: base-drift-commented, four-parts, proposal-language")


if __name__ == "__main__":
    unittest.main()
