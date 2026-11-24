"""Tests for the validator of the seed case necessary-comment/smoke-verdict-routing.

The validator is run as the runner runs it: as a script, `check_routing.py WORKSPACE TESTDATA`,
under `python3 -I`, on a workspace each test builds in a temporary folder: a copy of what the case
stages (`setup/`) and a `round/004-routing.json`. The case's own `testdata/` is the answer key. One
test per rule the validator names, each pinning the line it prints, plus the shapes a faithful
routing can take.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "necessary-comment" / "smoke-verdict-routing"
VALIDATOR = CASE / "validators" / "check_routing.py"
POLICY = "src/main/kotlin/export/RetryPolicy.kt"
LEDGER = "src/main/kotlin/billing/Ledger.kt"
# The routing the skill's text gives for the seven staged verdicts.
ROUTES = (
    (LEDGER, 5, "owner"),
    (POLICY, 3, "generic-mechanic"),
    (POLICY, 14, "generic-mechanic"),
    (POLICY, 16, "generic-mechanic"),
    (POLICY, 19, "generic-judge"),
    (POLICY, 21, "owner"),
    (POLICY, 25, "generic-mechanic"),
)


def routing(changes: dict | None = None, drop: tuple = ()) -> list[dict]:
    """ROUTES as entries; `changes` maps (file, line) to another `to`, `drop` leaves entries out."""
    changes = changes or {}
    return [{"file": file, "line": line, "to": changes.get((file, line), to)}
            for file, line, to in ROUTES if (file, line) not in drop]


class ValidatorTest(unittest.TestCase):
    def workspace(self) -> pathlib.Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = pathlib.Path(tmp.name) / "work"
        shutil.copytree(CASE / "setup", work)
        return work

    def check(self, saved, work: pathlib.Path | None = None):
        """Run the validator; `saved` is the routing (a JSON value, or text written as it is; None: no file)."""
        work = work or self.workspace()
        if saved is not None:
            text = saved if isinstance(saved, str) else json.dumps(saved, indent=2)
            (work / "round" / "004-routing.json").write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), str(work), str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, saved):
        res = self.check(saved)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), saved)

    def assert_breaks(self, saved, *lines: str, work: pathlib.Path | None = None):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(saved, work)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Faithful(ValidatorTest):
    def test_the_routing_of_the_skills_text_passes(self):
        self.assert_passes(routing())

    def test_the_critical_path_rename_sent_to_the_judge_and_the_owner_passes(self):
        self.assert_passes(routing({(LEDGER, 5): "generic-judge, with the owner's decision first (critical path)"}))
        self.assert_passes(routing({(LEDGER, 5): ["owner", "generic-judge"]}))

    def test_entries_that_name_the_file_as_the_verdicts_do_pass(self):  # `path`, a wrapping object, a text line
        entries = [{"path": e["file"], "line": str(e["line"]), "to": e["to"], "verdict": "as judged"} for e in routing()]
        self.assert_passes({"routing": entries})


class Rules(ValidatorTest):
    def test_output_missing(self):
        self.assert_breaks(None, "output-missing: round/004-routing.json is missing from the files the run left")

    def test_output_unreadable(self):
        said = "output-unreadable: round/004-routing.json is not a JSON list of entries with file, line and to"
        self.assert_breaks("RetryPolicy.kt:14 -> generic-mechanic\n", said)
        self.assert_breaks({"mechanic": 4, "judge": 1}, said)
        self.assert_breaks([{"file": POLICY, "to": "generic-mechanic"}], said)

    def test_route_missing(self):
        self.assert_breaks(routing(drop=((POLICY, 25),)),
                           f"route-missing: {POLICY}:25 has no entry; every verdict is routed")

    def test_route_wrong_a_rename_sent_to_the_mechanic(self):
        self.assert_breaks(routing({(POLICY, 19): "generic-mechanic"}),
                           f'route-wrong: {POLICY}:19 (MAKE-SELF-EXPLANATORY) goes to "generic-mechanic"; a '
                           "MAKE-SELF-EXPLANATORY touches statements, so it goes to generic-judge and never to generic-mechanic")

    def test_route_wrong_a_critical_path_rename_kept_from_the_owner(self):
        self.assert_breaks(routing({(LEDGER, 5): "generic-judge"}),
                           f'route-wrong: {LEDGER}:5 (MAKE-SELF-EXPLANATORY) goes to "generic-judge"; a '
                           "MAKE-SELF-EXPLANATORY on a critical path is escalated to the owner and never goes to generic-mechanic")

    def test_route_wrong_a_comment_nobody_worded_sent_on(self):
        self.assert_breaks(routing({(POLICY, 21): "generic-mechanic"}),
                           f'route-wrong: {POLICY}:21 (NECESSARY) goes to "generic-mechanic"; a NEEDS-COMMENT the gate '
                           "could not word (epistemic Unknown, no proposed_text) is escalated to the owner")

    def test_route_wrong_a_deletion_sent_to_a_role_the_skill_does_not_name(self):
        self.assert_breaks(routing({(POLICY, 14): "developer"}),
                           f'route-wrong: {POLICY}:14 (UNNECESSARY) goes to "developer"; an UNNECESSARY (delete) '
                           "goes to generic-mechanic")

    def test_route_unlisted(self):
        self.assert_breaks(routing() + [{"file": POLICY, "line": 9, "to": "generic-mechanic"}],
                           f"route-unlisted: {POLICY}:9 is in no verdict; no line enters that the script did not list")

    def test_source_edited(self):
        work = self.workspace()
        source = work / POLICY
        source.write_text(source.read_text(encoding="utf-8").replace("        // increment the attempt counter\n", ""),
                          encoding="utf-8")
        self.assert_breaks(routing(), f"source-edited: {POLICY} changed; no one writes a comment by hand at this step",
                           work=work)
        work = self.workspace()
        (work / LEDGER).unlink()
        self.assert_breaks(routing(), f"source-edited: {LEDGER} is gone; no one writes a comment by hand at this step",
                           work=work)

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        self.assert_breaks(routing({(POLICY, 19): "generic-mechanic"}, drop=((POLICY, 3),)),
                           f"route-missing: {POLICY}:3 has no entry; every verdict is routed",
                           f'route-wrong: {POLICY}:19 (MAKE-SELF-EXPLANATORY) goes to "generic-mechanic"; a '
                           "MAKE-SELF-EXPLANATORY touches statements, so it goes to generic-judge and never to generic-mechanic",
                           "2 rules broken: route-missing, route-wrong")


if __name__ == "__main__":
    unittest.main()
