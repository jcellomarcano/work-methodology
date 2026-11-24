"""Tests for the validator of the seed case benchmark-release/smoke-base-is-the-tag.

The validator is run as the runner runs it: as a script, `check_release_benchmark.py WORKSPACE
TESTDATA`, under `python3 -I`, on a `release-benchmark.md` each test builds in a temporary folder
from the figures of the case's answer key. One test per rule the validator names, each pinning the
line it prints, plus the shapes a faithful write-up may take and the answer key checked against the
two comparisons the case stages.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "benchmark-release" / "smoke-base-is-the-tag"
VALIDATOR = CASE / "validators" / "check_release_benchmark.py"
KEY = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
MAIN_FIGURES = "-14, -27, -189, -857, -1023"  # the deltas that only the comparison based at main holds


def summary_table(side: str) -> str:
    """The summary table of one comparison, as the kit's script renders it (`+` on a rise)."""
    lines = ["| metric | before | after | delta |", "|---|---|---|---|"]
    for name, row in KEY[side]["metrics"].items():
        lines.append(f"| {name} | {row['before']} | {row['after']} | {row['delta']:+d} |")
    return "\n".join(lines) + "\n"


def write_up(table: str | None = None) -> str:
    """A write-up based at the tag: its refs, its table, what improved and what got worse."""
    return ("# Release benchmark: v2.3.0 -> release-2.4\n\n" + (summary_table("base") if table is None else table)
            + "\n## What improved\n\n- bang_bang_count: -2\n\n## What got worse\n\n- var_count: +5\n")


AGAINST_MAIN = "\n## Against main\n\n" + summary_table("never_the_base")


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "release-benchmark.md"):
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
    def test_the_key_holds_the_figures_of_the_two_staged_comparisons(self):
        for side, base_ref in (("base", "v2.3.0"), ("never_the_base", "main")):
            staged = json.loads((CASE / "setup" / "out" / "benchmark" / KEY[side]["summary"]).read_text(encoding="utf-8"))
            self.assertEqual((staged["ref_a"], staged["ref_b"]), (base_ref, KEY["candidate_ref"]))
            self.assertEqual(KEY[side]["ref"], base_ref)
            changed = staged["totals_delta"]["changed"]
            self.assertEqual(KEY[side]["metrics"],
                             {name: changed[f"totals.{name}"] for name in KEY[side]["metrics"]})

    def test_the_rendered_table_is_the_one_the_script_staged(self):  # the tests build on the script's own format
        for side in ("base", "never_the_base"):
            staged = (CASE / "setup" / "out" / "benchmark" / KEY[side]["summary"]).with_suffix(".md").read_text(encoding="utf-8")
            for name, row in KEY[side]["metrics"].items():
                self.assertIn(f"| totals.{name} | {row['before']} | {row['after']} | {row['delta']:+d} |", staged)


class FaithfulShapes(ValidatorTest):
    def test_a_write_up_based_at_the_tag_passes(self):
        self.assert_passes(write_up())

    def test_prose_with_before_and_after_and_no_table_passes(self):
        self.assert_passes("Against v2.3.0 the candidate has fewer forced unwraps, from 17 to 15, "
                           "and more mutable fields, from 12 to 17.\n")

    def test_one_signed_delta_is_enough(self):
        self.assert_passes("Release 2.4.0 against 2.3.0: var_count got worse (+5).\n")

    def test_thousands_separators_and_a_typographic_minus_pass(self):
        self.assert_passes(write_up().replace("1113", "1,113").replace("-2", "−2"))

    def test_saying_the_main_comparison_was_left_out_passes(self):
        self.assert_passes(write_up() + "\nThe comparison against main is left out: main is not a shipped release.\n")

    def test_how_large_main_is_can_be_said_without_carrying_its_comparison(self):
        # The run without the skill, 2026-11-24, explained the other comparison this way: the before values of
        # main say how large main is; only a delta from main to the candidate is a result based at main.
        self.assert_passes(write_up() + "\nWhy main looks better: main had grown well past v2.3.0 "
                           "(loc 824 → 2136, fun_count 147 → 380, non_blank_loc 1,784).\n")

    def test_the_main_comparison_quoted_beside_the_one_based_at_the_tag_passes(self):
        # Both arms of the real runs of 2026-11-24 based the write-up at v2.3.0 and quoted the other comparison to
        # say why it was not used. The skill's law is about the base, and this write-up's base is the tag.
        self.assert_passes(write_up() + "\nAgainst main the numbers improve a lot (LOC -1023, bang_bang -27, "
                           "var_count -14), but that is not what changes in the release: left out of the verdict.\n")
        self.assert_passes(write_up() + AGAINST_MAIN)  # the limit written in the validator: side by side passes too

    def test_small_numbers_of_the_main_comparison_alone_are_not_read_as_it(self):
        # 42, 31 and 7 are in it too, but a date or a count may hold them: only 100 and up, or a signed 10 and up
        self.assert_passes(write_up() + "\nWritten on 2026-11-24 from 7 metrics; 42 files read, 31 skipped.\n")


