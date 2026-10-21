"""T7 (S2, odd/tasks/delegation-context.md): the main session cannot silently
do the team's work.

1. guard_paths.py: a main-session edit of a source path, when the newest
   routing decision put a writer at `delegate: subagent`, gets one visible
   `METODO-WARN delegate-writer` and one ledger line, once per session per
   decision. Never a deny or an ask: the owner keeps control.
2. output_author.py (PostToolUse mcp__metodo__output_write) ledgers who wrote
   each round output; rdd_receipt.capture freezes that author in the capture
   and finalize turns a main-authored review into `inconclusive`.
3. T18 (B-005/A-006): the same hook records a Write/Edit/MultiEdit into a
   round dir; a review capture with no recorded author keeps its verdict but
   the receipt lists it under `author_unknown`.
Captures and receipts with no authorship keep today's verdict."""
import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path

from lib import baseline, rdd_receipt as rr, round_output, router
from tests import test_rdd_receipt as trr
from tests.test_hooks import HOOKS, HookFixture

TOOLS_ROOT = Path(__file__).resolve().parent.parent
CATALOG = baseline.load_json(TOOLS_ROOT / "config" / "model-tiers.json")
AS_OF = "2026-10-16"
OUTPUT_WRITE = "mcp__metodo__output_write"


def _task(**overrides):
    task = {"task_kind": "implement", "tier": "medium", "lane": "sonnet", "critical_hit": False, "owner_gate": False,
            "changed_lines": 50, "modules": 1, "full_required": False, "map_age_days": 1, "offline": False,
            "owner_named": False, "prior": {}, "approvals": []}
    task.update(overrides)
    return task


def _line(repo=None, **overrides) -> str:
    """One routing-log line exactly as the router writes it; `repo` is the task's
    root (a line without it never matches a repo, T16 B-006)."""
    return router.log_line(router.route(_task(**overrides), CATALOG, AS_OF), str(repo) if repo else None)


DELEGATED = {"changed_lines": 500}          # medium, 500 lines: proposer at delegate: subagent (rule B3)
SMALL = {"changed_lines": 10}               # medium, 10 lines, one module: proposer in the main session


class MainSessionWriterWarn(HookFixture):
    def write_log(self, *lines: str):
        self.routing_log.parent.mkdir(parents=True, exist_ok=True)
        with self.routing_log.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")

    def edit(self, rel, **extra):
        return {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / rel)}, **extra}

    def delegate_lines(self, session="s1"):
        return [l for l in self.ledger(session) if l["kind"] == "main-edit-delegated-role"]

    def test_main_edit_with_writer_delegated_warns_once(self):
        self.write_log(_line(self.repo, **SMALL), _line(self.repo, **DELEGATED))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        text = self.assert_visible_warn(out, "delegate-writer")
        self.assertIn("generic-proposer", text)
        self.assertIn("B3", text)
        [line] = self.delegate_lines()
        self.assertEqual((line["hook"], line["decision"], line["path"]), ("guard_paths", "warn", "app/Foo.kt"))
        again, _ = self.run_hook("guard_paths.py", self.edit("app/Bar.kt"))
        self.assertEqual(again, {}, "one warn per session per routing decision")
        self.assertEqual(len(self.delegate_lines()), 1)

    def test_a_new_routing_decision_warns_again_and_a_new_session_too(self):
        self.write_log(_line(self.repo, **DELEGATED))
        self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"), session="s2")
        self.assert_visible_warn(out, "delegate-writer")
        self.write_log(_line(self.repo, changed_lines=400))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assert_visible_warn(out, "delegate-writer")
        self.assertEqual(len(self.delegate_lines()), 2)

    def test_subagent_edit_is_silent(self):
        self.write_log(_line(self.repo, **DELEGATED))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(out, {})
        self.assertEqual(self.delegate_lines(), [])

    def test_newest_small_task_decision_is_silent(self):
        # negative control: the newest line wins, deterministically
        self.write_log(_line(self.repo, **DELEGATED), _line(self.repo, **SMALL))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assertEqual(out, {})
        self.assertEqual(self.delegate_lines(), [])

    def test_no_routing_log_is_silent(self):
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger(), [])

    def test_a_line_without_repo_is_ignored(self):
        self.write_log(_line(**DELEGATED))  # no repo: an old or foreign decision never warns
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assertEqual(out, {})

    def test_a_roster_without_a_writer_is_silent(self):
        self.write_log(_line(self.repo, task_kind="map", modules=5))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assertEqual(out, {})

    def test_another_repos_decision_is_ignored(self):
        line = json.loads(_line(self.repo, **DELEGATED))
        line["repo"] = str(self.tmp / "elsewhere")
        self.write_log(json.dumps(line))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/Foo.kt"))
        self.assertEqual(out, {})

    def test_tests_docs_odd_and_round_paths_are_silent(self):
        self.write_log(_line(self.repo, **DELEGATED))
        for rel in ("README.md", "app/src/test/FooTest.kt", "odd/tasks/x.txt"):
            with self.subTest(path=rel):
                out, _ = self.run_hook("guard_paths.py", self.edit(rel))
                self.assertEqual(out, {}, rel)
        round_file = self.tmp / "round" / "001-challenger-findings.json"
        out, _ = self.run_hook("guard_paths.py", {"tool_name": "Write", "tool_input": {"file_path": str(round_file)}})
        self.assertEqual(out, {})
        self.assertEqual(self.delegate_lines(), [])

    def test_shared_build_file_keeps_the_owner_gate(self):
        # negative control: the absolute ask is unchanged and nothing is added on top of it
        self.write_log(_line(self.repo, **DELEGATED))
        out, _ = self.run_hook("guard_paths.py", self.edit("app/build.gradle"))
        self.assertEqual(self.decision(out), "ask")
        self.assertEqual(self.delegate_lines(), [])


