"""lib/done_check.py (WU16, context-method §6, done-gate.md §3): DONE-01..17
as pure checks over explicit inputs. Every rule has a PASS and a FLAG
fixture (temporary git repos, synthetic runs.jsonl and receipts); the
shipped config starts every rule in FLAG (D2), so BLOCK and exit 1 come
from a test config. Marker words the gate itself hunts are built by
concatenation so this file never trips DONE-11/12 on the kit."""
import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import done_check, findings_schema_validator, run_check

TOOLS_ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((TOOLS_ROOT / "config" / "done-gate.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((TOOLS_ROOT / "schemas" / "done-check-output.schema.json").read_text(encoding="utf-8"))
ACTION = "TO" + "DO"
MARKER = "NEEDS-" + "COMMENT"
RULE_IDS = [f"DONE-{n:02d}" for n in range(1, 18)]
TEST_FILE = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_f(self):\n        self.assertEqual(1, 1)\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class Fixture(unittest.TestCase):
    kit = False
    kit_exit = 0
    caps = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="done-check-"))
        self.repo = self.tmp / "repo"
        files = {"03-tools/lib/a.py": "def f():\n    return 1\n", "03-tools/tests/test_a.py": TEST_FILE,
                 "docs/x.md": "# x\n", "README.md": "readme\n", ".gitignore": "ignored/\n"}
        if self.kit:
            files["01-roles/r.md"] = "role\n"
            files["03-tools/lib/kit_status.py"] = f"import sys\nprint('kit-status stub')\nsys.exit({self.kit_exit})\n"
        if self.caps is not None:
            files["03-tools/config/docs-caps.json"] = json.dumps({"docs_root": ".", "caps": self.caps})
        for rel, text in files.items():
            self.write(rel, text)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.runs = self.tmp / "runs" / "runs.jsonl"
        self.receipts = self.tmp / "rdd"
        self.receipts.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def edit_source(self):
        self.write("03-tools/lib/a.py", "def f():\n    return 2\n")

    def commit_all(self, message="change") -> str:
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", message)
        return _git(self.repo, "rev-parse", "HEAD")

    def add_run(self, name="03-tools", exit_code=0, argv=None, fingerprint=None):
        self.runs.parent.mkdir(parents=True, exist_ok=True)
        lines = self.runs.read_text(encoding="utf-8").splitlines() if self.runs.exists() else []
        fp = fingerprint or run_check.worktree_fingerprint(self.repo)
        record = dict(fp, argv=argv or ["python3", "-m", "unittest", "discover", "tests"], cwd="03-tools", elapsed_ms=5,
                      exit=exit_code, log=f"{len(lines) + 1}.log", name=name, output_sha256="0" * 64, schema_version=1,
                      seq=len(lines) + 1)
        with self.runs.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def check(self, reply: str | None = "Done.", *extra: str, config: dict | None = None, raw=False):
        args = ["--repo", str(self.repo), "--runs", str(self.runs), "--receipts", str(self.receipts)]
        if reply is not None:
            reply_path = self.tmp / "reply.md"
            reply_path.write_text(reply, encoding="utf-8")
            args += ["--reply", str(reply_path)]
        if config is not None:
            config_path = self.tmp / "done-gate.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            args += ["--config", str(config_path)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = done_check.main(args + list(extra))
        if raw:
            return code, out.getvalue(), err.getvalue()
        return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None)

    def rule(self, payload: dict, rule_id: str) -> dict:
        return next(r for r in payload["rules"] if r["id"] == rule_id)

    def status(self, reply="Done.", *extra, rule_id, **kw) -> str:
        return self.rule(self.check(reply, *extra, **kw)[1], rule_id)["status"]


def _block_config(*rule_ids):
    config = json.loads(json.dumps(CONFIG))
    for rule_id in rule_ids:
        config["rules"][rule_id]["mode"] = "BLOCK"
    return config


