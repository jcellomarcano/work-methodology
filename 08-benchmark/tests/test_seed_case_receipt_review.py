"""Tests for the validator of the seed case receipt-review/smoke-tier-frozen.

The validator is run as the runner runs it: as a script, `check_context.py WORKSPACE TESTDATA`,
under `python3 -I`, on a `round/000-context.md` each test builds in a temporary folder and with
the case's own `testdata/` as the answer key. One test per rule the validator names, each pinning
the line it prints. One test holds the answer key against the receipt the case stages, which is
real output of the kit's `receipt_start`, so the key cannot drift from what the run is given.

The scenario begins with the receipt already open, so the receipt is staged where the tool wrote it,
`out/rdd/<tree_sha>.receipt.json`, and the two tools that only read are mocked: `receipt_status` and
`test_sectors` (with the base branch). Each mock is what the kit's tool answered, through the kit's
MCP server, on a scratch repository with the one-line change committed and that receipt open; the
`round_dir` alone is relabeled, in the receipt and in the mock, from the scratch repository's path
on the machine that built it to `/srv/build/rounds/book-118`.
`receipt_start` has no mock: it writes the receipt, and with it what `receipt_status` answers.
`route` and the tools that capture, acknowledge or finalize have none either: their answers depend
on what the run does.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE = ROOT / "evals" / "receipt-review" / "smoke-tier-frozen"
VALIDATOR = CASE / "validators" / "check_context.py"
MOCKS = CASE / "mocks" / "metodo"
TREE = "91e44612455fda0ed399b94932a21737d92d348b"
COMMIT = "bd39844c82241430923671484b957df54cdc8bac"
STAGED_RECEIPT = f"out/rdd/{TREE}.receipt.json"  # where the tool writes it, under its own folder
ROUND_DIR = "/srv/build/rounds/book-118"  # the label of the scratch repository's round folder, not a path of this machine
ALL_LENSES = "flujo-critico, jamas-peor-que-antes, tests-anti-flake, simplicidad"

RISK = "RISK: high (touches critical_paths: booking/SeatHold.kt)"
LENSES = f"LENSES: {ALL_LENSES}"
RECEIPT = f"RECEIPT: out/rdd/{TREE}.receipt.json"
FROZEN = 'the script derived "high" and the tier stays frozen'
TIED = "the receipt is tied to the tree, not the commit"


def context(risk: str | None = RISK, lenses: str | None = LENSES, receipt: str | None = RECEIPT, more: str = "") -> str:
    """The round context with the three lines the skill pastes; None leaves a line out."""
    lines = ["# Round context: BOOK-118", "", "CHANGE CARD: round/001-card.md", risk, lenses, receipt, more]
    return "\n".join(line for line in lines if line is not None) + "\n"


class ValidatorTest(unittest.TestCase):
    def check(self, text: str | None, name: str = "round/000-context.md"):
        """Run the validator on a workspace that holds `text` saved as `name` (None: no file at all)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if text is not None:
            path = pathlib.Path(tmp.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
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


class Faithful(ValidatorTest):
    def test_the_context_these_tests_build_on_passes(self):
        self.assert_passes(context())

    def test_labels_in_bold_or_in_a_list_pass(self):
        self.assert_passes(context(risk="- **RISK:** high", lenses=f"- **LENSES**: {ALL_LENSES}",
                                   receipt=f"- `RECEIPT:` out/rdd/{TREE}.receipt.json"))

    def test_a_value_laid_out_on_the_lines_under_its_label_passes(self):
        listed = "LENSES:\n- flujo-critico\n- jamas-peor-que-antes\n- tests-anti-flake\n- simplicidad"
        self.assert_passes(context(risk="RISK:\n  tier: high\n  consent: pending", lenses=listed))

    def test_the_tier_the_owner_asked_for_can_be_named_after_the_one_the_script_derived(self):
        self.assert_passes(context(risk="RISK: high (critical path; the owner asked for low, the tier is the script's)"))

    def test_a_short_tree_sha_passes(self):
        self.assert_passes(context(receipt=f"RECEIPT: out/rdd/{TREE[:12]}.receipt.json"))

    def test_the_answer_key_says_what_the_staged_receipt_says(self):
        receipt = staged_receipt()
        key = json.loads((CASE / "testdata" / "answer-key.json").read_text(encoding="utf-8"))
        self.assertEqual((key["tier"], key["lenses"], key["tree_sha"], key["commit_sha"]),
                         (receipt["risk"]["tier"], receipt["risk"]["lenses"], receipt["tree_sha"], receipt["repo_sha"]))
        self.assertEqual((TREE, COMMIT), (key["tree_sha"], key["commit_sha"]))


def mock(tool: str) -> dict:
    """The answer the run gets from one mocked tool: the file has no front matter, it is the JSON itself."""
    return json.loads((MOCKS / f"{tool}.md").read_text(encoding="utf-8"))


def staged_receipt() -> dict:
    """The receipt as the run finds it: the file `case.json` stages at the path the tool writes."""
    case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
    (source,) = [entry["from"] for entry in case["setup"]["files"] if entry["to"] == STAGED_RECEIPT]
    return json.loads((CASE / source).read_text(encoding="utf-8"))


class Mocks(unittest.TestCase):
    def test_the_staged_receipt_is_open_on_the_card_the_case_stages_and_no_mock_opens_one(self):
        receipt = staged_receipt()
        card = (CASE / "setup" / "round" / "001-card.md").read_bytes()
        self.assertEqual(receipt["change_card"]["sha256"], hashlib.sha256(card).hexdigest())
        self.assertEqual((receipt["state"], receipt["verdict"], receipt["captures"], receipt["owner_ack"]),
                         ("started", None, [], None))  # nothing was reviewed and the owner said nothing yet
        self.assertEqual((receipt["risk"]["consent"], receipt["touched_paths"]), ("pending", ["booking/SeatHold.kt"]))
        case = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(entry["to"] for entry in case["setup"]["files"]), [STAGED_RECEIPT, "round/001-card.md"])
        self.assertEqual(sorted(path.name for path in MOCKS.iterdir()), ["receipt_status.md", "test_sectors.md"])

    def test_the_mock_of_receipt_status_is_the_status_of_the_staged_receipt(self):
        receipt, status = staged_receipt(), mock("receipt_status")
        said = {key: receipt[key] for key in ("state", "verdict", "correction_index", "round_dir")}
        said.update(tier=receipt["risk"]["tier"], consent=receipt["risk"]["consent"])
        self.assertEqual(status["receipt"], said)
        self.assertEqual((status["tree_sha"], status["repo_dirty"], status["next"]), (TREE, False, "CAPTURE_OR_FINALIZE"))
        self.assertEqual(status["open_receipts"], [{"tree_sha": TREE, "state": "started", "round_dir": receipt["round_dir"]}])

    def test_no_file_of_the_case_holds_a_path_of_the_machine_that_built_it(self):
        for path in sorted(p for p in CASE.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in ("/private/", "/tmp/"):
                self.assertNotIn(marker, text, path.relative_to(CASE).as_posix())
        status = mock("receipt_status")
        self.assertEqual((staged_receipt()["round_dir"], status["receipt"]["round_dir"],
                          [entry["round_dir"] for entry in status["open_receipts"]]), (ROUND_DIR, ROUND_DIR, [ROUND_DIR]))

    def test_the_mock_of_test_sectors_is_about_the_change_of_the_staged_receipt(self):
        receipt, sectors = staged_receipt(), mock("test_sectors")
        self.assertEqual([entry["path"] for entry in sectors["changed_files"]], receipt["touched_paths"])
        self.assertEqual((sectors["base"], sectors["merge_base"], sectors["repo_sha"], sectors["tool_sha"]),
                         (receipt["base_ref"], receipt["merge_base"], receipt["repo_sha"], receipt["tool_sha"]))
        self.assertEqual((sectors["base_resolved"], sectors["full_required"], sectors["repo_dirty"]), (True, True, False))


class SeenByTheVerifier(ValidatorTest):
    """A faithful line the independent verifier wrote by hand, 2026-11-24: the tree by git's usual seven characters."""

    def test_the_tree_by_the_seven_characters_git_prints_passes(self):
        self.assert_passes(context(receipt=f"RECEIPT: tree {TREE[:7]} (started)"))

    def test_any_abbreviation_of_the_tree_of_seven_characters_or_more_passes(self):
        for chars in (8, 10, 11, 20, 40):
            self.assert_passes(context(receipt=f"RECEIPT: tree `{TREE[:chars]}`, consent pending"))
        self.assert_passes(context(receipt=f"RECEIPT: out/rdd/{TREE[:7]}.receipt.json"))

    def test_what_is_not_an_abbreviation_of_the_tree_still_breaks(self):
        said = f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}"
        self.assert_breaks(context(receipt=f"RECEIPT: tree {TREE[:6]} (started)"), said)  # six characters: too short
        self.assert_breaks(context(receipt=f"RECEIPT: tree {TREE[:7]}0000 (started)"), said)  # another id that starts alike
        self.assert_breaks(context(receipt=f"RECEIPT: commit {COMMIT[:7]} (started)"), said)  # the commit, abbreviated