class OutputAuthorship(HookFixture):
    def setUp(self):
        super().setUp()
        self.round_dir = self.tmp / "round"

    def write_output(self, role="challenger", doc=None):
        result = round_output.write_output(self.round_dir, role, doc or trr.FINDINGS_OK, repo=self.repo)
        return self.round_dir / Path(result["path"]).name

    def post(self, role="challenger", doc=None, **extra):
        payload = {"hook_event_name": "PostToolUse", "tool_name": OUTPUT_WRITE,
                   "tool_input": {"round_dir": str(self.round_dir), "role": role, "document": doc or trr.FINDINGS_OK}}
        payload.update(extra)
        return self.run_hook("output_author.py", payload)

    def authored(self, session="s1"):
        return [l for l in self.ledger(session) if l["kind"] == "output-authored"]

    def test_main_session_authorship_is_ledgered(self):
        path = self.write_output()
        out, _ = self.post()
        self.assertEqual(out, {}, "a recorder never decides")
        [line] = self.authored()
        self.assertEqual((line["hook"], line["decision"], line["tool"]), ("output_author", "record", OUTPUT_WRITE))
        self.assertEqual(line["path"], path.resolve().as_posix())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(line["reason"], f"author=main role=generic-challenger schema=findings sha256={sha}")

    def test_subagent_authorship_names_the_role(self):
        self.write_output("verifier", trr.VERIFICATION_PASS)
        self.post("verifier", trr.VERIFICATION_PASS, agent_type="generic-verifier", agent_id="a1")
        [line] = self.authored()
        self.assertTrue(line["reason"].startswith("author=generic-verifier role=generic-verifier schema=verification "), line)

    def test_other_tools_and_bad_input_record_nothing(self):
        # negative control
        self.run_hook("output_author.py", {"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                           "tool_input": {"file_path": "a"}})
        self.run_hook("output_author.py", {"hook_event_name": "PostToolUse", "tool_name": OUTPUT_WRITE,
                                           "tool_input": {"round_dir": str(self.round_dir), "role": "nobody", "document": []}})
        self.assertEqual(self.authored(), [])

    def test_the_hook_is_wired_on_claude_code(self):
        settings = json.loads((HOOKS / "hooks.settings.json").read_text(encoding="utf-8"))["hooks"]
        wired = [e for e in settings["PostToolUse"] if e["matcher"] == OUTPUT_WRITE]
        self.assertEqual(len(wired), 1)
        self.assertIn('"$H/output_author.py"', wired[0]["hooks"][0]["command"])
        # T18: and on the file tools, so a round output written by hand is attributed too
        wired = [e for e in settings["PostToolUse"] if e["matcher"] == "Edit|Write|MultiEdit"
                 and '"$H/output_author.py"' in e["hooks"][0]["command"]]
        self.assertEqual(len(wired), 1)

    # T18 (B-005/A-006): Write/Edit/MultiEdit into a round dir
    def open_receipt(self, round_dir, state="started", tree="t" * 40):
        self.rdd_dir.mkdir(parents=True, exist_ok=True)
        (self.rdd_dir / f"{tree}.receipt.json").write_text(json.dumps(
            {"tree_sha": tree, "state": state, "round_dir": str(round_dir)}), encoding="utf-8")

    def file_tool(self, tool, path, text='{"x": 1}\n', **extra):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {"file_path": str(path)}}
        payload.update(extra)
        out, _ = self.run_hook("output_author.py", payload)
        return out, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_main_write_into_an_open_round_dir_is_ledgered(self):
        self.open_receipt(self.round_dir)
        path = self.round_dir / "f.json"
        out, sha = self.file_tool("Write", path)
        self.assertEqual(out, {}, "a recorder never decides")
        [line] = self.authored()
        self.assertEqual((line["hook"], line["decision"], line["tool"]), ("output_author", "record", "Write"))
        self.assertEqual(line["path"], path.resolve().as_posix())
        self.assertEqual(line["reason"], f"author=main role=any schema=any sha256={sha}")

    def test_subagent_edit_of_a_numbered_round_output_names_the_role(self):
        # no receipt yet: the round_output file name alone marks a round dir
        path = self.round_dir / "003-verifier-verification.json"
        _, sha = self.file_tool("Edit", path, agent_type="generic-verifier", agent_id="a1")
        [line] = self.authored()
        self.assertEqual(line["reason"],
                         f"author=generic-verifier role=generic-verifier schema=verification sha256={sha}")

    def test_multiedit_by_an_unnamed_subagent_is_a_subagent(self):
        self.open_receipt(self.round_dir)
        self.file_tool("MultiEdit", self.round_dir / "notes.json", agent_id="a1")
        [line] = self.authored()
        self.assertTrue(line["reason"].startswith("author=subagent role=any "), line)

    def test_writes_outside_an_open_round_dir_record_nothing(self):
        # negative control: the repo, a finalized receipt's round dir, a file the tool did not leave
        self.open_receipt(self.tmp / "closed-round", state="finalized")
        self.file_tool("Write", self.repo / "app" / "notes.json")
        self.file_tool("Write", self.tmp / "closed-round" / "f.json")
        self.run_hook("output_author.py", {"hook_event_name": "PostToolUse", "tool_name": "Write",
                                           "tool_input": {"file_path": str(self.round_dir / "001-judge-verdict.json")}})
        self.assertEqual(self.authored(), [])


class MainAuthoredReviewReceipt(trr.ReceiptFixture):
    """rdd_receipt.capture looks the artifact's sha256 up in the hook ledger and
    freezes the author in the capture; finalize reads only the captures."""

    REASON = "review authored by the main session ({}): the author never reviews itself"

    def setUp(self):
        super().setUp()  # points METODO_HOOKS_DIR at this test's own ledger dir
        self.hooks_dir = Path(os.environ["METODO_HOOKS_DIR"])

    def authored(self, role, doc, agent_type=None, session="s1") -> Path:
        """output_write as the MCP tool does it, then the PostToolUse hook."""
        result = round_output.write_output(self.round_dir, role, doc, repo=self.repo)
        payload = {"session_id": session, "cwd": str(self.repo), "hook_event_name": "PostToolUse", "tool_name": OUTPUT_WRITE,
                   "tool_input": {"round_dir": str(self.round_dir), "role": role, "document": doc}}
        if agent_type:
            payload.update(agent_type=agent_type, agent_id=f"id-{agent_type}")
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_HOOKS_DIR=str(self.hooks_dir))
        proc = subprocess.run(["python3", str(HOOKS / "output_author.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.round_dir / Path(result["path"]).name

    def medium(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(trr.CARD_MEDIUM))
        self._capture_scripts(tree)
        return tree

    def test_main_authored_challenger_is_inconclusive(self):
        tree = self.medium()
        _, entry = rr.capture(tree, "challenger", self.authored("challenger", trr.FINDINGS_OK), self.repo)
        self.assertEqual(entry["author"], "main")
        _, entry = rr.capture(tree, "verifier", self.authored("verifier", trr.VERIFICATION_PASS, "generic-verifier"), self.repo)
        self.assertEqual(entry["author"], "generic-verifier")
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "inconclusive")
        self.assertEqual(receipt["verdict_reasons"], [self.REASON.format("generic-challenger")])
        self.assertEqual(rr.validate_receipt(rr.receipt_path(tree))["verdict"], "PASS")

    def test_main_authored_judge_is_inconclusive_even_when_not_required(self):
        # the judge can REFUTE a BROKEN finding, so a main-authored ruling would flip a rejection
        tree = self.medium()
        rr.capture(tree, "challenger", self.authored("challenger", trr.FINDINGS_ROTO, "generic-challenger"), self.repo)
        rr.capture(tree, "verifier", self.authored("verifier", trr.VERIFICATION_PASS, "generic-verifier"), self.repo)
        rr.capture(tree, "judge", self.authored("judge", trr._rulings(**{"F-02": "REFUTED"})), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual((receipt["verdict"], receipt["verdict_reasons"]), ("inconclusive", [self.REASON.format("generic-judge")]))

    def test_subagent_authored_reviews_are_approved(self):
        tree = self.medium()
        rr.capture(tree, "challenger", self.authored("challenger", trr.FINDINGS_OK, "generic-challenger"), self.repo)
        rr.capture(tree, "verifier", self.authored("verifier", trr.VERIFICATION_PASS, "generic-verifier"), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")

    def test_legacy_captures_without_authorship_are_unchanged(self):
        # negative control: no ledger, no `author` key, today's verdict
        tree = self.medium()
        _, entry = rr.capture(tree, "challenger", self._artifact("f.json", trr.FINDINGS_OK), self.repo)
        self.assertNotIn("author", entry)
        rr.capture(tree, "verifier", self._artifact("v.json", trr.VERIFICATION_PASS), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")

    # T18 (B-005/A-006)
    def written(self, name, doc, agent_type=None, tool="Write", session="s1") -> Path:
        """A review output written with the file tool, then the PostToolUse hook."""
        path = self.round_dir / name
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        payload = {"session_id": session, "cwd": str(self.repo), "hook_event_name": "PostToolUse", "tool_name": tool,
                   "tool_input": {"file_path": str(path)}}
        if agent_type:
            payload.update(agent_type=agent_type, agent_id=f"id-{agent_type}")
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_HOOKS_DIR=str(self.hooks_dir))
        proc = subprocess.run(["python3", str(HOOKS / "output_author.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return path

    def test_a_challenger_output_the_main_session_wrote_by_hand_is_inconclusive(self):
        tree = self.medium()
        _, entry = rr.capture(tree, "challenger", self.written("f.json", trr.FINDINGS_OK), self.repo)
        self.assertEqual(entry["author"], "main")
        rr.capture(tree, "verifier", self.written("v.json", trr.VERIFICATION_PASS, "generic-verifier", "Edit"), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual((receipt["verdict"], receipt["verdict_reasons"]), ("inconclusive", [self.REASON.format("generic-challenger")]))

    def test_an_unknown_author_is_flagged_on_the_receipt_not_made_inconclusive(self):
        import contextlib
        import io
        tree = self.medium()
        rr.capture(tree, "challenger", self._artifact("f.json", trr.FINDINGS_OK), self.repo)   # e.g. written by Bash
        rr.capture(tree, "verifier", self.authored("verifier", trr.VERIFICATION_PASS, "generic-verifier"), self.repo)
        status = rr.status(self.repo, config=trr.CONFIG)
        self.assertEqual(status["receipt"]["author_unknown"], ["generic-challenger"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(rr.main(["finalize", "--tree", tree]), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual((out["verdict"], out["author_unknown"]), ("approved", ["generic-challenger"]))
        self.assertEqual(rr.load_receipt(tree)["author_unknown"], ["generic-challenger"])
        self.assertEqual(rr.validate_receipt(rr.receipt_path(tree))["verdict"], "PASS")

    def test_known_authors_leave_no_flag(self):
        # negative control
        tree = self.medium()
        rr.capture(tree, "challenger", self.authored("challenger", trr.FINDINGS_OK, "generic-challenger"), self.repo)
        rr.capture(tree, "verifier", self.authored("verifier", trr.VERIFICATION_PASS, "generic-verifier"), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "approved")
        self.assertNotIn("author_unknown", receipt)

    def test_review_roles_are_the_routers(self):
        self.assertEqual(tuple(rr.REVIEW_ROLES), tuple(router.REVIEW_ROLES))

    def test_legacy_receipt_file_without_author_finalizes_as_before(self):
        tree = self.medium()
        rr.capture(tree, "challenger", self.authored("challenger", trr.FINDINGS_OK), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", trr.VERIFICATION_PASS), self.repo)
        receipt = rr.load_receipt(tree)
        for entry in receipt["captures"]:
            entry.pop("author", None)          # a receipt written before T7
        rr.save_receipt(receipt)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")


if __name__ == "__main__":
    unittest.main()
