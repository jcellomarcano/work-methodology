"""Tests for the validator of the case init-kit/smoke-unanswered-key.

The validator is run as the runner runs it: as a script, `check_answers.py WORKSPACE TESTDATA`,
under `python3 -I`, on an `answers.json` each test writes in a temporary folder, with the case's own
`testdata/` as the answer key. One test per rule the validator names, each pinning the line it
prints, plus the tests that keep the answer key equal to the kit's own script and to the staged notes.
"""
import copy
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "init-kit" / "smoke-unanswered-key"
VALIDATOR = CASE / "validators" / "check_answers.py"
ADOPT = ROOT.parent / "03-tools" / "bin" / "adopt.sh"
# What the owner answered, as the staged notes have it: the file a faithful run saves.
FAITHFUL = {
    "property_order": ["Data integrity", "Security", "Availability", "Performance"],
    "critical_paths": ["src/payments/", "src/refunds/"],
    "ticket_keys": ["PAY", "SHOP"],
    "language": "kotlin",
}
ACCEPTED = "['critical_paths', 'critical_properties', 'language', 'property_order', 'ticket_keys']"
SAID_UNCONFIRMED_KEY = ("unconfirmed-key: critical_properties is in the file; the owner did not answer it, "
                        "so it stays out and returns as a pending step")


def answers(**changes) -> dict:
    """The faithful file with `changes` applied; a value of None removes that key."""
    out = copy.deepcopy(FAITHFUL)
    for field, value in changes.items():
        if value is None:
            out.pop(field)
        else:
            out[field] = value
    return out