class ClaimDetectorTests(unittest.TestCase):
    def claims(self, text):
        return done_check.detect_claims(text, CONFIG)

    def test_english_and_spanish_claim_words(self):
        cases = {
            "Done.": ["done"], "Finished the refactor.": ["done"], "The task is complete.": ["done"],
            "All tests pass.": ["green"], "The suite is green.": ["green"], "Todo en verde.": ["green"],
            "Committed as the last step.": ["committed"], "Cambios commiteados.": ["committed"],
            "Pushed to origin.": ["delivered"], "Delivered.": ["delivered"], "Publicado en npm.": ["delivered"],
            "Entregado al cliente.": ["delivered"], "Listo.": ["done"], "Terminado.": ["done"], "Hecho.": ["done"],
            "Done and committed, all green.": ["committed", "done", "green"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.claims(text), expected)

    def test_no_claim_for_questions_negations_code_quotes_and_facts(self):
        for text in ("Which option do you prefer?", "It is not done yet.", "Todavía no está listo.",
                     "Nothing was committed.", "Run `git commit` when done.".replace("when done", "later"),
                     "```\ndone\n```\nWhich one?", "> done\n\nShould I go on?", 'You wrote "done" earlier; what next?',
                     "De hecho, falta una prueba.", "DONE-02 needs a run.", ""):
            with self.subTest(text=text):
                self.assertEqual(self.claims(text), [])

    def test_status_completed_counts_as_a_done_claim_even_in_a_fence(self):
        self.assertEqual(self.claims("```text\nstatus: completed\nsummary: x\n```\n"), ["done"])


class ShortCircuitAndContractTests(Fixture):
    def test_no_claim_runs_nothing_and_says_no_claim(self):
        missing_repo = self.tmp / "not-a-repo"
        reply = self.tmp / "q.md"
        reply.write_text("Which option do you prefer?", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = done_check.main(["--repo", str(missing_repo), "--reply", str(reply)])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "no-claim")
        self.assertEqual(payload["claims"], [])
        self.assertEqual(payload["flag_block"], "DONE-GATE: no-claim")
        self.assertEqual([r["status"] for r in payload["rules"]], ["SKIP"])

    def test_every_rule_reported_once_in_order_with_fixed_keys(self):
        code, payload = self.check()
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in payload["rules"]], RULE_IDS)
        for entry in payload["rules"]:
            self.assertEqual(sorted(entry), ["evidence", "fix", "id", "mode", "status", "target_mode", "waiver"])
            self.assertIn(entry["status"], ("PASS", "FLAG", "BLOCK", "SKIP"))
            if entry["status"] == "SKIP":
                self.assertTrue(entry["evidence"], entry["id"])  # a SKIP always says why
        self.assertEqual(findings_schema_validator.validate(payload, SCHEMA)["verdict"], "PASS",
                         findings_schema_validator.validate(payload, SCHEMA))

    def test_same_inputs_same_bytes(self):
        self.edit_source()
        self.add_run()
        first = self.check("Done, all green.", raw=True)
        second = self.check("Done, all green.", raw=True)
        self.assertEqual(first, second)

    def test_shipped_config_starts_every_rule_in_flag_with_a_target_mode(self):
        self.assertEqual(sorted(CONFIG["rules"]), RULE_IDS)
        for rule_id, rule in CONFIG["rules"].items():
            self.assertEqual(rule["mode"], "FLAG", rule_id)
            self.assertIn(rule["target_mode"], ("FLAG", "BLOCK"), rule_id)
        self.assertEqual({r for r, v in CONFIG["rules"].items() if v["target_mode"] == "BLOCK"},
                         {"DONE-02", "DONE-04", "DONE-05", "DONE-06", "DONE-07", "DONE-08", "DONE-10", "DONE-11",
                          "DONE-12", "DONE-13", "DONE-14", "DONE-16"})

    def test_block_mode_exits_1_and_the_flag_block_has_the_fixed_format(self):
        self.edit_source()
        code, payload = self.check("Done.", config=_block_config("DONE-02"))
        self.assertEqual(code, 1)
        self.assertEqual(payload["verdict"], "BLOCK")
        lines = payload["flag_block"].splitlines()
        self.assertLessEqual(len(lines), 40)
        self.assertRegex(lines[0], r"^DONE-GATE: BLOCK 1 · FLAG \d+ · tree [0-9a-f]{7} · tool [0-9a-f]{7}$")
        for line in lines[1:]:
            self.assertRegex(line, r"^- DONE-\d\d (?:BLOCK|FLAG) .+ · fix: .+$|^- DONE-\d\d WAIVED by .+: .+$")
        self.assertTrue(any(line.startswith("- DONE-02 BLOCK ") for line in lines))

    def test_format_block_prints_only_the_block(self):
        code, text, _ = self.check("Done.", "--format", "block", raw=True)
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith("DONE-GATE: "))

    def test_usage_errors_exit_2(self):
        for extra in (["--open-jobs", "-1"], ["--tier", "huge"], ["--claim", "nope"]):
            with self.subTest(extra=extra):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.check("Done.", *extra, raw=True)[0], 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(done_check.main(["--repo", str(self.repo)]), 2)  # neither --reply nor --claim

    def test_waive_is_the_owners_step_not_this_tool(self):
        code, _, err = self.check("Done.", "--waive", "DONE-04", "--reason", "x", raw=True)
        self.assertEqual(code, 2)
        self.assertIn("owner", err)

    def test_claim_flag_without_reply(self):
        code, payload = self.check(None, "--claim", "green")
        self.assertEqual((code, payload["claims"]), (0, ["green"]))

    def test_exempt_tier_skips_02_03_04_09(self):
        self.edit_source()
        _, payload = self.check("Done.", "--tier", "exempt")
        for rule_id in ("DONE-02", "DONE-03", "DONE-04", "DONE-09"):
            self.assertEqual(self.rule(payload, rule_id)["status"], "SKIP", rule_id)
            self.assertIn("exempt", " ".join(self.rule(payload, rule_id)["evidence"]))

    def test_mode_pass_turns_a_rule_off_as_a_skip_with_findings(self):
        self.edit_source()
        config = json.loads(json.dumps(CONFIG))
        config["rules"]["DONE-02"]["mode"] = "PASS"
        entry = self.rule(self.check("Done.", config=config)[1], "DONE-02")
        self.assertEqual(entry["status"], "SKIP")
        self.assertIn("off", entry["evidence"][0])