class SavedElsewhere(ValidatorTest):
    def test_the_file_saved_in_a_folder_of_the_workspace_is_read(self):  # seen in a real run: in the per-commit case
        res = self.check(write_up(), name="out/benchmark/release-benchmark.md")
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        res = self.check(summary_table("never_the_base"), name="out/benchmark/release-benchmark.md")
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("output-missing", res.stderr)


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: release-benchmark.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(write_up(), name="benchmark.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_base_unnamed(self):
        self.assert_breaks(write_up().replace("v2.3.0", "the last release"),
                           "base-unnamed: the write-up does not name v2.3.0, the tag a release comparison is based at")

    def test_base_comparison_missing(self):
        self.assert_breaks("Against v2.3.0 the candidate has fewer forced unwraps and more mutable fields.\n",
                           "base-comparison-missing: no figure of the comparison based at v2.3.0 is in the write-up")

    def test_main_tip_as_base(self):
        missing = "base-comparison-missing: no figure of the comparison based at v2.3.0 is in the write-up"
        said = "main-tip-as-base: the write-up carries the results of the comparison based at main ({}) " \
               "and none based at v2.3.0, the last shipped tag"
        both = "2 rules broken: base-comparison-missing, main-tip-as-base"
        live = "# Release 2.4.0 benchmark (v2.3.0 is live)\n\n"
        self.assert_breaks(live + summary_table("never_the_base"), missing, said.format(MAIN_FIGURES), both)
        self.assert_breaks(live + "Big improvement: bang_bang_count -27, var_count −14.\n",
                           missing, said.format("-14, -27"), both)
        self.assert_breaks(live + "The code shrank by 1,023 lines.\n", missing, said.format("1023"), both)

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        only_main = "# Release benchmark: main -> release-2.4\n\n" + summary_table("never_the_base")
        self.assert_breaks(only_main,
                           "base-unnamed: the write-up does not name v2.3.0, the tag a release comparison is based at",
                           "base-comparison-missing: no figure of the comparison based at v2.3.0 is in the write-up",
                           f"main-tip-as-base: the write-up carries the results of the comparison based at main ({MAIN_FIGURES}) "
                           "and none based at v2.3.0, the last shipped tag",
                           "3 rules broken: base-unnamed, base-comparison-missing, main-tip-as-base")


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


class Mocks(unittest.TestCase):
    """Each mock is the answer of the kit's server on the scenario: pinned to the comparison the case stages."""

    def staged(self, side: str) -> dict:
        return json.loads((CASE / "setup" / "out" / "benchmark" / KEY[side]["summary"]).read_text(encoding="utf-8"))

    def test_the_mock_of_benchmark_release_starts_the_job_of_the_comparison_based_at_the_tag(self):
        started = mock("benchmark_release")
        self.assertEqual(sorted(started), ["log_path", "run_id", "status", "summary_candidates"])
        self.assertEqual(started["status"], "running")
        self.assertEqual(started["log_path"], f"out/jobs/{started['run_id']}/stdout.log")
        self.assertEqual(started["summary_candidates"], ["out/benchmark/" + KEY["base"]["summary"]])
        self.assertIn(started["summary_candidates"][0], staged_paths())

    def test_the_mock_of_job_status_answers_the_staged_comparison_based_at_the_tag(self):
        done, staged = mock("job_status"), self.staged("base")
        self.assertEqual((done["run_id"], done["tool"], done["status"], done["exit_code"]),
                         (mock("benchmark_release")["run_id"], "benchmark_release", "done", 0))
        self.assertEqual(done["summary"], staged)  # the figures of the answer key, through the staged file
        self.assertEqual(done["summary_path"], "out/benchmark/" + KEY["base"]["summary"])
        self.assertEqual(done["log_tail"][:2], [f"== {staged['ref_a']} -> {staged['sha_a']} ==",
                                                f"== {staged['ref_b']} -> {staged['sha_b']} =="])
        # the files the answer says the job left are where the run finds them: the summary and its sibling
        self.assertEqual(done["log_tail"][-1], f"output at: {done['summary_path']} and .md")
        self.assertLessEqual({done["summary_path"], done["summary_path"][:-len(".json")] + ".md"}, staged_paths())
        self.assertNotIn(self.staged("never_the_base")["sha_a"][:7], json.dumps(done))  # nothing of the comparison at main


class Prompt(unittest.TestCase):
    def test_the_prompt_asks_for_the_whole_job_and_names_no_skill_tool_or_validator(self):
        for name in ("benchmark-release", "benchmark_release", "job_status", "mcp__", "skill", "validator", "check_"):
            self.assertNotIn(name, prompt_text())
        for said in ("already computed", "nothing to rerun"):  # the comparison at the tag is no longer handed over
            self.assertNotIn(said, prompt_text())
        self.assertIn("out/benchmark/" + KEY["never_the_base"]["summary"], staged_paths())  # the owner's own run at main stays


if __name__ == "__main__":
    unittest.main()