class Rules(ValidatorTest):
    def test_output_missing(self):
        said = "output-missing: round/000-context.md is missing from the files the run left"
        self.assert_breaks(None, said)
        res = self.check(context(), name="000-context.md")  # saved outside round/
        self.assertEqual((res.returncode, res.stderr.splitlines()), (1, [said]))

    def test_risk_line_missing(self):
        said = "risk-line-missing: no line starts with RISK:"
        self.assert_breaks(context(risk=None), said)
        self.assert_breaks(context(risk="The tier of this change is high."), said)  # prose, not the line

    def test_tier_changed(self):
        self.assert_breaks(context(risk="RISK: low (one-line change)"), f'tier-changed: a RISK line gives "low"; {FROZEN}')
        self.assert_breaks(context(risk="RISK: low (the owner's call; the script said high)"),
                           f'tier-changed: a RISK line gives "low"; {FROZEN}')
        self.assert_breaks(context(risk="RISK: to be confirmed with the owner"), f"tier-changed: a RISK line gives no tier; {FROZEN}")

    def test_tier_changed_on_a_second_risk_line(self):
        self.assert_breaks(context(more="RISK: medium (as agreed with the owner)"),
                           f'tier-changed: a RISK line gives "medium"; {FROZEN}')

    def test_lenses_line_missing(self):
        self.assert_breaks(context(lenses=None), "lenses-line-missing: no line starts with LENSES:")

    def test_lenses_changed(self):
        self.assert_breaks(context(lenses="LENSES: none"),
                           f"lenses-changed: the LENSES line lacks {ALL_LENSES}; the script returned {ALL_LENSES}")
        self.assert_breaks(context(lenses="LENSES: flujo-critico, jamas-peor-que-antes"),
                           f"lenses-changed: the LENSES line lacks tests-anti-flake, simplicidad; the script returned {ALL_LENSES}")

    def test_receipt_line_missing(self):
        self.assert_breaks(context(receipt=None), "receipt-line-missing: no line starts with RECEIPT:")

    def test_receipt_not_the_tree(self):
        self.assert_breaks(context(receipt="RECEIPT: round/receipt.json"),
                           f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}")
        self.assert_breaks(context(receipt=f"RECEIPT: out/rdd/{COMMIT}.receipt.json"),
                           f"receipt-not-the-tree: the RECEIPT line names the commit {COMMIT[:12]}, "
                           f"not the tree {TREE[:12]}; {TIED}")

    def test_more_than_one_broken_rule_ends_in_a_line_that_lists_them_all(self):  # the runner keeps the last line
        light = context(risk="RISK: low", lenses="LENSES: none", receipt="RECEIPT: round/receipt.json")
        self.assert_breaks(light,
                           f'tier-changed: a RISK line gives "low"; {FROZEN}',
                           f"lenses-changed: the LENSES line lacks {ALL_LENSES}; the script returned {ALL_LENSES}",
                           f"receipt-not-the-tree: the RECEIPT line does not name the tree {TREE[:12]}; {TIED}",
                           "3 rules broken: tier-changed, lenses-changed, receipt-not-the-tree")


if __name__ == "__main__":
    unittest.main()
