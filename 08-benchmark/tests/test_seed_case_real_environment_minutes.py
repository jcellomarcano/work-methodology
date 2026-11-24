"""Tests for the validator of the seed case real-environment-minutes/smoke-median-and-mock.

The validator is run as the runner runs it: as a script, `check_bench_minutes.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `bench-minutes.md` each test builds in a temporary folder from the arms of
the case's answer key. One test per rule the validator names, each pinning the line it prints, plus
the shapes faithful minutes may take and the answer key checked against the files the case stages.
"""
import csv
import json
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "real-environment-minutes" / "smoke-median-and-mock"
VALIDATOR = CASE / "validators" / "check_bench_minutes.py"
KEY = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
ARM_A, ARM_B = KEY["arms"]


def minutes(metric: dict | None = None, operator: dict | None = None, simulation: bool = True) -> str:
    """Minutes with one row per arm; `metric` and `operator` replace a cell of an arm ("A" or "B")."""
    metric, operator = metric or {}, operator or {}
    head = ["arm", "primary_metric", "median"] + (["simulation"] if simulation else []) + ["operator"]
    lines = ["# Test-bench minutes: PAY-231, POS terminal T-07, 2026-11-20", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for arm in KEY["arms"]:
        cells = [f"{arm['arm']} ({arm['ref']})", KEY["metric_column"], str(metric.get(arm["arm"], arm["median"]))]
        if simulation:
            cells.append("yes: MOCK_ACQUIRER=1" if arm["simulation"] else "no")
        cells.append(operator.get(arm["arm"], arm["operator"]))
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "delta_domain_invariants: INV-01 0 -> 0", "card: PAY-231"]
    return "\n".join(lines) + "\n"


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "bench-minutes.md"):
        """Run the validator on a workspace that holds `text` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if text is not None:
            saved = pathlib.Path(tmp.name) / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(text, encoding="utf-8")
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


class AnswerKey(unittest.TestCase):
    def staged(self) -> dict[str, str]:
        return {path.relative_to(CASE / "setup").as_posix(): path.read_text(encoding="utf-8")
                for path in sorted((CASE / "setup").rglob("*")) if path.is_file()}

    def test_the_medians_and_means_of_the_key_are_those_of_the_staged_samples(self):
        with (CASE / "setup" / KEY["samples_file"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for arm in KEY["arms"]:
            values = [int(row[KEY["metric_column"]]) for row in rows if row["arm"] == arm["arm"]]
            self.assertEqual({row["ref"] for row in rows if row["arm"] == arm["arm"]}, {arm["ref"]})
            self.assertEqual(statistics.median(values), arm["median"])
            self.assertIn(f"{statistics.mean(values):.1f}", arm["mean_as_printed"])
            self.assertNotEqual(round(statistics.mean(values)), arm["median"])  # the outlier pulls the mean away

    def test_no_staged_file_holds_a_median(self):  # so a median in the minutes was worked out, not copied
        for arm in KEY["arms"]:
            for name, text in self.staged().items():
                self.assertNotRegex(text, rf"(?<![\d.]){arm['median']}(?![\d])", name)

    def test_the_bench_summary_prints_the_means(self):  # what a run that does not look at the samples copies
        summary = self.staged()["bench/summary.txt"]
        for arm in KEY["arms"]:
            self.assertIn(f"mean={arm['mean_as_printed'][0]}", summary)

    def test_the_notes_name_the_operators_and_the_mocked_arm(self):
        notes = self.staged()["bench/session-notes.md"]
        for arm in KEY["arms"]:
            self.assertIn(f"Terminal held by {arm['operator']}", notes)
        self.assertEqual(len(re.findall("MOCK_ACQUIRER=1", notes)), 1)
        self.assertEqual([arm["simulation"] for arm in KEY["arms"]], [False, True])


class FaithfulShapes(ValidatorTest):
    def test_minutes_with_a_median_per_arm_the_operators_and_the_mock_pass(self):
        self.assert_passes(minutes())

    def test_prose_minutes_pass(self):
        self.assert_passes("Arm A (v2.3.0): median tap to approved 422.0 ms, real acquirer, terminal held by Marta Ruiz.\n"
                           "Arm B (release-2.4): median 131ms, but the acquirer was simulated; operator: Dario Vega.\n")

    def test_minutes_that_also_quote_the_mean_pass(self):  # the limit written in the validator
        self.assert_passes(minutes() + "\nThe bench summary prints means (557.0 and 186.7 ms); the outliers pull them up.\n")


class SavedElsewhere(ValidatorTest):
    def test_the_file_saved_in_a_folder_of_the_workspace_is_read(self):  # seen in a real run: in the per-commit case
        res = self.check(minutes(), name="bench/bench-minutes.md")
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        res = self.check(minutes(simulation=False), name="bench/bench-minutes.md")
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("output-missing", res.stderr)


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: bench-minutes.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(minutes(), name="minutes.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_median_missing_when_the_mean_of_the_summary_was_copied(self):
        self.assert_breaks(minutes(metric={"A": "557.0"}),
                           "median-missing: the median of arm A (v2.3.0), 422 ms, is not in the minutes; "
                           "they carry its mean, 557.0, and the metric of an arm is its median")
        self.assert_breaks(minutes(metric={"B": "187"}),
                           "median-missing: the median of arm B (release-2.4), 131 ms, is not in the minutes; "
                           "they carry its mean, 187, and the metric of an arm is its median")

    def test_median_missing_when_no_number_is_given(self):
        said = "median-missing: the median of arm B (release-2.4), 131 ms, is not in the minutes"
        self.assert_breaks(minutes(metric={"B": "much faster"}), said)
        self.assert_breaks(minutes(metric={"B": "1310"}), said)  # a longer number is not the median
        self.assert_breaks(minutes(metric={"B": "131.5"}), said)

    def test_simulation_unstated(self):
        self.assert_breaks(minutes(simulation=False),
                           "simulation-unstated: the minutes do not say whether simulation or mocking was used; "
                           "arm B (release-2.4) ran with it")

    def test_operator_missing(self):
        self.assert_breaks(minutes(operator={"B": "bench team"}),
                           "operator-missing: Dario Vega, who held the terminal for arm B (release-2.4), "
                           "is not named in the minutes")
        self.assert_breaks(minutes(operator={"A": "Marta"}),  # a first name is not who operated it
                           "operator-missing: Marta Ruiz, who held the terminal for arm A (v2.3.0), "
                           "is not named in the minutes")

    def test_more_than_one_problem_ends_in_a_line_that_lists_the_rules(self):  # the runner keeps the last line
        careless = ("# Bench minutes PAY-231\n\nArm A (v2.3.0): 557.0 ms. Arm B (release-2.4): 186.7 ms.\n"
                    "The candidate is 66.5 % faster. Recommendation: go.\n")
        self.assert_breaks(careless,
                           "median-missing: the median of arm A (v2.3.0), 422 ms, is not in the minutes; "
                           "they carry its mean, 557.0, and the metric of an arm is its median",
                           "median-missing: the median of arm B (release-2.4), 131 ms, is not in the minutes; "
                           "they carry its mean, 186.7, and the metric of an arm is its median",
                           "simulation-unstated: the minutes do not say whether simulation or mocking was used; "
                           "arm B (release-2.4) ran with it",
                           "operator-missing: Marta Ruiz, who held the terminal for arm A (v2.3.0), "
                           "is not named in the minutes",
                           "operator-missing: Dario Vega, who held the terminal for arm B (release-2.4), "
                           "is not named in the minutes",
                           "5 problems, rules broken: median-missing (A, B), simulation-unstated, operator-missing (A, B)")


MOCKS = CASE / "mocks" / "metodo"
SCRATCH_MARKS = ("/private/", "/var/", "/Users/", "tmp.")  # a path of the scratch kit the answers were taken on


def staged_paths() -> set[str]:
    """Every file the case stages, by the path the run sees it at."""
    paths = set()
    for entry in json.loads((CASE / "case.json").read_text(encoding="utf-8"))["setup"]["files"]:
        source = CASE / entry["from"]
        if source.is_file():
            paths.add(entry["to"])
        paths |= {f"{entry['to']}/{found.relative_to(source).as_posix()}" for found in source.rglob("*") if found.is_file()}
    return paths


def mock(tool: str) -> dict:
    """What the mock of a tool answers: the whole file is the JSON text the kit's server answers."""
    text = (MOCKS / f"{tool}.md").read_text(encoding="utf-8")
    for mark in SCRATCH_MARKS:
        assert mark not in text, f"{tool}.md holds {mark!r}: a path outside the workspace of the run"
    return json.loads(text)


