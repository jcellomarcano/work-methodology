"""hooks/pi/metodo-hooks.ts driven through node with a fake pi API object.

The extension is the pi adapter for the same Python hooks Claude Code runs.
Each test spawns one node process (one pi process = one subagent under
gentle-pi), feeds it pi events (tool_call, tool_result, before_agent_start,
agent_end) and reads back what the extension returned plus what the Python
hooks wrote in the ledger. node >= 22.6 strips the TypeScript types; the
suite skips when no such node is on PATH.

What this proves and what it does not: the fake pi API only carries the
event fields the extension reads. Whether a real pi delivers each field
(e.g. before_agent_start.systemPrompt) is not proven here."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_hooks import HookFixture

TOOLS_ROOT = Path(__file__).resolve().parent.parent
EXTENSION = TOOLS_ROOT / "hooks" / "pi" / "metodo-hooks.ts"
SETTINGS = TOOLS_ROOT / "hooks" / "hooks.settings.json"

HARNESS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const script = JSON.parse(readFileSync(0, "utf8"));
const mod = await import(pathToFileURL(process.argv[2]).href);
const handlers = {};
mod.default({ on(name, fn) { (handlers[name] ||= []).push(fn); } });
const notes = [];
const ctx = {
  hasUI: !!script.hasUI,
  sessionManager: { getSessionFile: () => script.sessionFile ?? undefined },
  ui: { notify: (m, l) => notes.push([l, m]), confirm: async () => !!script.confirm },
};
const results = [];
for (const step of script.steps || []) {
  let result = null;
  for (const fn of handlers[step.event] || []) {
    const r = await fn(step.payload || {}, ctx);
    if (r !== undefined) result = r;
  }
  results.push(result);
}
console.log(JSON.stringify({ results, notes, matrix: mod.HOOK_MATRIX ?? null }));
"""


def _node_strips_types() -> list[str] | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"v(\d+)\.(\d+)", version)
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    if (major, minor) < (22, 6):
        return None
    # Type stripping is on by default from 23.6; before that it needs the flag.
    return [node] if (major, minor) >= (23, 6) else [node, "--experimental-strip-types"]


NODE = _node_strips_types()
PROPOSER_PROMPT_MARKER = "<!-- metodo-role: generic-proposer -->"


