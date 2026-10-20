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
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.rdd_dir), METODO_MEMORY="off")
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


class BashPostToolUse(PiExtensionFixture):
    """Gap (d): PostToolUse Bash runs guard_gates.py, which records the outcome."""

    def test_bash_result_is_ledgered(self):
        self.run_ext([self.result("bash", command="git push origin main")])
        self.assertEqual(self.pi_ledger()[-1]["kind"], "gate-push-outcome")

    def test_plain_bash_result_writes_nothing(self):
        # negative control
        self.run_ext([self.result("bash", command="ls -la")])
        self.assertEqual(self.pi_ledger(), [])

    def test_edit_result_still_logs_touched_paths(self):
        self.run_ext([self.result("edit", path=str(self.repo / "app" / "Foo.kt"))])
        lines = (self.hooks_dir / "pi-ephemeral" / "touched.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["path"], "app/Foo.kt")


class ParityWithClaudeCode(PiExtensionFixture):
    """The pi dispatch table is the Claude Code one: same scripts, same
    matchers, read from hooks.settings.json so the two cannot drift."""

    def test_matrix_matches_hooks_settings(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
        expected = {}
        for event in ("PreToolUse", "PostToolUse"):
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


if __name__ == "__main__":
    unittest.main()
