"""lib/brief_check.py: the goal contract of a brief (04-templates/brief.md,
agent-protocol.md section 1) is checked by script. The template itself
passes; a missing, empty or misplaced field fails; SPECS entries must be
S# references with the task-document path, never a paraphrase; BUDGET
carries a number; the same brief gives the same bytes and exit code."""
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

SCRIPT = TOOLS_ROOT / "lib" / "brief_check.py"
TEMPLATE = KIT_ROOT / "04-templates" / "brief.md"
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


if __name__ == "__main__":
    unittest.main()