@unittest.skipUnless(NODE, "needs node >= 22.6 to run the pi extension's TypeScript")
class PiExtensionFixture(HookFixture):
    def setUp(self):
        super().setUp()
        self.harness = self.tmp / "harness.mjs"
        self.harness.write_text(HARNESS, encoding="utf-8")

    def run_ext(self, steps, child=False, role=None, session_file=None, has_ui=False):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GENTLE_PI_", "PI_", "METODO_")) and k != "CLAUDE_PROJECT_DIR"}
        env.update(METODO_TOOLS=str(TOOLS_ROOT), METODO_REPO=str(self.repo), METODO_PROJECT_CONFIG=str(self.config_path),
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.rdd_dir), METODO_MEMORY="off",
                   METODO_ROUTING_LOG=str(self.routing_log))
        if child:
            env["GENTLE_PI_AGENTS_CHILD"] = "1"
        if role:
            env["METODO_AGENT_TYPE"] = role
        body = {"steps": steps, "sessionFile": session_file, "hasUI": has_ui}
        proc = subprocess.run([*NODE, str(self.harness), str(EXTENSION)], input=json.dumps(body),
                              capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    @staticmethod
    def call(tool_name, /, **tool_input):
        return {"event": "tool_call", "payload": {"toolName": tool_name, "input": tool_input}}

    @staticmethod
    def result(tool_name, /, **tool_input):
        return {"event": "tool_result", "payload": {"toolName": tool_name, "input": tool_input}}

    @staticmethod
    def end(text):
        return {"event": "agent_end", "payload": {"messages": [
            {"role": "user", "content": "go"}, {"role": "assistant", "content": [{"type": "text", "text": text}]}]}}

    def pi_ledger(self):
        return self.ledger(session="pi-ephemeral")


class ReceiptToolsReachGuardGates(PiExtensionFixture):
    """Gap (a): on Claude Code the guard_gates matcher includes the three
    receipt MCP tools; on pi they must reach the same script."""

    def test_subagent_receipt_tools_are_denied(self):
        for tool in ("mcp__metodo__receipt_start", "mcp__metodo__receipt_finalize", "mcp__metodo__receipt_acknowledge"):
            with self.subTest(tool=tool):
                out = self.run_ext([self.call(tool, tree="x")], child=True)
                self.assertTrue((out["results"][0] or {}).get("block"), out)
        kinds = [(l["hook"], l["kind"], l["decision"]) for l in self.pi_ledger()]
        self.assertEqual(kinds.count(("guard_gates", "gate-receipt", "deny")), 3)

    def test_subagent_receipt_through_the_mcp_proxy_is_denied(self):
        out = self.run_ext([self.call("mcp", tool="metodo_receipt_finalize", args={"tree": "x"})], child=True)
        self.assertTrue((out["results"][0] or {}).get("block"), out)
        self.assertEqual(self.pi_ledger()[0]["kind"], "gate-receipt")

    def test_proxy_receipt_name_variants_are_denied(self):
        # verifier advisory 2: separators, case, padding and nesting must not escape the gate
        variants = [{"tool": "metodo/receipt_start"}, {"tool": "metodo.receipt_finalize"},
                    {"tool": "metodo:receipt_acknowledge"}, {"tool": "metodo-receipt-start"},
                    {"tool": "METODO_RECEIPT_FINALIZE "}, {"request": {"name": "metodo__receipt_start"}}]
        for tool_input in variants:
            with self.subTest(tool_input=tool_input):
                out = self.run_ext([self.call("mcp", **tool_input)], child=True)
                self.assertTrue((out["results"][0] or {}).get("block"), out)

    def test_proxy_names_that_only_contain_receipt_words_are_not_gated(self):
        # negative control: a longer word is not a receipt tool
        out = self.run_ext([self.call("mcp", tool="metodo_receipt_starts"), self.call("mcp", tool="metodo_receipt_status")], child=True)
        self.assertEqual(out["results"], [None, None])

    def test_owner_receipt_tool_is_allowed_and_ledgered(self):
        out = self.run_ext([self.call("mcp__metodo__receipt_start", tree="x")])
        self.assertIsNone(out["results"][0])
        line = self.pi_ledger()[-1]
        self.assertEqual((line["kind"], line["decision"], line["agent_id"]), ("gate-receipt", "allow", ""))

    def test_other_mcp_tools_do_not_reach_guard_gates(self):
        # negative control: only the three receipt tools are gates
        out = self.run_ext([self.call("mcp__metodo__docs_lint"), self.call("mcp", tool="metodo_docs_lint")], child=True)
        self.assertEqual(out["results"], [None, None])
        self.assertEqual(self.pi_ledger(), [])


class BudgetPerSubagent(PiExtensionFixture):
    """Gap (b): the counter is per subagent, never shared between two pi
    processes, even when both resolve to the same session id."""

    def counters(self):
        return sorted(p.name for p in (self.hooks_dir / "pi-ephemeral").glob("budget-*.count"))

    def test_two_subagents_get_separate_counters(self):
        a = self.run_ext([self.call("read", path="app/Foo.kt")] * 3, child=True, role="generic-proposer")
        b = self.run_ext([self.call("read", path="app/Foo.kt")] * 3, child=True, role="generic-proposer")
        self.assertEqual(a["results"] + b["results"], [None] * 6, "the cap is 3 per subagent, not per session")
        counters = self.counters()
        self.assertEqual(len(counters), 2, counters)
        self.assertTrue(all(c.startswith("budget-generic-proposer-pi-") for c in counters), counters)
        for name in counters:
            self.assertEqual((self.hooks_dir / "pi-ephemeral" / name).read_text().strip(), "3")

    def test_one_subagent_is_denied_past_its_cap(self):
        out = self.run_ext([self.call("read", path="app/Foo.kt")] * 4, child=True, role="generic-proposer")
        self.assertEqual(out["results"][:3], [None] * 3)
        self.assertTrue(out["results"][3]["block"])
        self.assertIn("truncated:true", out["results"][3]["reason"])

    def test_every_tool_counts_like_claude_code(self):
        # budget.py has matcher "" on Claude Code: MCP and non-built-in tools count too
        out = self.run_ext([self.call("mcp__metodo__docs_lint"), self.call("mem_save"), self.call("mcp", tool="metodo_job_status"),
                            self.call("read", path="a")], child=True, role="generic-proposer")
        self.assertTrue(out["results"][3]["block"], out)

    def test_role_comes_from_the_rendered_marker(self):
        prompt = {"event": "before_agent_start", "payload": {"prompt": "go", "systemPrompt": "You are...\n" + PROPOSER_PROMPT_MARKER}}
        out = self.run_ext([prompt] + [self.call("read", path="a")] * 4, child=True)
        self.assertTrue(out["results"][4]["block"], out)

    @unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
    def test_role_comes_from_the_real_rendered_agent(self):
        # the link render_agents.py -> extension, with the kit's own generic-proposer
        import sys
        sys.path.insert(0, str(TOOLS_ROOT))
        from lib import render_agents
        body = render_agents.render(TOOLS_ROOT.parent / "01-roles" / "agents" / "generic-proposer.md", "pi", "/opt/tools")
        prompt = {"event": "before_agent_start", "payload": {"prompt": "go", "systemPrompt": body}}
        out = self.run_ext([prompt] + [self.call("read", path="a")] * 4, child=True)
        self.assertTrue(out["results"][4]["block"], out)

    def test_first_role_found_stays(self):
        first = {"event": "before_agent_start", "payload": {"systemPrompt": PROPOSER_PROMPT_MARKER}}
        second = {"event": "before_agent_start", "payload": {"systemPrompt": "<!-- metodo-role: generic-challenger -->"}}
        out = self.run_ext([first, second] + [self.call("read", path="a")] * 4, child=True)
        self.assertTrue(out["results"][5]["block"], out)

    def test_last_marker_in_the_system_prompt_wins(self):
        # verifier advisory 1: context files come before the agent body, whose marker is its last line
        system = "AGENTS.md says <!-- metodo-role: generic-challenger -->\n...\n" + PROPOSER_PROMPT_MARKER
        prompt = {"event": "before_agent_start", "payload": {"prompt": "go", "systemPrompt": system}}
        out = self.run_ext([prompt] + [self.call("read", path="a")] * 4, child=True)
        self.assertTrue(out["results"][4]["block"], out)

    def test_marker_in_the_task_prompt_does_not_pick_the_role(self):
        # negative control: the task text is not a role source
        prompt = {"event": "before_agent_start", "payload": {"prompt": PROPOSER_PROMPT_MARKER, "systemPrompt": "no marker"}}
        out = self.run_ext([prompt] + [self.call("read", path="a")] * 4, child=True)
        self.assertEqual(out["results"][1:], [None] * 4)

    def test_owner_session_is_never_counted(self):
        # negative control: the owner has no agent_id, budget.py exits at once
        out = self.run_ext([self.call("read", path="a")] * 5, role="generic-proposer")
        self.assertEqual(out["results"], [None] * 5)
        self.assertFalse(self.hooks_dir.exists())

    def test_unsafe_role_values_are_ignored(self):
        out = self.run_ext([self.call("read", path="a")] * 4, child=True, role="../../etc/generic-proposer")
        self.assertEqual(out["results"], [None] * 4)


class OutputValidatedOnClose(PiExtensionFixture):
    """Gap (c): a schema-bearing subagent's final reply is validated at
    agent_end, as SubagentStop does on Claude Code."""

    def test_invalid_output_is_ledgered(self):
        self.run_ext([self.end("I attacked the claims and found nothing.")], child=True, role="generic-challenger")
        line = self.pi_ledger()[-1]
        self.assertEqual((line["hook"], line["kind"], line["decision"], line["agent_type"]),
                         ("validate_subagent_output", "output-invalid", "warn", "generic-challenger"))
        self.assertTrue(line["agent_id"].startswith("pi-"))

    def test_block_mode_is_recorded_as_unenforced_not_as_a_block(self):
        self.set_config(enabled=True, mode="block")
        self.run_ext([self.end("prose")], child=True, role="generic-challenger")
        line = self.pi_ledger()[-1]
        self.assertEqual((line["kind"], line["decision"]), ("output-invalid", "invalid-unenforced"))
        self.assertEqual(list((self.hooks_dir / "pi-ephemeral").glob("output-blocked-*")), [])

    def test_valid_output_passes_silently(self):
        from tests.test_hooks import FINDINGS
        self.run_ext([self.end(json.dumps(FINDINGS))], child=True, role="generic-challenger")
        self.assertEqual(self.pi_ledger(), [])

    def test_owner_reply_is_not_validated(self):
        # negative control: the owner's reply is not schema-checked
        self.run_ext([self.end("prose")], role="generic-challenger")
        self.assertEqual([l for l in self.pi_ledger() if l["hook"] == "validate_subagent_output"], [])

    def test_owner_reply_runs_no_reply_lint(self):
        # T1 (D3): the Stop-time reply lint is off on pi too
        text = "Vale, entonces te cuento: " + "una frase larga que no dice nada concreto y sigue " * 12
        self.run_ext([self.end(text)])
        self.assertEqual([l for l in self.pi_ledger() if l["hook"] == "reply_lint"], [])


class DoneGateOnAgentEnd(PiExtensionFixture):
    """T14: done_gate.py runs at agent_end, as Stop (owner) and SubagentStop
    (writer roles) do on Claude Code. pi cannot send the agent back after
    agent_end, so it records only (runtime_can_block false); the owner's
    DONE-GATE block is handed to the next turn like a warn."""

    START = {"event": "before_agent_start", "payload": {"prompt": "next", "systemPrompt": "no marker"}}

    def setUp(self):
        super().setUp()
        (self.repo / "app" / "Foo.kt").write_text("class Foo { val x = 1 }\n", encoding="utf-8")

    def gate_lines(self):
        return [l for l in self.pi_ledger() if l["hook"] == "done_gate"]

    def test_owner_claim_is_ledgered_and_reaches_the_next_turn(self):
        out = self.run_ext([self.end("Done."), self.START], has_ui=True)
        line = self.gate_lines()[-1]
        self.assertEqual((line["event"], line["kind"], line["decision"]), ("Stop", "done-gate", "warn"))
        self.assertTrue(out["results"][1]["message"]["content"].startswith("DONE-GATE: "), out["results"][1])
        self.assertTrue(any(m.startswith("DONE-GATE: ") for _, m in out["notes"]), out["notes"])

    def test_owner_without_claim_is_silent(self):
        out = self.run_ext([self.end("Which option do you prefer?"), self.START])
        self.assertEqual(self.gate_lines(), [])
        self.assertIsNone(out["results"][1])

    def test_writer_block_rule_is_recorded_unenforced(self):
        config = json.loads((TOOLS_ROOT / "config" / "done-gate.json").read_text(encoding="utf-8"))
        config["rules"]["DONE-02"]["mode"] = "BLOCK"
        (self.tmp / "done-gate.json").write_text(json.dumps(config), encoding="utf-8")
        self.run_ext([self.end("Done.")], child=True, role="generic-mechanic")
        line = self.gate_lines()[-1]
        self.assertEqual((line["event"], line["agent_type"], line["kind"], line["decision"]),
                         ("SubagentStop", "generic-mechanic", "done-unproven", "unenforced"))

    def test_non_writer_subagent_is_not_checked(self):
        self.run_ext([self.end("Done.")], child=True, role="generic-challenger")
        self.assertEqual(self.gate_lines(), [])


class BashPostToolUse(PiExtensionFixture):
    """Gap (d): PostToolUse Bash runs guard_gates.py, which records the outcome."""

    def test_bash_result_is_ledgered(self):
        self.run_ext([self.result("bash", command="git push origin main")])
        self.assertEqual(self.pi_ledger()[-1]["kind"], "gate-push-outcome")

    def test_plain_bash_result_writes_nothing(self):
        # negative control
        self.run_ext([self.result("bash", command="ls -la")])
        self.assertEqual(self.pi_ledger(), [])

    def test_tool_output_filter_is_in_the_matrix_and_record_only(self):
        # T11 (WU12): same matcher as Claude Code; pi's tool_result payload
        # carries no tool_response here, so nothing is replaced or saved.
        out = self.run_ext([self.result("bash", command="seq 1 100000")])
        self.assertIn({"matcher": "Bash", "script": "tool_output_filter.py"}, out["matrix"]["PostToolUse"])
        self.assertEqual(out["results"], [None])
        self.assertFalse((self.hooks_dir / "pi-ephemeral" / "outputs").exists())

    def test_edit_result_still_logs_touched_paths(self):
        self.run_ext([self.result("edit", path=str(self.repo / "app" / "Foo.kt"))])
        lines = (self.hooks_dir / "pi-ephemeral" / "touched.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["path"], "app/Foo.kt")


class VisibleWarnOnPi(PiExtensionFixture):
    """T2 (WU5): a hook's additionalContext is read, never treated as a
    decision, and handed to the model through the one channel the extension
    already uses: the before_agent_start message (next turn). Whether a real
    pi feeds that message to the model is not proven here [Unverified]."""

    START = {"event": "before_agent_start", "payload": {"prompt": "next", "systemPrompt": "no marker"}}

    def test_owner_push_warn_reaches_the_next_turn(self):
        out = self.run_ext([self.call("bash", command="git push origin main"), self.START, self.START])
        self.assertIsNone(out["results"][0], "a warn never blocks the call")
        message = out["results"][1]["message"]
        self.assertEqual(message["customType"], "metodo-warn")
        self.assertTrue(message["content"].startswith("METODO-WARN gate-push: "), message)
        self.assertIsNone(out["results"][2], "a warn is delivered once")
        line = self.pi_ledger()[-1]
        self.assertEqual((line["kind"], line["decision"], line["mode"]), ("gate-push", "warn", "warn"))

    def test_subagent_budget_warn_is_queued_without_blocking(self):
        out = self.run_ext([self.call("read", path="a")] * 3 + [self.START], child=True, role="generic-proposer")
        self.assertEqual(out["results"][:3], [None] * 3)
        self.assertIn("METODO-WARN budget-warn: 3 of 3", out["results"][3]["message"]["content"])

    def test_owner_sees_the_warn_in_the_ui(self):
        out = self.run_ext([self.call("bash", command="git push origin main")], has_ui=True)
        self.assertEqual(out["notes"][0][0], "warning")
        self.assertIn("METODO-WARN gate-push", out["notes"][0][1])

    def test_at_most_three_distinct_warns_per_turn(self):
        pushes = [self.call("bash", command=f"git push origin main && echo {i}") for i in range(2)]
        prs = [self.call("bash", command=c) for c in ("gh pr create --fill", "gh pr merge 1", "git tag v1", "git merge main")]
        out = self.run_ext(pushes + prs + [self.START])
        lines = out["results"][-1]["message"]["content"].splitlines()
        self.assertLessEqual(len(lines), 3)
        self.assertEqual(len(lines), len(set(lines)))
        self.assertTrue(all(l.startswith("METODO-WARN ") for l in lines), lines)

    def test_block_mode_ask_still_holds_without_ui(self):
        # negative control: block mode unchanged, nothing queued
        self.set_config(enabled=True, mode="block")
        out = self.run_ext([self.call("bash", command="git push origin main"), self.START])
        self.assertTrue(out["results"][0]["block"])
        self.assertIsNone(out["results"][1])


class ParityWithClaudeCode(PiExtensionFixture):
    """The pi dispatch table is the Claude Code one: same scripts, same
    matchers, read from hooks.settings.json so the two cannot drift."""

    def test_matrix_matches_hooks_settings(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
        expected = {}
        for event in ("PreToolUse", "PostToolUse", "Stop", "SubagentStop"):
            expected[event] = [{"matcher": entry["matcher"],
                                "script": re.search(r'"\$H/(\w+\.py)"\s*$', entry["hooks"][0]["command"]).group(1)}
                               for entry in settings[event]]
        self.assertEqual(self.run_ext([])["matrix"], expected)

    def test_subagent_edit_of_a_build_file_is_still_denied(self):
        out = self.run_ext([self.call("edit", path=str(self.repo / "app" / "build.gradle"))], child=True)
        self.assertTrue(out["results"][0]["block"])

    def test_subagent_read_of_a_build_file_is_allowed_like_claude_code(self):
        # guard_paths runs on Edit|Write|MultiEdit only, so a read is not a write
        out = self.run_ext([self.call("read", path=str(self.repo / "app" / "build.gradle"))], child=True)
        self.assertEqual(out["results"], [None])

    def test_force_push_is_denied_for_the_owner(self):
        self.set_config(enabled=False)
        out = self.run_ext([self.call("bash", command="git push --force origin feat")])
        self.assertTrue(out["results"][0]["block"])


class MainSessionGuardOnPi(PiExtensionFixture):
    """T7 (S2): the same two hooks on pi. A main-session source edit with the
    writer delegated queues one delegate-writer warn; output_write through a
    direct MCP tool name records its author."""

    START = {"event": "before_agent_start", "payload": {"prompt": "next", "systemPrompt": "no marker"}}

    def _delegated_log(self):
        from tests.test_main_session_guard import DELEGATED, _line
        self.routing_log.parent.mkdir(parents=True, exist_ok=True)
        self.routing_log.write_text(_line(**DELEGATED) + "\n", encoding="utf-8")

    def test_owner_edit_with_writer_delegated_warns_on_the_next_turn(self):
        self._delegated_log()
        edit = self.call("edit", path=str(self.repo / "app" / "Foo.kt"))
        out = self.run_ext([edit, self.START, edit, self.START])
        self.assertIsNone(out["results"][0], "a warn never blocks the call")
        self.assertTrue(out["results"][1]["message"]["content"].startswith("METODO-WARN delegate-writer: "))
        self.assertIsNone(out["results"][3], "once per session per routing decision")
        kinds = [l["kind"] for l in self.pi_ledger()]
        self.assertEqual(kinds.count("main-edit-delegated-role"), 1)

    def test_subagent_edit_with_writer_delegated_is_silent(self):
        self._delegated_log()
        out = self.run_ext([self.call("edit", path=str(self.repo / "app" / "Foo.kt")), self.START],
                           child=True, role="generic-proposer")
        self.assertEqual(out["results"], [None, None])

    def test_output_write_records_the_author(self):
        from tests.test_hooks import FINDINGS
        args = {"round_dir": str(self.tmp / "round"), "role": "challenger", "document": FINDINGS}
        self.run_ext([self.result("mcp__metodo__output_write", **args)])
        self.run_ext([self.result("mcp__metodo__output_write", **args)], child=True, role="generic-challenger")
        authors = [l["reason"].split()[0] for l in self.pi_ledger() if l["kind"] == "output-authored"]
        self.assertEqual(authors, ["author=main", "author=generic-challenger"])


if __name__ == "__main__":
    unittest.main()