class WaiverTests(Fixture):
    def _waiver(self, rule_id="DONE-02", fingerprint=None):
        fp = fingerprint or run_check.worktree_fingerprint(self.repo)
        path = self.tmp / "waivers.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "done-waiver", "rule": rule_id, "tree_sha": fp["tree_sha"],
                                     "worktree_sha": fp["worktree_sha"], "reason": "suite runs in CI",
                                     "email": "owner@example.com"}) + "\n")
        return path

    def test_waiver_on_the_current_tree_clears_the_block_and_is_shown(self):
        self.edit_source()
        waivers = self._waiver()
        code, payload = self.check("Done.", "--waivers", str(waivers), config=_block_config("DONE-02"))
        self.assertEqual(code, 0)
        entry = self.rule(payload, "DONE-02")
        self.assertEqual(entry["waiver"], {"email": "owner@example.com", "reason": "suite runs in CI"})
        self.assertIn("- DONE-02 WAIVED by owner@example.com: suite runs in CI", payload["flag_block"].splitlines())

    def test_waiver_dies_when_the_tree_changes(self):
        self.edit_source()
        waivers = self._waiver()
        self.write("03-tools/lib/a.py", "def f():\n    return 3\n")
        code, payload = self.check("Done.", "--waivers", str(waivers), config=_block_config("DONE-02"))
        self.assertEqual(code, 1)
        self.assertIsNone(self.rule(payload, "DONE-02")["waiver"])

    def test_waiver_lines_are_also_read_from_the_session_ledger(self):
        self.edit_source()
        session = self.tmp / "session"
        session.mkdir()
        shutil.copy(self._waiver(), session / "ledger.jsonl")
        code, _ = self.check("Done.", "--session-dir", str(session), config=_block_config("DONE-02"))
        self.assertEqual(code, 0)


