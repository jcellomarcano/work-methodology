"""lib/brief_check.py: the goal contract of a brief (04-templates/brief.md,
agent-protocol.md section 1) is checked by script. The template itself
passes; a missing, empty or misplaced field fails; SPECS entries must be
S# references with the task-document path, never a paraphrase; BUDGET
carries a number; the same brief gives the same bytes and exit code.
The goal rule (methodology.md paragraph 9) adds: a specialised ROLE, a
one-sentence OBJECTIVE, INPUTS that are paths, a bounded brief; and the
JSON schema of the brief requires the same twelve fields."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
KIT_ROOT = TOOLS_ROOT.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import brief_check  # noqa: E402
from lib import findings_schema_validator as fsv  # noqa: E402

SCRIPT = TOOLS_ROOT / "lib" / "brief_check.py"
TEMPLATE = KIT_ROOT / "04-templates" / "brief.md"
ROSTER = KIT_ROOT / "01-roles" / "agents"
SCHEMA = TOOLS_ROOT / "schemas" / "brief.schema.json"
ORDER = ["ROLE", "OBJECTIVE", "SPECS", "ACCEPTANCE", "INPUTS", "SCOPE", "ALREADY READ",
         "CONSTRAINTS", "OUTPUT", "STOP", "BUDGET", "EVIDENCE"]

VALID = """ROLE: generic-proposer
OBJECTIVE: lib/brief_check.py exits 0 on 04-templates/brief.md.
SPECS: odd/tasks/delegation-context.md#S4
ACCEPTANCE: cd 03-tools && python3 -m unittest tests.test_brief_check
INPUTS:
  - 04-templates/brief.md
SCOPE: 03-tools/lib/brief_check.py, 03-tools/tests/test_brief_check.py
ALREADY READ: odd/research/context/context-method.md:52-66 (the goal contract table)
CONSTRAINTS: stdlib only; never touch the router files
OUTPUT: proposer-output; JSON only
STOP: acceptance passes, a budget deny, or a blocking unknown
BUDGET: max_context_tokens=60000; max_tool_calls=40
EVIDENCE: cite the statement at file:line@sha; tag every claim
"""


def without(text: str, field: str) -> str:
    """Drops the field's header line and its indented continuation lines."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith(field + ":"):
            skipping = True
            continue
        if skipping and line[:1] in (" ", "\t"):
            continue
        skipping = False
        out.append(line)
    return "".join(out)


def replace_field(text: str, field: str, value: str) -> str:
    lines = without(text, field).splitlines(keepends=True)
    index = ORDER.index(field)
    at = len(lines)
    for i, line in enumerate(lines):
        name = line.split(":", 1)[0]
        if name in ORDER and ORDER.index(name) > index:
            at = i
            break
    lines.insert(at, f"{field}: {value}\n" if value else f"{field}:\n")
    return "".join(lines)


class BriefCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brief-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def check(self, text):
        return brief_check.check(text)

    def run_cli(self, text=None, path=None):
        if path is None:
            path = self.tmp / "brief.md"
            path.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=60)

    def test_field_order_is_the_goal_contract(self):
        self.assertEqual(list(brief_check.FIELDS), ORDER)

    def test_the_template_itself_passes(self):
        result = self.check(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "PASS", result)
        proc = self.run_cli(path=TEMPLATE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["verdict"], "PASS")

    def test_a_valid_brief_passes(self):
        result = self.check(VALID)
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["empty"], [])
        self.assertEqual(result["specs_invalid"], [])

    def test_each_missing_field_fails(self):
        for field in ORDER:
            with self.subTest(field=field):
                result = self.check(without(VALID, field))
                self.assertEqual(result["verdict"], "FAIL")
                self.assertEqual(result["missing"], [field])
                proc = self.run_cli(without(VALID, field))
                self.assertEqual(proc.returncode, 1)

    def test_each_empty_field_fails(self):
        for field in ORDER:
            with self.subTest(field=field):
                result = self.check(replace_field(VALID, field, ""))
                self.assertEqual(result["verdict"], "FAIL")
                self.assertIn(field, result["empty"])

    def test_a_field_out_of_order_fails(self):
        swapped = VALID.replace("ROLE: generic-proposer\n", "") + "ROLE: generic-proposer\n"
        result = self.check(swapped)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["out_of_order"], ["ROLE"])

    def test_a_duplicated_field_fails(self):
        result = self.check(VALID + "STOP: again\n")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["duplicate"], ["STOP"])

    def test_paraphrase_only_specs_fail(self):
        result = self.check(replace_field(VALID, "SPECS", "implement the context method of the research"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["specs_invalid"], [{"entry": "implement the context method of the research",
                                                    "problems": ["no_id", "no_path"]}])

    def test_specs_need_both_the_id_and_the_path(self):
        cases = {
            "S4": ["no_path"],
            "odd/tasks/delegation-context.md": ["no_id"],
            "odd/tasks/delegation-context.md#S4 context method": ["paraphrase"],
            "S4 Context method. Implement WU5-WU17": ["no_path"],
        }
        for entry, problems in cases.items():
            with self.subTest(entry=entry):
                result = self.check(replace_field(VALID, "SPECS", entry))
                self.assertEqual(result["verdict"], "FAIL")
                self.assertEqual(result["specs_invalid"], [{"entry": entry, "problems": problems}])

    def test_several_spec_references_pass_as_a_list_or_inline(self):
        inline = replace_field(VALID, "SPECS", "odd/tasks/a.md#S1, odd/tasks/a.md#S3")
        listed = replace_field(VALID, "SPECS", "\n  - odd/tasks/a.md#S1\n  - odd/tasks/b.md#S12").replace("SPECS: \n", "SPECS:\n")
        for text in (inline, listed):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)["verdict"], "PASS", self.check(text))

    def test_one_bad_entry_among_good_ones_fails(self):
        result = self.check(replace_field(VALID, "SPECS", "odd/tasks/a.md#S1, the done gate"))
        self.assertEqual(result["specs_invalid"], [{"entry": "the done gate", "problems": ["no_id", "no_path"]}])

    def test_budget_without_a_number_fails(self):
        result = self.check(replace_field(VALID, "BUDGET", "from the contract"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["budget_without_number"])
        self.assertFalse(self.check(VALID)["budget_without_number"])

    def test_the_fenced_template_layout_is_read(self):
        fenced = "# Brief\n\n```\n" + VALID + "```\n\nRules: prose after the fence is not a field.\n"
        self.assertEqual(self.check(fenced)["verdict"], "PASS", self.check(fenced))

    def test_determinism_same_brief_same_bytes(self):
        bad = without(replace_field(VALID, "SPECS", "the method"), "STOP")
        first, second = self.run_cli(bad), self.run_cli(bad)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.returncode, second.returncode)
        self.assertEqual(first.returncode, 1)
        self.assertEqual(json.loads(first.stdout), json.loads(json.dumps(json.loads(first.stdout), sort_keys=True)))

    def test_an_unreadable_brief_exits_2(self):
        proc = self.run_cli(path=self.tmp / "absent.md")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stderr))


