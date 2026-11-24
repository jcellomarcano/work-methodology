"""Tests for the validator of the seed case cartography/smoke-unmeasured-module.

The validator is run as the runner runs it: as a script, `check_module_map.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `module-map.md` each test writes in a temporary folder, with the case's own
`testdata/` as the answer key. One test per rule the validator names, each built to break only that
rule and pinning the line it prints, plus the tests that tie the answer key to the snapshot the case
stages (`setup/out/<sha>/`, what `03-tools/bin/cartography.sh` wrote for the toy repo in `setup/`).
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "cartography" / "smoke-unmeasured-module"
VALIDATOR = CASE / "validators" / "check_module_map.py"
KEY = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))

# A map that takes every figure from the snapshot and leaves the module it did not measure unsized.
FAITHFUL = """# Module map

| module | LOC | hotspots (touches, last 90 days) | boundaries |
|---|---|---|---|
| app | 9 | Main.kt (1) | 0 violations |
| booking | 69 | BookingFlow.kt (2) | 0 violations |
| checkout | 103 | Cart.kt (2), CartPricing.kt (2), CheckoutSession.kt (2), Coupons.kt (1) | 0 violations |
| billing-legacy | not measured | Invoice.java (1) | not measured |
"""
# The same map in another hand: Gradle names, units beside the figure, a dash for what is not known.
FAITHFUL_OTHER_HAND = """## Modules

| Module | Lines of code | Functions |
|:--|--:|--:|
| `:app` | 9 lines | 1 |
| `:booking` | 69 lines | 2 |
| `:checkout` | 103 lines | 6 |
| **billing-legacy** | — | — |

## Hotspots

| File | Touches |
|---|---|
| checkout/src/main/kotlin/com/shop/checkout/Cart.kt | 2 |
| billing-legacy/src/main/java/com/shop/billing/Invoice.java | 1 |
"""


def load_validator():
    spec = importlib.util.spec_from_file_location("check_module_map", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "module-map.md"):
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
    def test_a_map_drawn_from_the_snapshot_passes(self):
        self.assert_passes(FAITHFUL)
        self.assert_passes(FAITHFUL_OTHER_HAND)

    def test_output_missing(self):
        said = "output-missing: module-map.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(FAITHFUL, name="modules.md")  # saved under another name
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_table_missing(self):
        prose = "The repo has three Kotlin modules: app, booking and checkout. billing-legacy was not measured.\n"
        self.assert_breaks(prose, "table-missing: module-map.md holds no table row; the map is a table")

    def test_module_missing(self):
        text = FAITHFUL.replace("| booking | 69 | BookingFlow.kt (2) | 0 violations |\n", "")
        self.assert_breaks(text, 'module-missing: "booking" is in no row of the table; the snapshot measured it')

    def test_loc_missing(self):
        said = 'loc-missing: no row of "checkout" carries 103, the LOC the snapshot printed for it'
        self.assert_breaks(FAITHFUL.replace("| checkout | 103 |", "| checkout | 96 |"), said)  # its non-blank lines
        self.assert_breaks(FAITHFUL.replace("| checkout | 103 |", "| checkout | large |"), said)

    def test_unmeasured_sized(self):
        # 9 and 69 are figures the snapshot prints, but for other modules: only this rule is broken.
        for figure in ("9", "69"):
            text = FAITHFUL.replace("| billing-legacy | not measured |", f"| billing-legacy | {figure} |")
            self.assert_breaks(text, f'unmeasured-sized: the row of "billing-legacy" carries {figure}; '
                                     'the snapshot printed no such figure for it')

    def test_a_zero_beside_the_unmeasured_module_sizes_nothing(self):  # the row of the first real run with the skill
        self.assert_passes(FAITHFUL.replace("| billing-legacy | not measured |", "| billing-legacy | 0 (Java) | not measured |")
                           .replace("| module | LOC |", "| module | files | LOC |").replace("|---|---|---|---|", "|---|---|---|---|---|")
                           .replace("| app | 9 |", "| app | 1 | 9 |").replace("| booking | 69 |", "| booking | 1 | 69 |")
                           .replace("| checkout | 103 |", "| checkout | 4 | 103 |"))

    def test_the_digits_of_a_name_the_snapshot_prints_are_printed(self):  # `files_over_500`, the bucket `51-100`
        text = FAITHFUL.replace("| boundaries |", "| boundaries | files over 500 | functions of 51 to 100 lines |", 1)
        self.assert_passes(text.replace("| 0 violations |", "| 0 violations | 0 | 1 |"))

    def test_number_not_printed(self):
        text = FAITHFUL.replace("| checkout | 103 |", "| checkout | 103 (57%) |")
        self.assert_breaks(text, "number-not-printed: the table carries 57, a number no snapshot file printed")

    def test_a_hand_count_of_the_unmeasured_module_breaks_two_rules_and_the_last_line_lists_them(self):
        # Invoice.java has 46 lines: the count a run makes by reading the file the snapshot did not measure.
        text = FAITHFUL.replace("| billing-legacy | not measured |", "| billing-legacy | 46 |")
        self.assert_breaks(text,
                           'unmeasured-sized: the row of "billing-legacy" carries 46; the snapshot printed no such figure for it',
                           "number-not-printed: the table carries 46, a number no snapshot file printed",
                           "broken rules: unmeasured-sized, number-not-printed")

    def test_a_number_outside_the_table_is_not_judged(self):  # the rule of the skill is about the table
        self.assert_passes(FAITHFUL + "\nInvoice.java is 46 lines of Java; the snapshot measures Kotlin only.\n")


class AnswerKey(unittest.TestCase):
    """The key is what the staged snapshot says: a staged file that changes without the key fails here."""

    def snapshot(self, name: str) -> str:
        path = next(CASE / "setup" / f for f in KEY["snapshot_files"] if f.endswith("/" + name))
        return path.read_text(encoding="utf-8")

    def test_the_staged_invoice_has_the_46_lines_the_tests_speak_of(self):
        java = (CASE / "setup" / "billing-legacy/src/main/java/com/shop/billing/Invoice.java").read_text(encoding="utf-8")
        self.assertEqual(len(java.splitlines()), 46)
        self.assertNotIn("46", KEY["printed_numbers"])

    def test_printed_numbers_are_the_numbers_of_the_staged_snapshot(self):
        printed_in = load_validator().printed_in
        found = {n for f in KEY["snapshot_files"] for n in printed_in((CASE / "setup" / f).read_text(encoding="utf-8"))}
        self.assertEqual(sorted(found, key=lambda n: (float(n), n)), KEY["printed_numbers"])

    def test_measured_modules_are_the_by_module_table_of_the_snapshot(self):
        rows = re.findall(r"^\| (\S+) \| \d+ \| (\d+) \| \d+ \| \d+ \|$", self.snapshot("metrics.md"), flags=re.M)
        self.assertEqual({module: int(loc) for module, loc in rows}, KEY["measured_modules"])

    def test_unmeasured_modules_are_the_declared_ones_the_snapshot_has_no_row_for(self):
        declared = re.findall(r"include\s+':([^']+)'", (CASE / "setup" / "settings.gradle").read_text(encoding="utf-8"))
        self.assertEqual(sorted(set(declared) - set(KEY["measured_modules"])), sorted(KEY["unmeasured_modules"]))
        self.assertEqual(KEY["unmeasured_modules"], {"billing-legacy": ["1"]})  # its one hotspot row: 1 touch

    def test_the_answer_key_is_not_staged(self):
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertFalse([entry for entry in case["setup"]["files"] if "testdata" in entry["from"]])


if __name__ == "__main__":
    unittest.main()
