"""hooks/done_gate.py (T14, WU17; done-gate.md section 4, owner decision D2)
and bin/done-waive.sh, driven as subprocesses over the HookFixture repo.

Stop (main session) and SubagentStop (writer roles only) read the final
message; no done claim, silent; a claim with missing proof, the DONE-GATE
block reaches the owner as `systemMessage` (warn first). A rule whose mode in
done-gate.json is BLOCK sends the agent back once per worktree_sha
(`decision: block`); the next stop on the same worktree is let through and
ledgered `done-unproven`. An owner waiver (done-waive.sh) clears a rule
until the tree changes."""
import json
import os
import subprocess
import unittest
from pathlib import Path

from lib import run_check
from tests.test_hooks import HookFixture

TOOLS_ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((TOOLS_ROOT / "config" / "done-gate.json").read_text(encoding="utf-8"))
WAIVE = TOOLS_ROOT / "bin" / "done-waive.sh"


class DoneGateFixture(HookFixture):
    def setUp(self):
        super().setUp()
        self.runs = self.tmp / "runs-dir" / "runs.jsonl"
        self.gate_config = self.tmp / "done-gate.json"  # beside project.json: the hook reads it there

    def block_rules(self, *rule_ids):
        config = json.loads(json.dumps(CONFIG))
        for rule_id in rule_ids:
            config["rules"][rule_id]["mode"] = "BLOCK"
        self.gate_config.write_text(json.dumps(config), encoding="utf-8")

    def edit(self, text="class Foo { val x = 1 }\n"):
        (self.repo / "app" / "Foo.kt").write_text(text, encoding="utf-8")

    def add_run(self, name="app", exit_code=0):
        self.runs.parent.mkdir(parents=True, exist_ok=True)
        lines = self.runs.read_text(encoding="utf-8").splitlines() if self.runs.exists() else []
        record = dict(run_check.worktree_fingerprint(self.repo), repo=str(run_check.repo_root(self.repo)),
                      argv=["./gradlew", "test"], cwd=".", elapsed_ms=1,
                      exit=exit_code, log=f"{len(lines) + 1}.log", name=name, output_sha256="0" * 64, schema_version=1,
                      seq=len(lines) + 1)
        with self.runs.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def stop(self, message, session="s1", event="Stop", **extra):
        payload = {"hook_event_name": event, "last_assistant_message": message, "stop_hook_active": False, **extra}
        return self.run_hook("done_gate.py", payload, session=session, env_extra={"METODO_RUNS_DIR": str(self.runs.parent)})

    def gate_lines(self, session="s1"):
        return [l for l in self.ledger(session) if l["hook"] == "done_gate"]

    def waive(self, *args, session="s1", cwd=None):
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_HOOKS_DIR=str(self.hooks_dir))
        return subprocess.run(["bash", str(WAIVE), *args, "--session", session], cwd=str(cwd or self.repo),
                              capture_output=True, text=True, env=env, timeout=60)


class StopWarnFirstTests(DoneGateFixture):
    def test_no_claim_is_silent_and_leaves_no_trace(self):
        self.edit()
        out, proc = self.stop("Which option do you prefer, A or B?")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.gate_lines(), [])

    def test_claim_with_nothing_to_prove_is_silent(self):
        # negative control: a clean tree and a claim every rule passes or skips
        out, proc = self.stop("Done.")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.gate_lines(), [])

    def test_claim_with_missing_proof_is_a_visible_warn_never_a_block(self):
        self.edit()
        out, _ = self.stop("Done, the change is finished.")
        self.assertNotIn("decision", out)
        self.assertNotIn("hookSpecificOutput", out)
        text = out["systemMessage"]
        self.assertRegex(text.splitlines()[0], r"^DONE-GATE: BLOCK 0 · FLAG \d+ · tree [0-9a-f]{7} · tool [0-9a-f]{7}$")
        self.assertIn("- DONE-02 FLAG ", text)
        line = self.gate_lines()[-1]
        self.assertEqual((line["kind"], line["decision"], line["mode"], line["event"]), ("done-gate", "warn", "warn", "Stop"))
        self.assertIn("DONE-02:FLAG", line["reason"])
        self.assertEqual(line["tree"], self.tree)

    def test_every_fire_is_ledgered_with_its_rule_ids(self):
        self.edit()
        self.stop("Done.")
        self.stop("Done.")
        lines = self.gate_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("DONE-02:FLAG" in l["reason"] for l in lines))

    def test_rdd_off_and_hook_mode_off_are_silent(self):
        self.edit()
        self.set_config(enabled=False)
        self.assertEqual(self.stop("Done.")[1].stdout, "")
        self.set_config(enabled=True, mode="warn", hook_modes={"done_gate": "off"})
        self.assertEqual(self.stop("Done.")[1].stdout, "")
        self.assertEqual(self.gate_lines(), [])

    def test_log_mode_records_without_showing(self):
        self.edit()
        self.set_config(enabled=True, mode="warn", hook_modes={"done_gate": "log"})
        out, proc = self.stop("Done.")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.gate_lines()[-1]["decision"], "log")

    def test_rdd_block_mode_never_blocks_a_flag_rule(self):
        # D2: blocking is per rule (done-gate.json), never from the profile or rdd.mode
        self.edit()
        self.set_config(enabled=True, mode="block")
        out, _ = self.stop("Done.")
        self.assertNotIn("decision", out)
        self.assertIn("systemMessage", out)