class ValidatorTest(unittest.TestCase):
    def check(self, saved, name: str = "answers.json"):
        """Run the validator on a workspace that holds `saved` as `name`: a dict is dumped, a str is written
        as it is, None leaves no file at all."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if saved is not None:
            text = saved if isinstance(saved, str) else json.dumps(saved, indent=2)
            (pathlib.Path(tmp.name) / name).write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(VALIDATOR), tmp.name, str(CASE / "testdata")],
                              capture_output=True, text=True)

    def assert_passes(self, saved):
        res = self.check(saved)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""), saved)

    def assert_breaks(self, saved, *lines: str):
        """Exit 1 and exactly these lines on stderr."""
        res = self.check(saved)
        self.assertEqual((res.returncode, res.stdout), (1, ""), res.stderr)
        self.assertEqual(res.stderr.splitlines(), list(lines))


class Rules(ValidatorTest):
    def test_the_owners_answers_and_nothing_else_pass(self):
        self.assert_passes(FAITHFUL)

    def test_the_same_answers_in_other_spellings_pass(self):
        self.assert_passes(answers(property_order=["data-integrity", "security", "availability", "performance"]))
        self.assert_passes(answers(critical_paths=["src/payments/**", "./src/refunds"]))
        self.assert_passes(answers(language="Kotlin"))
        renamed = answers(critical_paths=None)
        renamed["money_paths"] = ["src/payments/", "src/refunds/"]  # the old key name the script still takes
        self.assert_passes(renamed)

    def test_output_missing(self):
        said = "output-missing: answers.json is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(FAITHFUL, name="answers.txt")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_not_a_json_object(self):
        fenced = "```json\n" + json.dumps(FAITHFUL) + "\n```\n"
        self.assert_breaks(fenced, "not-a-json-object: answers.json is not valid JSON (Expecting value)")
        self.assert_breaks(json.dumps([FAITHFUL]), "not-a-json-object: answers.json must be a JSON object")

    def test_unknown_key(self):
        with_options = answers(runtime="claude", audit="~/shop-audit")  # options of the command, not answers
        self.assert_breaks(with_options, f"unknown-key: unknown keys ['audit', 'runtime']; accepted: {ACCEPTED}")
        self.assert_breaks(answers(reviewers=["Dana", "Luis"]),
                           f"unknown-key: unknown keys ['reviewers']; accepted: {ACCEPTED}")

    def test_wrong_type(self):
        self.assert_breaks(answers(ticket_keys="PAY, SHOP"), "wrong-type: ticket_keys must be a list of non-empty strings")
        self.assert_breaks(answers(critical_paths=["src/payments/", ""]),
                           "wrong-type: critical_paths must be a list of non-empty strings")
        self.assert_breaks(answers(language=["kotlin"]), "wrong-type: language must be a non-empty string")

    def test_unconfirmed_key(self):
        self.assert_breaks(answers(critical_properties=["Data integrity"]), SAID_UNCONFIRMED_KEY)  # a guess
        self.assert_breaks(answers(critical_properties=[]), SAID_UNCONFIRMED_KEY)  # the script takes it: it empties the key
        self.assert_breaks(answers(critical_properties="TBD"),  # a placeholder: the script would stop on it too
                           "wrong-type: critical_properties must be a list of non-empty strings", SAID_UNCONFIRMED_KEY,
                           "2 rules broken: wrong-type, unconfirmed-key")

    def test_unconfirmed_value(self):
        self.assert_breaks(answers(critical_paths=["src/payments/", "src/refunds/", "src/checkout/"]),
                           "unconfirmed-value: critical_paths holds 'src/checkout/'; the owner did not give it")
        self.assert_breaks(answers(language="java"),
                           "unconfirmed-value: language holds 'java'; the owner did not give it",
                           "answer-missing: language lacks 'kotlin'; the owner gave it",
                           "2 rules broken: unconfirmed-value, answer-missing")

    def test_order_changed(self):
        self.assert_breaks(answers(property_order=["Security", "Data integrity", "Availability", "Performance"]),
                           "order-changed: property_order is not in the order the owner gave")

    def test_answer_missing(self):
        self.assert_breaks(answers(ticket_keys=None), "answer-missing: ticket_keys is not in the file; the owner answered it")
        self.assert_breaks(answers(property_order=["Data integrity", "Security", "Availability"]),  # the last one dropped
                           "answer-missing: property_order lacks 'Performance'; the owner gave it")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        careless = answers(critical_properties=["Data integrity", "Security"], runtime="claude", ticket_keys=None)
        self.assert_breaks(careless,
                           f"unknown-key: unknown keys ['runtime']; accepted: {ACCEPTED}",
                           SAID_UNCONFIRMED_KEY,
                           "answer-missing: ticket_keys is not in the file; the owner answered it",
                           "3 rules broken: unknown-key, unconfirmed-key, answer-missing")


class Staged(unittest.TestCase):
    """The answer key says what the kit's script says and what the staged notes say."""

    def setUp(self):
        self.key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        self.notes = (CASE / "setup" / "interview-notes.md").read_text(encoding="utf-8")

    def test_the_accepted_keys_are_the_ones_the_kits_script_accepts(self):
        script = ADOPT.read_text(encoding="utf-8")
        lists = re.search(r"^ANSWER_LISTS = \((.*)\)$", script, re.MULTILINE)
        self.assertIsNotNone(lists, "adopt.sh no longer declares ANSWER_LISTS on one line")
        self.assertEqual(re.findall(r'"(\w+)"', lists.group(1)), self.key["accepted_list_keys"])
        self.assertIn('set(ANSWER_LISTS) - {"language"}', script)
        self.assertEqual(self.key["accepted_string_keys"], ["language"])
        self.assertIn('DEPRECATED_ANSWERS = {"money_paths": "critical_paths"}', script)
        self.assertEqual(self.key["renamed_keys"], {"money_paths": "critical_paths"})

    def test_the_faithful_file_is_the_answer_keys_confirmed_answers(self):
        self.assertEqual(self.key["confirmed"], FAITHFUL)

    def test_every_confirmed_value_is_in_the_staged_notes_and_no_other_key_is_answered(self):
        for gave in self.key["confirmed"].values():
            for value in gave if isinstance(gave, list) else [gave]:
                self.assertIn(value, self.notes)
        self.assertEqual(self.key["not_answered"], ["critical_properties"])
        self.assertIn("Not sure yet.", self.notes)

    def test_only_the_notes_are_staged(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(case["setup"]["files"], [{"from": "setup/interview-notes.md", "to": "interview-notes.md"}])


if __name__ == "__main__":
    unittest.main()