class GreenRunTests(Fixture):
    def test_02_pass_with_a_green_run_on_the_current_tree(self):
        self.edit_source()
        self.add_run()
        self.assertEqual(self.status(rule_id="DONE-02"), "PASS")

    def test_02_flag_without_a_run_or_after_a_later_edit_or_when_the_last_run_failed(self):
        self.edit_source()
        entry = self.rule(self.check()[1], "DONE-02")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("03-tools", " ".join(entry["evidence"]))
        self.assertIn("run-check.sh 03-tools --", entry["fix"])
        self.add_run()
        self.write("03-tools/lib/a.py", "def f():\n    return 3\n")  # edit after the run
        self.assertEqual(self.status(rule_id="DONE-02"), "FLAG")
        self.add_run(exit_code=0)
        self.add_run(exit_code=1)  # last run on this tree is red
        self.assertEqual(self.status(rule_id="DONE-02"), "FLAG")

    def test_02_docs_only_change_needs_no_run_and_unknown_touch_is_a_skip(self):
        self.assertEqual(self.status(rule_id="DONE-02"), "SKIP")  # clean tree, no base: nothing known
        self.write("docs/x.md", "# x\nmore\n")
        self.assertEqual(self.status(rule_id="DONE-02"), "PASS")

    def test_02_base_range_finds_committed_touches(self):
        base = _git(self.repo, "rev-parse", "HEAD")
        self.edit_source()
        self.commit_all()
        self.assertEqual(self.status("Done.", "--base", base, rule_id="DONE-02"), "FLAG")
        self.add_run()
        self.assertEqual(self.status("Done.", "--base", base, rule_id="DONE-02"), "PASS")

    def test_03_pass_with_red_before_green_and_flag_with_green_only(self):
        self.edit_source()
        self.add_run()
        self.assertEqual(self.status(rule_id="DONE-03"), "FLAG")
        self.runs.unlink()
        self.add_run(exit_code=1)
        self.add_run(exit_code=0)
        self.assertEqual(self.status(rule_id="DONE-03"), "PASS")

    def test_03_refactor_only_is_a_skip(self):
        self.edit_source()
        self.assertEqual(self.status("Done.", "--refactor-only", rule_id="DONE-03"), "SKIP")

    def test_09_pass_when_the_cards_command_ran_and_flag_when_not(self):
        card = self.tmp / "card.md"
        card.write_text("**How we'll know**: `python3 -m unittest tests.test_a` fails without the fix [Tested]\n",
                        encoding="utf-8")
        self.edit_source()
        self.assertEqual(self.status("Done.", "--card", str(card), rule_id="DONE-09"), "FLAG")
        self.add_run(argv=["python3", "-m", "unittest", "tests.test_a"])
        self.assertEqual(self.status("Done.", "--card", str(card), rule_id="DONE-09"), "PASS")


class NotTestedTests(Fixture):
    def test_10_flag_when_a_skip_exists_and_no_not_tested_line_names_it(self):
        self.edit_source()
        self.assertEqual(self.status(rule_id="DONE-10"), "FLAG")
        self.assertEqual(self.status("Done.\n\nNot tested: the suite elsewhere.", rule_id="DONE-10"), "FLAG")

    def test_10_pass_when_the_line_names_each_skip_or_nothing_was_skipped(self):
        self.edit_source()
        self.assertEqual(self.status("Done.\n\nNot tested: the 03-tools suite (no run).", rule_id="DONE-10"), "PASS")
        self.assertEqual(self.status("Hecho.\n\nNo probado: suite de 03-tools.", rule_id="DONE-10"), "PASS")
        self.add_run(exit_code=1)
        self.add_run()
        self.assertEqual(self.status(rule_id="DONE-10"), "PASS")

    def test_10_no_verify_in_the_ledger_is_a_skip(self):
        session = self.tmp / "session"
        session.mkdir()
        (session / "ledger.jsonl").write_text(json.dumps({"kind": "no-verify", "hook": "guard_gates"}) + "\n", encoding="utf-8")
        self.assertEqual(self.status("Done.", "--session-dir", str(session), rule_id="DONE-10"), "FLAG")
        self.assertEqual(self.status("Done.\nNot tested: hooks skipped by --no-verify.", "--session-dir", str(session),
                                     rule_id="DONE-10"), "PASS")