class BlockOncePerWorktreeTests(DoneGateFixture):
    def test_block_rule_blocks_once_then_lets_the_stop_through_as_done_unproven(self):
        self.block_rules("DONE-02")
        self.edit()
        out, _ = self.stop("Done.")
        self.assertEqual(out["decision"], "block")
        self.assertTrue(out["reason"].startswith("DONE-GATE: BLOCK 1 · "), out["reason"])
        self.assertIn("- DONE-02 BLOCK ", out["reason"])
        self.assertEqual(self.gate_lines()[-1]["decision"], "block")
        out, _ = self.stop("Done, as I said.")
        self.assertNotIn("decision", out)
        self.assertTrue(out["systemMessage"].startswith("DONE-GATE: BLOCK 1 · "))
        line = self.gate_lines()[-1]
        self.assertEqual((line["kind"], line["decision"]), ("done-unproven", "let-through"))
        self.assertIn("DONE-02:BLOCK", line["reason"])

    def test_a_new_worktree_blocks_again(self):
        self.block_rules("DONE-02")
        self.edit()
        self.stop("Done.")
        self.edit("class Foo { val x = 2 }\n")
        out, _ = self.stop("Done.")
        self.assertEqual(out.get("decision"), "block")

    def test_stop_hook_active_lets_it_through(self):
        self.block_rules("DONE-02")
        self.edit()
        out, _ = self.stop("Done.", stop_hook_active=True)
        self.assertNotIn("decision", out)
        self.assertEqual(self.gate_lines()[-1]["kind"], "done-unproven")

    def test_a_green_run_clears_the_block_rule(self):
        self.block_rules("DONE-02")
        self.edit()
        self.add_run()
        out, _ = self.stop("Done.")
        self.assertNotIn("decision", out)


class OwnerWaiverTests(DoneGateFixture):
    def test_done_waive_writes_the_waiver_record_with_the_current_fingerprint(self):
        self.edit()
        (self.hooks_dir / "s1").mkdir(parents=True)
        proc = self.waive("DONE-02", "--reason", "suite runs in CI")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        fp = run_check.worktree_fingerprint(self.repo)
        line = self.ledger()[-1]
        self.assertEqual({k: line[k] for k in ("kind", "rule", "tree_sha", "worktree_sha", "reason", "email")},
                         {"kind": "done-waiver", "rule": "DONE-02", "tree_sha": fp["tree_sha"],
                          "worktree_sha": fp["worktree_sha"], "reason": "suite runs in CI", "email": "t@example.com"})

    def test_waiver_is_honored_and_dies_when_the_tree_changes(self):
        self.block_rules("DONE-02")
        self.edit()
        self.waive("DONE-02", "--reason", "suite runs in CI")
        out, _ = self.stop("Done.")
        self.assertNotIn("decision", out)
        self.assertIn("- DONE-02 WAIVED by t@example.com: suite runs in CI", out["systemMessage"].splitlines())
        self.edit("class Foo { val x = 3 }\n")
        out, _ = self.stop("Done.")
        self.assertEqual(out.get("decision"), "block")

    def test_usage_errors_write_nothing(self):
        (self.hooks_dir / "s1").mkdir(parents=True)
        for args in (("DONE-99", "--reason", "x"), ("DONE-02",), ("DONE-02", "--reason", "  "), ("DONE-01", "--reason", "x")):
            with self.subTest(args=args):
                self.assertEqual(self.waive(*args).returncode, 2)
        self.assertEqual(self.ledger(), [])


