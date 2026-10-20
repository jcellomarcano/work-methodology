"""validate_subagent_output.py beyond the schema shape (context-method §3, D9):
the report cap (2,000 tokens = ceil(chars / 4)), the optional per-S# verdicts
(spec_verdicts) and the context_tokens_used measurement against the role
contract's max_context_tokens. Each case runs the hook as a subprocess over a
temporary git repo, config and ledger directory."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import findings_schema_validator as fsv

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOK = TOOLS_ROOT / "hooks" / "validate_subagent_output.py"

FINDINGS = {"round": "r", "role": "challenger", "summary": "ok", "findings": [
    {"id": "F-01", "lens": "simplicity", "claim": "c", "attack": "a", "failure_scenario": "f", "evidence": ["x.kt:1"],
     "verdict": "OK", "epistemic": "Tested", "simpler_alternative": "none"}]}
CONTEXT_CAP = 60000


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def sized_reply(chars: int) -> str:
    """A schema-valid findings reply that is exactly `chars` characters long."""
    base = json.dumps(dict(FINDINGS, summary=""))
    reply = json.dumps(dict(FINDINGS, summary="x" * (chars - len(base))))
    assert len(reply) == chars, (len(reply), chars)
    return reply


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="validate-output-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        agents = self.repo / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "generic-challenger.contract.json").write_text(json.dumps(
            {"agent": "generic-challenger", "may_write": [], "max_tool_calls": 40, "max_context_tokens": CONTEXT_CAP}),
            encoding="utf-8")
        self.hooks_dir = self.tmp / "hooks-out"
        self.config_path = self.tmp / "project.json"
        self.set_mode("warn")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_mode(self, mode):
        self.config_path.write_text(json.dumps({"rdd": {"enabled": True, "mode": mode, "hook_modes": {}}}), encoding="utf-8")

    def run_hook(self, message, **extra):
        payload = {"session_id": "s1", "cwd": str(self.repo), "hook_event_name": "SubagentStop",
                   "agent_type": "generic-challenger", "agent_id": "a9", "last_assistant_message": message, **extra}
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_path),
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.tmp / "rdd"), CLAUDE_PROJECT_DIR=str(self.repo))
        proc = subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        lines = proc.stdout.strip().splitlines()
        self.assertLessEqual(len(lines), 1, proc.stdout)  # one stop decision at most, always parseable
        return json.loads(lines[0]) if lines else {}

    def ledger(self):
        path = self.hooks_dir / "s1" / "ledger.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def kinds(self):
        return [(l["kind"], l["decision"]) for l in self.ledger()]


class ReportCapTests(Fixture):
    def test_cap_is_two_thousand_tokens_of_four_chars(self):
        self.assertEqual(fsv.REPORT_CAP_TOKENS, 2000)
        self.assertEqual(fsv.report_tokens("x" * 8000), 2000)
        self.assertEqual(fsv.report_tokens("x" * 8001), 2001)
        self.assertEqual(fsv.report_tokens(""), 0)

    def test_report_at_exactly_the_cap_is_silent(self):
        # negative control: 8,000 chars = 2,000 tokens is inside the cap
        self.set_mode("block")
        self.assertEqual(self.run_hook(sized_reply(8000)), {})
        self.assertEqual(self.ledger(), [])

    def test_report_one_token_over_the_cap_is_recorded_in_warn(self):
        self.assertEqual(self.run_hook(sized_reply(8001)), {})
        self.assertEqual(self.kinds(), [("report-over-cap", "warn")])
        self.assertIn("2001", self.ledger()[-1]["reason"])

    def test_block_mode_blocks_once_with_the_handoff_fix_then_lets_through(self):
        self.set_mode("block")
        out = self.run_hook(sized_reply(8001))
        self.assertEqual(out["decision"], "block")
        self.assertIn("mcp__metodo__handoff_write", out["reason"])
        self.assertIn("2,000 tokens", out["reason"])
        self.assertEqual(self.kinds(), [("report-over-cap", "block")])
        self.assertEqual(self.run_hook(sized_reply(8001)), {})
        self.assertEqual(self.kinds()[-1], ("report-over-cap", "over-cap-let-through"))

    def test_runtime_that_cannot_block_records_unenforced(self):
        self.set_mode("block")
        self.assertEqual(self.run_hook(sized_reply(9000), runtime_can_block=False), {})
        self.assertEqual(self.kinds(), [("report-over-cap", "over-cap-unenforced")])
        self.assertEqual(list((self.hooks_dir / "s1").glob("*blocked*")), [])

    def test_invalid_and_over_cap_give_one_block_naming_both(self):
        self.set_mode("block")
        out = self.run_hook("prose " * 2000)
        self.assertEqual(out["decision"], "block")
        self.assertIn("schema", out["reason"])
        self.assertIn("mcp__metodo__handoff_write", out["reason"])
        self.assertEqual(self.kinds(), [("output-invalid", "block"), ("report-over-cap", "block")])

    def test_truncated_report_over_the_cap_is_still_reported(self):
        reply = json.dumps(dict(FINDINGS, truncated=True, not_covered=["C"], summary="x" * 8000))
        self.assertEqual(self.run_hook(reply), {})
        self.assertEqual(self.kinds(), [("output-truncated", "log"), ("report-over-cap", "warn")])


class SpecVerdictsInReplyTests(Fixture):
    def test_valid_spec_verdicts_pass_silently(self):
        reply = dict(FINDINGS, spec_verdicts=[{"spec": "S4", "verdict": "PASS", "evidence": "tests/x.py:1"},
                                              {"spec": "S12", "verdict": "NOT_COVERED"}])
        self.assertEqual(self.run_hook(json.dumps(reply)), {})
        self.assertEqual(self.ledger(), [])

    def test_malformed_spec_verdict_is_an_invalid_output(self):
        reply = dict(FINDINGS, spec_verdicts=[{"spec": "4", "verdict": "met"}])
        self.assertEqual(self.run_hook(json.dumps(reply)), {})
        self.assertEqual(self.kinds(), [("output-invalid", "warn")])
        self.assertIn("spec_verdicts", self.ledger()[-1]["reason"])


class ContextOverCapTests(Fixture):
    def test_context_over_the_contract_cap_is_logged_never_blocked(self):
        self.set_mode("block")
        out = self.run_hook(json.dumps(dict(FINDINGS, context_tokens_used=CONTEXT_CAP + 1)))
        self.assertEqual(out, {})
        self.assertEqual(self.kinds(), [("context-over-cap", "log")])
        self.assertIn(str(CONTEXT_CAP + 1), self.ledger()[-1]["reason"])

    def test_context_at_the_cap_or_absent_is_silent(self):
        # negative controls: exactly at the cap, and no field at all
        for doc in (dict(FINDINGS, context_tokens_used=CONTEXT_CAP), FINDINGS):
            self.assertEqual(self.run_hook(json.dumps(doc)), {})
        self.assertEqual(self.ledger(), [])

    def test_context_without_a_contract_cap_is_silent(self):
        (self.repo / ".claude" / "agents" / "generic-challenger.contract.json").write_text(
            json.dumps({"agent": "generic-challenger", "may_write": []}), encoding="utf-8")
        self.assertEqual(self.run_hook(json.dumps(dict(FINDINGS, context_tokens_used=10 ** 9))), {})
        self.assertNotIn("context-over-cap", [k for k, _ in self.kinds()])

    def test_non_integer_context_tokens_is_a_shape_error(self):
        self.assertEqual(self.run_hook(json.dumps(dict(FINDINGS, context_tokens_used="lots"))), {})
        self.assertEqual(self.kinds(), [("output-invalid", "warn")])


class ExistingOutputsTests(Fixture):
    def test_reply_without_the_new_fields_still_passes_in_block(self):
        self.set_mode("block")
        self.assertEqual(self.run_hook(json.dumps(FINDINGS)), {})
        self.assertEqual(self.ledger(), [])


if __name__ == "__main__":
    unittest.main()