class WeakenedTestTests(Fixture):
    def test_04_pass_when_a_test_is_added(self):
        self.write("03-tools/tests/test_a.py", TEST_FILE + "\n    def test_g(self):\n        self.assertTrue(True)\n")
        self.assertEqual(self.status(rule_id="DONE-04"), "PASS")

    def test_04_flag_on_a_removed_assertion_a_deleted_test_or_an_added_skip(self):
        self.write("03-tools/tests/test_a.py", TEST_FILE.replace("        self.assertEqual(1, 1)\n", "        pass\n"))
        self.assertEqual(self.status(rule_id="DONE-04"), "FLAG")
        (self.repo / "03-tools/tests/test_a.py").unlink()
        self.assertEqual(self.status(rule_id="DONE-04"), "FLAG")
        self.write("03-tools/tests/test_a.py", TEST_FILE.replace("    def test_f", "    @unittest.skip('later')\n    def test_f"))
        entry = self.rule(self.check()[1], "DONE-04")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("skip", " ".join(entry["evidence"]))

    def test_04_reformatted_assertion_is_not_a_weakening(self):
        self.write("03-tools/tests/test_a.py", TEST_FILE.replace("assertEqual(1, 1)", "assertEqual(1,  1)"))
        self.assertEqual(self.status(rule_id="DONE-04"), "PASS")


class MarkerTests(Fixture):
    def test_11_flag_on_an_unticketed_action_tag_and_pass_when_ticketed(self):
        self.write("03-tools/lib/a.py", f"def f():\n    # {ACTION} fix later\n    return 1\n")
        entry = self.rule(self.check()[1], "DONE-11")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("03-tools/lib/a.py:2", " ".join(entry["evidence"]))
        self.write("03-tools/lib/a.py", f"def f():\n    # {ACTION}(KEY-12): fix later\n    return 1\n")
        self.assertEqual(self.status(rule_id="DONE-11"), "PASS")

    def test_11_untracked_file_counts_and_docs_are_exempt(self):
        self.write("03-tools/lib/b.py", f"x = 1  # {ACTION} later\n")
        self.assertEqual(self.status(rule_id="DONE-11"), "FLAG")
        (self.repo / "03-tools/lib/b.py").unlink()
        self.write("docs/x.md", f"# x\n<!-- {ACTION} write more -->\n")
        self.assertEqual(self.status(rule_id="DONE-11"), "PASS")

    def test_12_flag_on_a_marker_in_a_touched_file_and_pass_without(self):
        self.write("03-tools/lib/a.py", f"def f():\n    # {MARKER}\n    return 1\n")
        self.assertEqual(self.status(rule_id="DONE-12"), "FLAG")
        self.edit_source()
        self.assertEqual(self.status(rule_id="DONE-12"), "PASS")

    def test_12_a_marker_already_committed_is_not_this_changes_leftover(self):
        self.write("03-tools/lib/a.py", f"DESCRIPTION = 'no {MARKER} marker remains'\n")
        self.commit_all()
        self.write("03-tools/lib/a.py", f"DESCRIPTION = 'no {MARKER} marker remains'\nX = 1\n")
        self.assertEqual(self.status(rule_id="DONE-12"), "PASS")


class DocsAndKitTests(Fixture):
    caps = {"docs/x.md": 3}

    def test_05_pass_under_cap_and_flag_over_cap(self):
        self.edit_source()
        self.assertEqual(self.status(rule_id="DONE-05"), "PASS")
        self.write("docs/x.md", "1\n2\n3\n4\n5\n")
        entry = self.rule(self.check()[1], "DONE-05")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("docs/x.md", " ".join(entry["evidence"]))

    def test_05_new_doc_in_a_capped_folder_without_a_cap_is_a_flag_even_in_block_mode(self):
        self.write("docs/y.md", "# y\n")
        entry = self.rule(self.check("Done.", config=_block_config("DONE-05"))[1], "DONE-05")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("docs/y.md", " ".join(entry["evidence"]))

    def test_06_non_kit_repo_is_a_skip(self):
        self.assertEqual(self.status(rule_id="DONE-06"), "SKIP")


class NoCapsTests(Fixture):
    def test_05_no_caps_config_is_a_skip(self):
        self.assertEqual(self.status(rule_id="DONE-05"), "SKIP")


class KitPassTests(Fixture):
    kit = True
    kit_exit = 0

    def test_06_pass_when_kit_status_check_exits_0(self):
        self.edit_source()
        self.assertEqual(self.status(rule_id="DONE-06"), "PASS")


