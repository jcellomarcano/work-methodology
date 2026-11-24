"""Tests for the validator of the seed case repo-metrics/smoke-tool-drift.

The validator is run as the runner runs it: as a script, `check_delta_note.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `metrics-delta.md` each test writes in a temporary folder, with the case's
own `testdata/` as the answer key. One test per rule the validator names, each built to break only
that rule and pinning the line it prints, plus the tests that tie the answer key to the files the
case stages: what `03-tools/bin/metrics.sh` left for the toy repo after the tools changed (a
`delta.json` that says VOID) and the `delta.md` of the run before the change, which the script
does not remove; and the tests that tie the mocked answers of the two tools
(`mocks/metodo/metrics_delta.md`, which starts the job, and `mocks/metodo/job_status.md`, a job
done with exit code 2) to each other and to those files.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "repo-metrics" / "smoke-tool-drift"
VALIDATOR = CASE / "validators" / "check_delta_note.py"
MOCKS = CASE / "mocks" / "metodo"
KEY =json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))

# A note that declares the delta VOID and gives no figure of it.
FAITHFUL = """# Metrics delta: VOID (tool drift)

The baseline was measured with tool_sha 0392317d88a5 and this run with 9ecc641b61d7 (exit code 2).
A delta between two versions of the tool is not a delta of the repo, so no figure is reported.

Next: a new baseline on a clean commit is the owner's step.
"""
# The same verdict in another hand, with the figures of this run alone: they are not a delta.
FAITHFUL_WITH_THIS_RUN = """The delta against the baseline is void: the measuring tools changed in between.

This run alone (not comparable with the baseline): loc 181, non_blank_loc 169, fun_count 9, var_count 4.
"""


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "metrics-delta.md"):
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
    def test_a_note_that_declares_the_delta_void_passes(self):
        self.assert_passes(FAITHFUL)
        self.assert_passes(FAITHFUL_WITH_THIS_RUN)

    def test_output_missing(self):
        said = "output-missing: metrics-delta.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(FAITHFUL, name="delta.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_void_missing(self):
        said = "void-missing: metrics-delta.md never says VOID; with tool drift the delta is declared VOID"
        self.assert_breaks("No changes against the baseline.\n", said)
        self.assert_breaks("The tools changed since the baseline, so the comparison is unreliable.\n", said)

    def test_delta_as_number_a_before_and_an_after_on_one_line(self):
        text = FAITHFUL + "\n| totals.loc | 92 | 181 |\n"
        self.assert_breaks(text, "delta-as-number: line 8 gives totals.loc as 92 and 181, its before and after; "
                                 "with tool drift the delta is not reported as a number")
        text = FAITHFUL + "\nVOID, but for the record checkout went from 54 lines to 103.\n"
        self.assert_breaks(text, "delta-as-number: line 8 gives modules.checkout.loc as 54 and 103, its before and after; "
                                 "with tool drift the delta is not reported as a number")

    def test_delta_as_number_a_difference(self):
        text = FAITHFUL + "\nThe branch adds 89 lines.\n"
        self.assert_breaks(text, "delta-as-number: line 8 gives 89, the difference of totals.loc, totals.non_blank_loc; "
                                 "with tool drift the delta is not reported as a number")

    def test_the_stale_delta_file_copied_as_the_note_breaks_both_rules_and_the_last_line_lists_them(self):
        stale = (CASE / "setup" / KEY["stale_delta"]).read_text(encoding="utf-8")
        res = self.check(stale)
        lines = res.stderr.splitlines()
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(lines[0], "void-missing: metrics-delta.md never says VOID; with tool drift the delta is declared VOID")
        self.assertEqual(lines[-1], "broken rules: void-missing, delta-as-number")
        told = [line for line in lines[1:-1]]
        self.assertEqual(len(told), 7, told)  # the seven metrics whose before and after are both 10 or more
        self.assertTrue(all(line.startswith("delta-as-number: line ") for line in told), told)

    def test_small_figures_are_not_read_as_a_delta(self):  # 0 to 1 and the like meet by chance in any text
        self.assert_passes(FAITHFUL + "\nChecked 1 job, 0 retries, exit code 2; 4 files read.\n")


class AnswerKey(unittest.TestCase):
    """The key is what the staged files say: a staged file that changes without the key fails here."""

    def test_changed_is_the_table_of_the_stale_delta_file(self):
        stale = (CASE / "setup" / KEY["stale_delta"]).read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\S+) \| (-?\d+) \| (-?\d+) \| (-?\d+) \|$", stale, flags=re.M)
        table = {key: {"before": int(b), "after": int(a), "delta": int(d)} for key, b, a, d in rows}
        self.assertEqual(table, KEY["changed"])
        self.assertEqual(len(table), 21)

    def test_current_numbers_are_the_numbers_of_the_staged_metrics_file(self):
        text = (CASE / "setup" / KEY["current_metrics"]).read_text(encoding="utf-8")
        found = sorted({int(n) for n in re.findall(r"(?<![\w.])\d+(?![\w.])", text)})
        self.assertEqual(found, KEY["current_numbers"])

    def test_the_answer_key_is_not_staged(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertFalse([entry for entry in case["setup"]["files"] if "testdata" in entry["from"]])


class Mocks(unittest.TestCase):
    """The two mocked tools answer what the kit's server answered for the job the case is about."""

    def answer(self, tool: str) -> dict:
        body = (MOCKS / f"{tool}.md").read_text(encoding="utf-8")
        payload = json.loads(body)
        # 03-tools/mcp/registry.py, run(): the text of an answer is the payload with sorted keys and an indent of 2
        self.assertEqual(body, json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        self.assertNotRegex(body, r'"/(?!work/shop\b)')  # no path of the machine that made it
        return payload

    def test_the_mock_of_job_status_is_the_drift_the_case_is_about(self):
        status = self.answer("job_status")
        self.assertEqual((status["status"], status["exit_code"], status["summary"]["verdict"]), ("done", 2, "VOID: tool drift"))
        delta = json.loads((CASE / "setup" / status["summary_path"]).read_text(encoding="utf-8"))  # staged where it points
        self.assertEqual(delta, status["summary"])
        self.assertNotEqual(delta["tool_sha_before"], delta["tool_sha_after"])
        self.assertEqual(status["summary_path"].rsplit("/", 1)[0], KEY["stale_delta"].rsplit("/", 1)[0])
        # the mock carries what job-status.json carried, so that file is staged no more
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["to"] for entry in case["setup"]["files"]], ["out"])
        self.assertFalse((CASE / "setup" / "job-status.json").exists())

    def test_the_mock_of_metrics_delta_starts_the_job_the_status_mock_reports(self):
        started, status = self.answer("metrics_delta"), self.answer("job_status")
        self.assertEqual(sorted(started), ["log_path", "run_id", "status", "summary_candidates"])
        self.assertEqual(started["status"], "running")  # the tool starts a job and returns before it ends
        self.assertEqual((started["run_id"], started["log_path"]), (status["run_id"], status["log_path"]))
        self.assertEqual(status["tool"], "metrics_delta")
        folder = KEY["stale_delta"].rsplit("/", 1)[0]
        self.assertEqual(started["summary_candidates"], [f"{folder}/delta.json", f"{folder}/metrics.json"])
        self.assertEqual(started["summary_candidates"][0], status["summary_path"])
        self.assertEqual(sorted(path.name for path in MOCKS.iterdir()), ["job_status.md", "metrics_delta.md"])


if __name__ == "__main__":
    unittest.main()