class GoalRuleTests(unittest.TestCase):
    """methodology.md paragraph 9: every launched agent carries a goal, a
    specific role and a bounded context. One test per rule, plus the proof
    that a brief valid before the rule is still valid."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brief-goal-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_valid_brief_trips_no_goal_rule(self):
        result = brief_check.check(VALID, roster=brief_check.roster_names(ROSTER))
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertFalse(result["role_general_purpose"])
        self.assertFalse(result["role_unknown"])
        self.assertFalse(result["objective_not_one_sentence"])
        self.assertEqual(result["inputs_not_paths"], [])
        self.assertFalse(result["too_long"])

    def test_the_template_passes_against_the_roster(self):
        result = brief_check.check(TEMPLATE.read_text(encoding="utf-8"), roster=brief_check.roster_names(ROSTER))
        self.assertEqual(result["verdict"], "PASS", result)

    def test_a_general_purpose_role_fails(self):
        for role in ("general-purpose", "General Purpose agent", "generic agent", "assistant", "agent", "default"):
            with self.subTest(role=role):
                result = brief_check.check(replace_field(VALID, "ROLE", role))
                self.assertEqual(result["verdict"], "FAIL")
                self.assertTrue(result["role_general_purpose"])

    def test_a_role_outside_the_roster_needs_an_explicit_model(self):
        roster = brief_check.roster_names(ROSTER)
        self.assertIn("generic-proposer", roster)
        unknown = brief_check.check(replace_field(VALID, "ROLE", "payments-mapper"), roster=roster)
        self.assertEqual(unknown["verdict"], "FAIL")
        self.assertTrue(unknown["role_unknown"])
        adhoc = brief_check.check(replace_field(VALID, "ROLE", "payments-mapper model=sonnet"), roster=roster)
        self.assertEqual(adhoc["verdict"], "PASS", adhoc)
        self.assertFalse(brief_check.check(replace_field(VALID, "ROLE", "payments-mapper"))["role_unknown"])

    def test_an_objective_of_several_sentences_fails(self):
        for objective in ("Map the payments module. Also fix the flaky test.",
                          "Map the payments module\n  and then refactor it"):
            with self.subTest(objective=objective):
                result = brief_check.check(replace_field(VALID, "OBJECTIVE", objective))
                self.assertEqual(result["verdict"], "FAIL")
                self.assertTrue(result["objective_not_one_sentence"])

    def test_inputs_are_paths_never_prose(self):
        result = brief_check.check(replace_field(VALID, "INPUTS", "\n  - 04-templates/brief.md\n  - the code we discussed earlier").replace("INPUTS: \n", "INPUTS:\n"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["inputs_not_paths"], ["the code we discussed earlier"])
        for entry in ("/abs/repo (read-only)", "~/notes/x.md", "round/003-handoff.json", "engram:metodo/receipt/abc123", "README.md"):
            with self.subTest(entry=entry):
                self.assertEqual(brief_check.check(replace_field(VALID, "INPUTS", entry))["inputs_not_paths"], [])

    def test_a_brief_that_pastes_content_fails(self):
        pasted = "".join(f"  line {n} of a pasted file\n" for n in range(brief_check.MAX_LINES))
        result = brief_check.check(VALID.replace("CONSTRAINTS:", "CONSTRAINTS: see below\n" + pasted + "CONSTRAINTS_END:", 1))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["too_long"])

    def test_none_declares_an_absent_spec_but_an_empty_field_still_fails(self):
        for field in ("SPECS", "ALREADY READ"):
            with self.subTest(field=field):
                self.assertEqual(brief_check.check(replace_field(VALID, field, "none"))["verdict"], "PASS")
                self.assertEqual(brief_check.check(replace_field(VALID, field, ""))["verdict"], "FAIL")

    def test_text_outside_the_fields_counts_against_the_bound(self):
        # a pasted file after the brief must not ride past the launch gate
        self.assertTrue(brief_check.check(VALID + "".join(f"pasted line {n}\n" for n in range(100)))["too_long"])
        self.assertTrue(brief_check.check("".join(f"pasted line {n}\n" for n in range(100)) + VALID)["too_long"])
        self.assertTrue(brief_check.check(VALID + "x" * (brief_check.MAX_CHARS + 1) + "\n")["too_long"])
        self.assertFalse(brief_check.check(VALID + "\nRules: a short note after the brief.\n")["too_long"])

    def test_abbreviations_and_quotes_do_not_split_the_objective(self):
        for objective in ("The mapper lists every module, e.g. App and Core, with its LOC.",
                          "The adapter runs on one runtime, i.e. Claude Code, end to end.",
                          "The report compares Kit vs. Baseline on recall.",
                          "The prompt 'Proceed? Yes' is answered by the script."):
            with self.subTest(objective=objective):
                result = brief_check.check(replace_field(VALID, "OBJECTIVE", objective))
                self.assertFalse(result["objective_not_one_sentence"])
                self.assertEqual(result["verdict"], "PASS", result)

    def test_inputs_accept_the_paths_people_write(self):
        for entry in ("`03-tools/lib/x.py`", '"docs/a b.md"', "Makefile", ".gitignore", "$HOME/notes/x.md", "**/*.py", "none"):
            with self.subTest(entry=entry):
                self.assertEqual(brief_check.check(replace_field(VALID, "INPUTS", entry))["inputs_not_paths"], [])
        self.assertEqual(brief_check.check(replace_field(VALID, "INPUTS", "whatever seems relevant"))["inputs_not_paths"],
                         ["whatever seems relevant"])

    def test_a_note_beside_the_role_does_not_hide_the_role(self):
        roster = brief_check.roster_names(ROSTER)
        for role in ("generic-proposer # the writer", "generic-proposer - writes the card", "generic-proposer, the writer",
                     "`generic-proposer`", "payments-mapper model = sonnet"):
            with self.subTest(role=role):
                result = brief_check.check(replace_field(VALID, "ROLE", role), roster=roster)
                self.assertEqual(result["verdict"], "PASS", result)
        self.assertTrue(brief_check.check(replace_field(VALID, "ROLE", "general-purpose # anything"))["role_general_purpose"])

    def test_the_tolerances_do_not_open_false_passes(self):
        for objective in ("The hook's deny works in block mode. The checker's verdict holds for every role.",
                          "Map the hooks, tools, etc. Then fix the docs lint."):
            with self.subTest(objective=objective):
                self.assertTrue(brief_check.check(replace_field(VALID, "OBJECTIVE", objective))["objective_not_one_sentence"])
        for entry in ('"the hooks folder and anything related"', "everything", "`whatever seems relevant`"):
            with self.subTest(entry=entry):
                self.assertEqual(brief_check.check(replace_field(VALID, "INPUTS", entry))["inputs_not_paths"], [entry])
        for entry in ("Dockerfile", "LICENSE", "'docs/a b.md' (the spec)"):
            with self.subTest(entry=entry):
                self.assertEqual(brief_check.check(replace_field(VALID, "INPUTS", entry))["inputs_not_paths"], [])

    def test_the_cli_takes_the_roster_directory(self):
        path = self.tmp / "brief.md"
        path.write_text(replace_field(VALID, "ROLE", "payments-mapper"), encoding="utf-8")
        argv = [sys.executable, str(SCRIPT), str(path)]
        self.assertEqual(subprocess.run(argv, capture_output=True, text=True, timeout=60).returncode, 0)
        proc = subprocess.run(argv + ["--roster", str(ROSTER)], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(json.loads(proc.stdout)["role_unknown"])


class BriefSchemaTests(unittest.TestCase):
    """schemas/brief.schema.json is the JSON form of the same goal contract:
    it requires the twelve fields the checker requires, in the same order."""

    DOC = {"ROLE": "generic-proposer", "OBJECTIVE": "x", "SPECS": ["odd/tasks/p1.md#S1"], "ACCEPTANCE": "python3 -m unittest",
           "INPUTS": ["README.md"], "SCOPE": ["lib/**"], "ALREADY READ": [], "CONSTRAINTS": [], "OUTPUT": "x", "STOP": "x",
           "BUDGET": {"max_context_tokens": 1, "max_tool_calls": 1}, "EVIDENCE": "x"}

    def schema(self):
        return json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_the_schema_requires_the_checker_fields_in_order(self):
        self.assertEqual(self.schema()["required"], list(brief_check.FIELDS))
        self.assertEqual(fsv.validate(self.DOC, self.schema())["verdict"], "PASS")
        # the FAIL without the four goal fields is pinned in tests/test_findings_schema_validator.py


if __name__ == "__main__":
    unittest.main()