class KitStaleTests(Fixture):
    kit = True
    kit_exit = 1

    def test_06_flag_when_kit_status_check_fails(self):
        self.edit_source()
        entry = self.rule(self.check()[1], "DONE-06")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("kit-status.sh --write", entry["fix"])


class ReceiptTests(Fixture):
    def _receipt(self, **fields):
        tree = _git(self.repo, "rev-parse", "HEAD^{tree}")
        receipt = {"tree_sha": tree, "verdict": "approved", "verdict_reasons": ["all required captures present and clean"],
                   "owner_ack": None, "risk": {"tier": "medium"}}
        receipt.update(fields)
        (self.receipts / f"{tree}.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    def test_07_pass_with_an_approved_receipt(self):
        self._receipt()
        self.assertEqual(self.status("Pushed.", rule_id="DONE-07"), "PASS")

    def test_07_flag_without_receipt_or_with_an_unquoted_unreviewed_ack(self):
        self.assertEqual(self.status("Pushed.", rule_id="DONE-07"), "FLAG")
        self._receipt(verdict_reasons=["owner declared the candidate unreviewed"],
                      owner_ack={"decision": "unreviewed", "reason": "hotfix tonight"})
        self.assertEqual(self.status("Pushed.", rule_id="DONE-07"), "FLAG")
        self.assertEqual(self.status('Pushed. Owner ack: "hotfix tonight".', rule_id="DONE-07"), "PASS")

    def test_07_skips_when_nothing_is_delivered(self):
        self.assertEqual(self.status("Done.", rule_id="DONE-07"), "SKIP")


TASK_DOC = """# Feature: f

## Specs

- **S1 First.** text
- **S2 Second.** text

## Tasks

| ID | Specs | Work | Status | Evidence |
|---|---|---|---|---|
| T1 | S1 | a | done | RED 1F -> GREEN 3 OK |
| T2 | S2 | b | {status} | {evidence} |

## Log
"""


class SpecTests(Fixture):
    def _task(self, status="done", evidence="GREEN 4 OK"):
        path = self.tmp / "task.md"
        path.write_text(TASK_DOC.format(status=status, evidence=evidence), encoding="utf-8")
        return path

    def test_08_pass_when_every_spec_sits_in_a_done_row_with_evidence(self):
        self.assertEqual(self.status("The feature is done.", "--task", str(self._task()), rule_id="DONE-08"), "PASS")

    def test_08_flag_on_an_open_spec_and_pass_when_it_carries_a_verdict(self):
        task = self._task(status="todo", evidence="")
        entry = self.rule(self.check("The feature is done.", "--task", str(task))[1], "DONE-08")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("S2", " ".join(entry["evidence"]))
        with task.open("a", encoding="utf-8") as handle:
            handle.write("- S2 verdict: PARTIAL (b is deferred)\n")
        self.assertEqual(self.status("The feature is done.", "--task", str(task), rule_id="DONE-08"), "PASS")

    def test_08_task_level_claim_is_a_skip(self):
        task = self._task(status="todo", evidence="")
        self.assertEqual(self.status("T1 done.", "--task", str(task), rule_id="DONE-08"), "SKIP")


class CommittedTests(Fixture):
    def test_13_pass_when_clean_and_the_cited_sha_is_reachable(self):
        self.edit_source()
        sha = self.commit_all()
        self.assertEqual(self.status(f"Committed as {sha[:7]}.", rule_id="DONE-13"), "PASS")

    def test_13_flag_when_touched_paths_are_dirty_or_the_sha_is_unknown(self):
        self.edit_source()
        entry = self.rule(self.check("Committed.")[1], "DONE-13")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("03-tools/lib/a.py", " ".join(entry["evidence"]))
        self.commit_all()
        self.assertEqual(self.status("Committed as commit abc1234.", rule_id="DONE-13"), "FLAG")

    def test_13_skips_for_a_plain_done(self):
        self.assertEqual(self.status("Done.", rule_id="DONE-13"), "SKIP")


TECH = "Done.\n\n## Technical detail\n\n"


class CitationTests(Fixture):
    def test_14_pass_on_existing_citations_and_flag_on_missing(self):
        self.assertEqual(self.status(TECH + "- `03-tools/lib/a.py:1` holds f [Measured]\n", rule_id="DONE-14"), "PASS")
        entry = self.rule(self.check(TECH + "- `03-tools/lib/a.py:99` holds f [Measured]\n")[1], "DONE-14")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("03-tools/lib/a.py:99", " ".join(entry["evidence"]))

    def test_15_flag_on_a_bare_tag_and_pass_with_citation_output_or_run(self):
        bare = TECH + "- the parser is fast [Measured]\n"
        entry = self.rule(self.check(bare)[1], "DONE-15")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("line 5", " ".join(entry["evidence"]))
        self.assertEqual(self.status(TECH + "- f returns 1, `03-tools/lib/a.py:2` [Tested]\n", rule_id="DONE-15"), "PASS")
        self.assertEqual(self.status(bare + "\n```\nOK\n```\n", rule_id="DONE-15"), "PASS")
        self.add_run()
        self.assertEqual(self.status(bare, rule_id="DONE-15"), "PASS")


RETURN_BLOCK = "status: {status}\nsummary: x\nvalidation:\n  - python3 -m unittest tests.test_a: {result}\nrisks:\n  - none\n"


class SubagentReturnTests(Fixture):
    def _ret(self, status="completed", result="Ran 3 tests, OK"):
        path = self.tmp / "return.txt"
        path.write_text(RETURN_BLOCK.format(status=status, result=result), encoding="utf-8")
        return str(path)

    def test_16_pass_when_completed_matches_green_validation(self):
        self.assertEqual(self.status("Done.", "--subagent-return", self._ret(), rule_id="DONE-16"), "PASS")
        self.assertEqual(self.status("Done.", "--subagent-return", self._ret("partial", "FAILED (errors=1)"),
                                     rule_id="DONE-16"), "PASS")

    def test_16_flag_when_completed_has_a_failing_line_unless_it_is_known(self):
        ret = self._ret(result="FAILED (errors=1)")
        self.assertEqual(self.status("Done.", "--subagent-return", ret, rule_id="DONE-16"), "FLAG")
        self.assertEqual(self.status("Done.", "--subagent-return", ret, "--known-failure", "tests.test_a",
                                     rule_id="DONE-16"), "PASS")

    def test_16_the_reply_itself_is_read_and_no_block_is_a_skip(self):
        self.assertEqual(self.status(RETURN_BLOCK.format(status="completed", result="exit 1"), rule_id="DONE-16"), "FLAG")
        self.assertEqual(self.status("Done.", rule_id="DONE-16"), "SKIP")


class LeftoverTests(Fixture):
    def test_17_pass_when_nothing_runs_or_lies_around(self):
        self.assertEqual(self.status("Done.", "--open-jobs", "0", rule_id="DONE-17"), "PASS")

    def test_17_flag_on_open_jobs_temp_paths_and_untracked_leftovers(self):
        self.assertEqual(self.status("Done.", "--open-jobs", "2", rule_id="DONE-17"), "FLAG")
        scratch = self.tmp / "scratch.txt"
        scratch.write_text("x", encoding="utf-8")
        self.assertEqual(self.status("Done.", "--temp-path", str(scratch), rule_id="DONE-17"), "FLAG")
        self.assertEqual(self.status("Done.", "--temp-path", str(self.tmp / "gone.txt"), rule_id="DONE-17"), "PASS")
        self.write("03-tools/lib/a.py.orig", "old\n")
        entry = self.rule(self.check()[1], "DONE-17")
        self.assertEqual(entry["status"], "FLAG")
        self.assertIn("03-tools/lib/a.py.orig", " ".join(entry["evidence"]))


class ClaimRuleTests(Fixture):
    def test_01_pass_names_the_claim_classes(self):
        entry = self.rule(self.check("Done and committed.")[1], "DONE-01")
        self.assertEqual(entry["status"], "PASS")
        self.assertIn("committed", " ".join(entry["evidence"]))

    def test_rules_not_selected_by_the_claim_are_skips_that_say_why(self):
        _, payload = self.check("All green.")
        for rule_id in ("DONE-07", "DONE-08", "DONE-13"):
            entry = self.rule(payload, rule_id)
            self.assertEqual(entry["status"], "SKIP", rule_id)
            self.assertTrue(re.search(r"claim", entry["evidence"][0]), entry)


if __name__ == "__main__":
    unittest.main()