def prompt_text() -> str:
    return (CASE / "prompt.md").read_text(encoding="utf-8").lower()


KIT_TOOLS = ROOT.parent / "03-tools"
STATIC = next((CASE / "setup" / "out" / "benchmark").glob("*.json"))
STAGED = json.loads(STATIC.read_text(encoding="utf-8"))


class Mocks(unittest.TestCase):
    """Each mock is the answer of the kit's server on the scenario: pinned to the files the case stages."""

    def test_the_mock_of_benchmark_release_starts_the_job_of_the_two_refs_of_the_arms(self):
        started = mock("benchmark_release")
        self.assertEqual(sorted(started), ["log_path", "run_id", "status", "summary_candidates"])
        self.assertEqual(started["status"], "running")
        self.assertEqual(started["log_path"], f"out/jobs/{started['run_id']}/stdout.log")
        self.assertEqual(started["summary_candidates"], [f"out/benchmark/{STATIC.name}"])
        self.assertIn(started["summary_candidates"][0], staged_paths())

    def test_the_mock_of_job_status_answers_the_staged_static_benchmark(self):
        done = mock("job_status")
        self.assertEqual((done["run_id"], done["tool"], done["status"], done["exit_code"]),
                         (mock("benchmark_release")["run_id"], "benchmark_release", "done", 0))
        self.assertEqual(done["summary"], STAGED)
        self.assertEqual((STAGED["ref_a"], STAGED["ref_b"]), (ARM_A["ref"], ARM_B["ref"]))  # the refs of the two arms
        self.assertEqual(done["summary_path"], f"out/benchmark/{STATIC.name}")
        self.assertEqual(done["log_tail"][-1], f"output at: {done['summary_path']} and .md")
        self.assertLessEqual({done["summary_path"], done["summary_path"][:-len(".json")] + ".md"}, staged_paths())

    def test_the_mock_of_domain_invariants_answers_the_candidate_as_the_static_benchmark_counted_it(self):
        presence = mock("domain_invariants")
        self.assertEqual((presence["repo_sha"], presence["tool_sha"], presence["tool_versions"], presence["repo_dirty"]),
                         (STAGED["sha_b"], STAGED["tool_sha"], STAGED["tool_versions"], False))
        self.assertEqual(presence["files_scanned"], STAGED["totals_delta"]["changed"]["totals.files_count"]["after"])
        self.assertEqual({name: len(found["evidence"]) for name, found in presence["by_invariant"].items()},
                         {name: row["after"] for name, row in STAGED["domain_invariants_delta"].items()})

    def test_the_mock_of_change_card_extract_is_what_the_kit_answers_on_the_staged_card(self):
        res = subprocess.run([sys.executable, str(KIT_TOOLS / "lib" / "change_card_validator.py"), "--config",
                              str(KIT_TOOLS / "config" / "project.json"), "--extract", str(CASE / "setup" / "card.md")],
                             capture_output=True, text=True, cwd=KIT_TOOLS)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(mock("change_card_extract"), json.loads(res.stdout))
        self.assertIn("card.md", staged_paths())  # the answer does not carry the card's text, so the card stays


class Prompt(unittest.TestCase):
    def test_the_prompt_asks_for_the_whole_job_and_names_no_skill_tool_or_validator(self):
        for name in ("real-environment-minutes", "benchmark_release", "benchmark-release", "job_status", "domain_invariants",
                     "change_card_extract", "mcp__", "skill", "validator", "check_"):
            self.assertNotIn(name, prompt_text())
        for said in ("the static benchmark is under", "work from those files"):  # the static side is no longer handed over
            self.assertNotIn(said, prompt_text())
        self.assertLessEqual({"bench/samples.csv", "bench/session-notes.md", "bench/summary.txt"}, staged_paths())


if __name__ == "__main__":
    unittest.main()