class WriterSubagentStopTests(DoneGateFixture):
    WRITER = {"agent_type": "generic-proposer", "agent_id": "w1"}

    def test_writer_claim_with_missing_proof_warns(self):
        self.edit()
        out, _ = self.stop("status: completed\nsummary: done", event="SubagentStop", **self.WRITER)
        self.assertIn("DONE-02 FLAG", out["systemMessage"])
        line = self.gate_lines()[-1]
        self.assertEqual((line["event"], line["agent_type"], line["decision"]), ("SubagentStop", "generic-proposer", "warn"))

    def test_schema_valid_json_writer_returns_are_claims(self):
        # B-002: the writer roles return schema JSON, so every prose value sits in double quotes
        from lib import findings_schema_validator
        returns = {
            ("generic-proposer", "proposer"): {
                "change_card_id": "C-1", "files_changed": ["app/Foo.kt"], "handoff_to": ["generic-challenger"],
                "build": {"variant": "debug", "task": "test", "result": "PASS"},
                "role_contract_validation": {"verdict": "PASS"},
                "status": "completed", "summary": "Foo wired; all tests pass, committed abc1234"},
            ("generic-mechanic", "mechanic"): {
                "fix_id": "F-1", "applied": True, "files_changed": ["app/Foo.kt"],
                "status": "completed", "summary": "all tests pass"},
        }
        for (role, schema_name), ret in returns.items():
            with self.subTest(role=role):
                schema = json.loads((TOOLS_ROOT / "schemas" / f"{schema_name}-output.schema.json").read_text(encoding="utf-8"))
                self.assertEqual(findings_schema_validator.validate(ret, schema)["verdict"], "PASS")
                self.edit(f"class Foo {{ val role = \"{role}\" }}\n")
                out, _ = self.stop(json.dumps(ret, indent=2), event="SubagentStop", agent_type=role, agent_id=role)
                self.assertIn("- DONE-02 FLAG ", out["systemMessage"])
                line = self.gate_lines()[-1]
                self.assertEqual((line["event"], line["agent_type"]), ("SubagentStop", role))
                self.assertIn("claims committed,done,green" if "committed" in ret["summary"] else "claims done,green",
                              line["reason"])

    def test_non_writer_roles_are_not_checked(self):
        self.edit()
        out, proc = self.stop("Done.", event="SubagentStop", agent_type="generic-challenger", agent_id="c1")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.gate_lines(), [])

    def test_writer_block_rule_blocks_once(self):
        self.block_rules("DONE-02")
        self.edit()
        out, _ = self.stop("Done.", event="SubagentStop", **self.WRITER)
        self.assertEqual(out["decision"], "block")
        out, _ = self.stop("Done.", event="SubagentStop", **self.WRITER)
        self.assertNotIn("decision", out)

    def test_runtime_that_cannot_block_records_it_unenforced(self):
        self.block_rules("DONE-02")
        self.edit()
        out, _ = self.stop("Done.", event="SubagentStop", runtime_can_block=False, **self.WRITER)
        self.assertNotIn("decision", out)
        line = self.gate_lines()[-1]
        self.assertEqual((line["kind"], line["decision"]), ("done-unproven", "unenforced"))
        self.assertEqual(list((self.hooks_dir / "s1").glob("done-gate-blocked-*")), [])


class TimeBudgetTests(DoneGateFixture):
    """A-008: the hook gives done_check one budget below its own 30 s timeout;
    a check that runs out of it is a visible FLAG "timed out", never silence."""

    def test_a_slow_check_is_a_timed_out_flag_inside_the_budget(self):
        import time
        (self.repo / "01-roles").mkdir()
        (self.repo / "01-roles" / "r.md").write_text("role\n", encoding="utf-8")
        (self.repo / "03-tools" / "lib").mkdir(parents=True)
        (self.repo / "03-tools" / "lib" / "kit_status.py").write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
        config = json.loads(json.dumps(CONFIG))
        config["hook_time_budget_s"] = 2
        self.gate_config.write_text(json.dumps(config), encoding="utf-8")
        self.edit()
        start = time.monotonic()
        out, _ = self.stop("Done, the change is finished.")
        self.assertLess(time.monotonic() - start, 10)
        lines = out["systemMessage"].splitlines()
        self.assertTrue(any(l.startswith("- DONE-06 FLAG ") and "timed out" in l for l in lines), lines)
        self.assertIn("DONE-06:FLAG", self.gate_lines()[-1]["reason"])


class ActivationProfileTests(DoneGateFixture):
    """T14 item 4: done_gate is an activation element; OFF in bare/light, WARN from scripts up."""

    def with_tier(self, tier):
        import shutil
        shutil.copyfile(TOOLS_ROOT / "config" / "activation.json", self.tmp / "activation.json")
        self.write_receipt(verdict=None, state="started")
        path = self.rdd_dir / f"{self.tree}.receipt.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["risk"]["tier"] = tier
        path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_light_profile_keeps_the_gate_silent(self):
        self.with_tier("exempt")
        self.edit()
        out, proc = self.stop("Done, the change is finished.")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.gate_lines(), [])

    def test_standard_profile_warns(self):
        self.with_tier("medium")
        self.edit()
        out, _ = self.stop("Done, the change is finished.")
        self.assertTrue(out["systemMessage"].startswith("DONE-GATE: "))
        self.assertEqual(self.gate_lines()[-1]["mode"], "warn")

    def test_full_profile_in_block_mode_still_only_warns_on_flag_rules(self):
        self.set_config(enabled=True, mode="block")
        self.with_tier("high")
        self.edit()
        out, _ = self.stop("Done, the change is finished.")
        self.assertNotIn("decision", out)
        self.assertIn("systemMessage", out)


if __name__ == "__main__":
    unittest.main()
