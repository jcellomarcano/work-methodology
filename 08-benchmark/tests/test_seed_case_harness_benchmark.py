"""Tests for the validator of the case harness-benchmark/smoke-one-run-report.

The validator is run as the runner runs it: as a script, `check_summary.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `summary.md` each test writes in a temporary folder, with the case's own
`testdata/` as the answer key. One test per rule the validator names, each pinning the line it
prints, plus the tests that keep the staged report honest: it is what the skill's own script prints
for the run kept in `testdata/run/`, and the answer key holds what that report prints.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "harness-benchmark" / "smoke-one-run-report"
VALIDATOR = CASE / "validators" / "check_summary.py"
REPORT = (CASE / "setup" / "run" / "report.md").read_text(encoding="utf-8")
BENCH = ROOT.parent / "02-skills" / "harness-benchmark" / "bench.py"
# A summary that relays the report: its line, its numbers as printed with their n, the invalid arm.
FAITHFUL = """\
**signal, not a conclusion** (k == 1 or fewer than 5 tasks): 4 tasks, 1 run per task and arm.

- pass@1, kit-invoked vs vanilla: diff 0.25 [Measured], 95% CI [0.0, 0.75], n = 4 tasks, 8 runs; reading: not shown.
- cost per run USD, kit-invoked vs vanilla: diff 0.569125 [Measured], 95% CI [0.5229, 0.6111], n = 4 tasks, 8 runs; reading: shown.
- kit-neutral: 4 runs, all invalid-arm (evidence-missing); reported, not scored.

No setup is shown to be better from this run.
"""
SIGNAL = '**signal, not a conclusion** (k == 1 or fewer than 5 tasks)'
INVALID = "- kit-neutral: 4 runs, all invalid-arm (evidence-missing); reported, not scored.\n"
SAID_SIGNAL = 'signal-line-missing: the line "signal, not a conclusion" of run/report.md is not in the summary'
SAID_INVALID = ("invalid-arm-dropped: the summary does not report kit-neutral as invalid-arm; "
                "an arm whose setup did not run is reported, never left out")
RELAYS = "run/report.md prints; a summary relays its numbers, it does not recompute or round them"


class ValidatorTest(unittest.TestCase):
    def check(self, summary: str | None, name: str = "summary.md"):
        """Run the validator on a workspace that holds `summary` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if summary is not None:
            (pathlib.Path(tmp.name) / name).parent.mkdir(parents=True, exist_ok=True)
            (pathlib.Path(tmp.name) / name).write_text(summary, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, summary: str):
        res = self.check(summary)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), summary)

    def assert_breaks(self, summary: str | None, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(summary)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))

    def changed(self, old: str, new: str) -> str:
        assert old in FAITHFUL, f"the faithful summary changed: these tests build on {old!r}"
        return FAITHFUL.replace(old, new)


class Rules(ValidatorTest):
    def test_a_summary_that_relays_the_report_passes(self):
        self.assert_passes(FAITHFUL)

    def test_the_same_summary_in_other_shapes_passes(self):
        self.assert_passes(self.changed(SIGNAL, "Signal, not a conclusion."))  # no bold, another case
        self.assert_passes(self.changed("kit-neutral: 4 runs, all invalid-arm", "`kit neutral`: 4 runs, all `invalid arm`"))
        self.assert_passes(self.changed("diff 0.25 [Measured]", "diff 25% (0.25 [Measured])"))  # the same value as a percentage
        self.assert_passes(self.changed("[0.0, 0.75]", "[0.00, 0.750]"))  # the same values, more zeros

    def test_output_missing(self):
        said = "output-missing: summary.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(FAITHFUL, name="report-summary.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_a_summary_saved_next_to_the_report_is_read_too(self):  # both arms of the first real run did this
        res = self.check(FAITHFUL, name="run/summary.md")
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""))
        res = self.check(FAITHFUL.replace(SIGNAL, "Early results"), name="run/summary.md")
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [SAID_SIGNAL]))

    def test_signal_line_missing(self):
        self.assert_breaks(self.changed(SIGNAL, "Early results"), SAID_SIGNAL)
        self.assert_breaks(self.changed(SIGNAL, "This is a signal and not yet a conclusion"), SAID_SIGNAL)  # reworded

    def test_invalid_arm_dropped(self):
        self.assert_breaks(self.changed(INVALID, ""), SAID_INVALID)
        self.assert_breaks(self.changed(INVALID, "- kit-neutral: 4 runs, none usable.\n"), SAID_INVALID)  # no status
        self.assert_breaks(self.changed(INVALID, "- 4 runs were invalid-arm and are not scored.\n"), SAID_INVALID)  # no arm

    def test_number_not_in_report(self):
        self.assert_breaks(self.changed("diff 0.569125 [Measured]", "diff 0.57 [Measured]"),  # rounded
                           f"number-not-in-report: 0.57 is not a number {RELAYS}")
        self.assert_breaks(FAITHFUL + "\nkit-invoked solved 75% of the tasks and vanilla 50%, at 2.3x the cost ($1.01 vs $0.44).\n",
                           f"number-not-in-report: 50%, 2.3, 1.01, 0.44 are not numbers {RELAYS}")  # recomputed
        many = FAITHFUL + "\nCosts: 0.41, 0.39, 0.45, 0.52, 0.97, 0.88, 0.41.\n"
        self.assert_breaks(many, f"number-not-in-report: 0.41, 0.39, 0.45, 0.52, 0.97 and 1 more are not numbers {RELAYS}")

    def test_whole_numbers_and_the_reports_own_percentage_are_not_checked(self):
        self.assert_passes(FAITHFUL + "\n12 runs in all, 3 arms, k 1, on 2026-11-23; intervals are 95% CIs.\n")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        careless = "kit-invoked is better: it solved 75% of the tasks against 50% for vanilla, at $1.01 a run.\n"
        self.assert_breaks(careless, SAID_SIGNAL, SAID_INVALID,
                           f"number-not-in-report: 50%, 1.01 are not numbers {RELAYS}",
                           "3 rules broken: signal-line-missing, invalid-arm-dropped, number-not-in-report")


class Staged(unittest.TestCase):
    """The staged report is the script's real output and the answer key is drawn from it."""

    def setUp(self):
        self.key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))

    def test_the_staged_report_is_what_the_skills_script_prints_for_the_kept_run(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        res = subprocess.run([sys.executable, str(BENCH), "report", "--run", str(CASE / "testdata" / "run"), "--out", tmp.name],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((pathlib.Path(tmp.name) / "report.md").read_text(encoding="utf-8"), REPORT)

    def test_the_answer_key_holds_what_the_report_prints(self):
        self.assertEqual(self.key["report_decimals"], sorted(set(re.findall(r"\d+\.\d+", REPORT)), key=float))
        self.assertEqual(self.key["report_percentages"], sorted(set(re.findall(r"\d+(?:\.\d+)?%", REPORT))))
        self.assertIn(f"**{self.key['signal_line']}**", REPORT)
        rows = [line for line in REPORT.splitlines()  # its rows in the table per arm and task
                if line.startswith(f"| {self.key['invalid_arm']} | t")]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(line.endswith(f"| {self.key['invalid_status']} |") for line in rows))

    def test_the_run_behind_the_report_is_one_run_per_task_and_arm(self):
        self.assertIn(" · k 1 · ", REPORT)
        self.assertIn("n: 4 tasks, 12 runs (invalid-arm 4, ok 8)", REPORT)

    def test_only_the_report_is_staged(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(case["setup"]["files"], [{"from": "setup/run/report.md", "to": "run/report.md"}])


if __name__ == "__main__":
    unittest.main()
