"""hooks/agy/bridge.py: agy's hook stdin becomes the Claude Code stdin the
kit's hook scripts already parse, and their stdout comes back as agy's
decision. Measured on agy 1.4.7 (odd/tasks/agy-adapter.md L3): an empty
stdout is neutral, `{}` denies, a nonzero exit fails the tool and `allow`
would skip agy's own permissions, so the bridge prints a deny, a force_ask,
a Stop `continue`, a SessionStart message or nothing, and always exits 0.

Three layers, all through the bridge's stdin and stdout:
- StubTree: a copy of bridge.py beside recorder stubs named after every
  script in hooks.settings.json. It pins which script runs on which agy tool
  (the row behind each parity entry) and how each stdout shape is translated.
- BridgeFixture: the real bridge over this tree's real scripts on a scratch
  repo (guards, the launch gate, the done gate, the status line).
- Parity: bridge.ROWS and bridge.EXEMPT against hooks.settings.json."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOKS = TOOLS_ROOT / "hooks"
BRIDGE = HOOKS / "agy" / "bridge.py"
SETTINGS = HOOKS / "hooks.settings.json"
DONE_GATE_CONFIG = TOOLS_ROOT / "config" / "done-gate.json"
sys.path.insert(0, str(HOOKS / "agy"))

import bridge  # noqa: E402

GATES_MATCHER = "Bash|mcp__metodo__receipt_start|mcp__metodo__receipt_finalize|mcp__metodo__receipt_acknowledge"
# Not in hooks.settings.json: it travels in each schema-bearing role's frontmatter on Claude Code.
FRONTMATTER_SCRIPT = "validate_subagent_output.py"

BRIEF = """ROLE: generic-proposer
OBJECTIVE: app/Foo.kt exposes a bar() function covered by FooTest.
SPECS: none
ACCEPTANCE: ./gradlew :app:test --tests FooTest
INPUTS:
  - app/Foo.kt
SCOPE: app/**
ALREADY READ: none
CONSTRAINTS: never touch app/build.gradle
OUTPUT: proposer-output; JSON only
STOP: acceptance passes, a budget deny, or a blocking unknown
BUDGET: max_context_tokens=60000; max_tool_calls=40
EVIDENCE: cite the statement at file:line@sha; tag every claim
"""

STUB_COMMON = '''import os
from pathlib import Path


def hooks_dir():
    return Path(os.environ["METODO_HOOKS_DIR"])
'''

# A recorder: logs the stdin it got and prints what STUB_OUT holds under its file name.
STUB_SCRIPT = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

name = Path(__file__).name
payload = json.loads(sys.stdin.read() or "{}")
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"script": name, "payload": payload}) + "\\n")
out = json.loads(os.environ.get("STUB_OUT") or "{}").get(name)
if out is not None:
    sys.stdout.write(out)
'''


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def settings_entries() -> list[tuple[str, str, str]]:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    return [(event, entry.get("matcher", ""), bridge.script_of(hook["command"]))
            for event, entries in settings.items() for entry in entries for hook in entry["hooks"]]


def pretool(decision: str, reason: str = "r") -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                              "permissionDecisionReason": reason}})


def warn(text: str = "METODO-WARN kind: fix", event: str = "PreToolUse") -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


class AgyInputs(unittest.TestCase):
    """The agy side of a test: transcripts and the stdin agy 1.4.7 sends (L3)."""

    def make_tmp(self, prefix: str) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.transcripts = self.tmp / "brain"
        self.hooks_dir = self.tmp / "hooks-out"

    def transcript(self, conversation: str, first_step: dict, reply: str | None = None) -> str:
        path = self.transcripts / conversation / "transcript_full.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [first_step] + ([{"type": "PLANNER_RESPONSE", "content": reply}] if reply is not None else [])
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return str(path)

    def owner_transcript(self, conversation="owner-1", reply: str | None = None) -> str:
        return self.transcript(conversation, {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                                              "content": "<USER_REQUEST>do it</USER_REQUEST>"}, reply)

    def subagent_transcript(self, conversation="child-1", parent="owner-1", prompt="Propose the change",
                            reply: str | None = None) -> str:
        content = ("The following is a <SYSTEM_MESSAGE> not actually sent by the user.\n\n<SYSTEM_MESSAGE>\n"
                   f"[Message] timestamp=2026-10-26T16:34:16Z sender={parent} priority=MESSAGE_PRIORITY_HIGH "
                   f"content={prompt}\n</SYSTEM_MESSAGE>")
        return self.transcript(conversation, {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE",
                                              "content": content}, reply)

    def run_bridge(self, event: str, payload: dict, raw: str | None = None, **env_extra) -> str:
        raise NotImplementedError

    def tool(self, event: str, name: str, args: dict, conversation="owner-1", transcript: str | None = None, **env) -> str:
        return self.run_bridge(event, {
            "conversationId": conversation, "transcriptPath": transcript or self.owner_transcript(conversation),
            "stepIdx": 3, "toolCall": {"name": name, "args": args}}, **env)

    def stop(self, conversation: str, transcript: str, execution_num=0, **env) -> str:
        return self.run_bridge("Stop", {"conversationId": conversation, "transcriptPath": transcript,
                                        "executionNum": execution_num, "terminationReason": "DONE", "fullyIdle": True,
                                        "error": ""}, **env)

    def verdict(self, stdout: str) -> dict:
        self.assertNotEqual(stdout, "", "the bridge stayed neutral")
        return json.loads(stdout)

    def assert_agy_safe(self, event: str, stdout: str) -> None:
        """Never `allow`, never `{}` (which denies), never a decision outside the bridge's own set."""
        if stdout == "":
            return
        out = json.loads(stdout)
        self.assertIsInstance(out, dict)
        self.assertTrue(out, "an empty object denies on agy")
        allowed = {"PreToolUse": ("deny", "force_ask"), "Stop": ("continue",)}.get(event)
        if allowed:
            self.assertIn(out.get("decision"), allowed)
        else:
            self.assertEqual(event, "SessionStart", "only SessionStart prints without a decision")
            self.assertEqual(list(out), ["injectSteps"])


class StubTree(AgyInputs):
    """bridge.py copied beside recorder stubs: what runs, with which stdin, and what each stdout becomes."""

    def setUp(self):
        self.make_tmp("agy-stub-")
        hooks = self.tmp / "tools" / "hooks"
        (hooks / "agy").mkdir(parents=True)
        self.bridge = hooks / "agy" / "bridge.py"
        shutil.copy(BRIDGE, self.bridge)
        shutil.copy(SETTINGS, hooks / "hooks.settings.json")
        (hooks / "_common.py").write_text(STUB_COMMON, encoding="utf-8")
        for script in sorted({script for _, _, script in settings_entries()} | {FRONTMATTER_SCRIPT}):
            (hooks / script).write_text(STUB_SCRIPT, encoding="utf-8")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.log = self.tmp / "stub.jsonl"

    def run_bridge(self, event: str, payload: dict, raw: str | None = None, out: dict | None = None, **env_extra) -> str:
        body = dict({"workspacePaths": [str(self.repo)], "modelName": "auto"}, **payload)
        env = dict(os.environ, METODO_TOOLS=str(self.tmp / "tools"), METODO_REPO=str(self.repo),
                   METODO_HOOKS_DIR=str(self.hooks_dir), STUB_LOG=str(self.log), STUB_OUT=json.dumps(out or {}))
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.update(env_extra)
        proc = subprocess.run(["python3", str(self.bridge), event], input=raw if raw is not None else json.dumps(body),
                              capture_output=True, text=True, env=env, cwd=str(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_agy_safe(event, proc.stdout)
        return proc.stdout

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def scripts_run(self) -> list[str]:
        return [call["script"] for call in self.calls()]

    def clear(self) -> None:
        self.log.unlink(missing_ok=True)


class RoutingTests(StubTree):
    """The row behind each parity entry: this agy call runs these scripts, as this Claude tool."""

    ROUTES = (
        ("PreToolUse", "run_command", {"CommandLine": "git status"}, "Bash", {"command": "git status"},
         ["guard_gates.py", "budget.py"]),
        ("PreToolUse", "write_file", {"Path": "/r/a.kt", "Content": "x", "Overwrite": True}, "Write",
         {"file_path": "/r/a.kt", "content": "x"}, ["guard_paths.py", "budget.py"]),
        ("PreToolUse", "edit_file", {"Path": "/r/a.kt", "Target": "a", "Replacement": "b"}, "Edit",
         {"file_path": "/r/a.kt", "old_string": "a", "new_string": "b"}, ["guard_paths.py", "budget.py"]),
        ("PreToolUse", "read_file", {"Path": "/r/a.kt"}, "Read", {"file_path": "/r/a.kt"}, ["budget.py"]),
        ("PreToolUse", "view_file", {"Path": "/r/a.kt"}, "Read", {"file_path": "/r/a.kt"}, ["budget.py"]),
        ("PreToolUse", "invoke_subagent", {"TypeName": "generic-judge", "Prompt": "judge it", "Role": "the judge"}, "Task",
         {"subagent_type": "generic-judge", "prompt": "judge it"}, ["guard_spawn.py", "budget.py"]),
        ("PreToolUse", "call_mcp_tool", {"ServerName": "metodo_metodo", "ToolName": "receipt_finalize", "Arguments": {"sha": "abc"}},
         "mcp__metodo__receipt_finalize", {"sha": "abc"}, ["guard_gates.py", "budget.py"]),
        ("PreToolUse", "call_mcp_tool", {"ServerName": "metodo", "ToolName": "receipt_start", "Arguments": {}},
         "mcp__metodo__receipt_start", {}, ["guard_gates.py", "budget.py"]),
        ("PreToolUse", "call_mcp_tool", {"ServerName": "stitch", "ToolName": "list", "Arguments": {}},
         "mcp__stitch__list", {}, ["budget.py"]),
        ("PreToolUse", "multi_replace_file_content", {"Path": "/r/settings.gradle"}, "Edit",
         {"file_path": "/r/settings.gradle"}, ["guard_paths.py", "budget.py"]),
        ("PreToolUse", "list_dir", {"Path": "/r"}, "list_dir", {"Path": "/r"}, ["budget.py"]),
        ("PreToolUse", "send_message", {"Recipient": "c2", "Message": "hi"}, "send_message", {"Message": "hi"}, ["budget.py"]),
        ("PostToolUse", "run_command", {"CommandLine": "git status"}, "Bash", {"command": "git status"}, ["guard_gates.py"]),
        ("PostToolUse", "write_file", {"Path": "/r/a.kt", "Content": "x"}, "Write", {"file_path": "/r/a.kt"},
         ["touched_paths.py", "output_author.py"]),
        ("PostToolUse", "edit_file", {"Path": "/r/a.kt", "Target": "a", "Replacement": "b"}, "Edit", {"file_path": "/r/a.kt"},
         ["touched_paths.py", "output_author.py"]),
        ("PostToolUse", "call_mcp_tool", {"ServerName": "metodo_metodo", "ToolName": "output_write",
                                          "Arguments": {"round_dir": "out/r1", "role": "generic-judge"}},
         "mcp__metodo__output_write", {"round_dir": "out/r1", "role": "generic-judge"}, ["output_author.py"]),
        ("PostToolUse", "invoke_subagent", {"TypeName": "generic-judge", "Prompt": "p"}, "Task", {}, []),
    )

    def test_each_agy_tool_runs_its_scripts_under_the_claude_name_and_input(self):
        for event, name, args, claude_name, expected_input, scripts in self.ROUTES:
            with self.subTest(event=event, tool=name, server=args.get("ServerName")):
                self.clear()
                self.assertEqual(self.tool(event, name, args), "")
                self.assertEqual(self.scripts_run(), scripts)
                for call in self.calls():
                    payload = call["payload"]
                    self.assertEqual((payload["hook_event_name"], payload["tool_name"]), (event, claude_name))
                    for key, value in expected_input.items():
                        self.assertEqual(payload["tool_input"][key], value)
                    self.assertEqual((payload["session_id"], payload["cwd"]), ("owner-1", str(self.repo)))
                    self.assertEqual((payload["agent_type"], payload["agent_id"]), ("", ""))

    def test_routes_cover_every_pre_and_post_tool_row(self):
        seen = set()
        for event, _, _, claude_name, _, scripts in self.ROUTES:
            seen |= {(event, script) for script in scripts}
        rows = {(event, script) for event, _, script in bridge.ROWS if event.endswith("ToolUse")}
        self.assertEqual(seen, rows)

    def test_an_exempt_script_never_runs(self):
        self.tool("PostToolUse", "run_command", {"CommandLine": "./gradlew test"})
        self.assertNotIn("tool_output_filter.py", self.scripts_run())
        self.assertIn(("PostToolUse", "Bash", "tool_output_filter.py"), bridge.EXEMPT)

    def test_a_mcp_call_passes_its_arguments_as_the_tool_input(self):
        self.tool("PostToolUse", "call_mcp_tool", {"ServerName": "metodo_metodo", "ToolName": "output_write",
                                                   "Arguments": {"round_dir": "out/r1"}})
        self.assertEqual(self.calls()[0]["payload"]["tool_input"], {"round_dir": "out/r1"})

    def test_role_is_never_the_launched_role_nor_the_prompt(self):
        self.tool("PreToolUse", "invoke_subagent", {"TypeName": "generic-judge", "Prompt": "judge it", "Role": "generic-proposer"})
        launch = self.calls()[0]["payload"]["tool_input"]
        self.assertEqual((launch["subagent_type"], launch["prompt"], launch["Role"]), ("generic-judge", "judge it", "generic-proposer"))
        self.clear()
        self.tool("PreToolUse", "invoke_subagent", {"Prompt": "judge it", "Role": "generic-proposer"})
        launch = self.calls()[0]["payload"]["tool_input"]
        self.assertEqual((launch["subagent_type"], launch["prompt"]), ("", "judge it"))

    def test_a_subagent_call_carries_its_role_and_conversation(self):
        self.tool("PreToolUse", "invoke_subagent", {"TypeName": "generic-proposer", "Prompt": "Propose the change", "Role": "r"})
        self.clear()
        self.tool("PreToolUse", "run_command", {"CommandLine": "ls"}, conversation="child-1",
                  transcript=self.subagent_transcript(prompt="Propose the change"))
        for call in self.calls():
            self.assertEqual((call["payload"]["agent_type"], call["payload"]["agent_id"], call["payload"]["session_id"]),
                             ("generic-proposer", "child-1", "child-1"))

    def test_session_start_runs_the_status_script_as_startup(self):
        self.run_bridge("SessionStart", {"conversationId": "owner-1", "lastUserInput": "hello"})
        (call,) = self.calls()
        self.assertEqual(call["script"], "session_start_status.py")
        self.assertEqual((call["payload"]["hook_event_name"], call["payload"]["source"]), ("SessionStart", "startup"))

    def test_owner_stop_runs_the_stop_row(self):
        self.stop("owner-1", self.owner_transcript(reply="Done."))
        (call,) = self.calls()
        payload = call["payload"]
        self.assertEqual(call["script"], "done_gate.py")
        self.assertEqual((payload["hook_event_name"], payload["last_assistant_message"], payload["agent_type"]), ("Stop", "Done.", ""))
        self.assertEqual((payload["stop_hook_active"], payload["runtime_can_block"]), (False, True))

    def test_subagent_stop_runs_the_subagent_stop_row_and_the_output_check(self):
        self.tool("PreToolUse", "invoke_subagent", {"TypeName": "generic-proposer", "Prompt": "Propose the change", "Role": "r"})
        self.clear()
        self.stop("child-1", self.subagent_transcript(prompt="Propose the change", reply='{"summary": "done"}'), execution_num=1)
        self.assertEqual(self.scripts_run(), [FRONTMATTER_SCRIPT, "done_gate.py"])
        for call in self.calls():
            payload = call["payload"]
            self.assertEqual((payload["hook_event_name"], payload["agent_type"], payload["agent_id"]),
                             ("SubagentStop", "generic-proposer", "child-1"))
            self.assertEqual((payload["stop_hook_active"], payload["runtime_can_block"]), (True, True))
            self.assertEqual(payload["last_assistant_message"], '{"summary": "done"}')

    def test_a_stop_without_a_reply_runs_nothing(self):
        self.assertEqual(self.stop("owner-1", self.owner_transcript()), "")
        self.assertEqual(self.calls(), [])


class DecisionTests(StubTree):
    """A script's stdout (deny, ask, warn context, nothing, noise) as agy's stdout."""

    def write(self, out: dict, **kw) -> str:
        return self.tool("PreToolUse", "write_file", {"Path": "/r/a.kt", "Content": "x"}, out=out, **kw)

    def child(self) -> dict:
        return {"conversation": "child-9", "transcript": self.subagent_transcript("child-9", prompt="unrecorded")}

    def test_a_deny_is_a_deny_with_its_reason(self):
        out = self.verdict(self.write({"guard_paths.py": pretool("deny", "not this file")}))
        self.assertEqual(out, {"decision": "deny", "reason": "not this file"})
        self.assertEqual(self.scripts_run(), ["guard_paths.py"])  # a deny ends the call: no later script runs

    def test_a_deny_from_the_last_script_is_a_deny(self):
        out = self.verdict(self.write({"budget.py": pretool("deny", "budget exhausted")}))
        self.assertEqual(out, {"decision": "deny", "reason": "budget exhausted"})

    def test_nothing_is_nothing(self):
        self.assertEqual(self.write({}), "")
        self.assertEqual(self.scripts_run(), ["guard_paths.py", "budget.py"])

    def test_a_warn_context_is_neutral_and_never_an_allow(self):
        # no decision-free PreToolUse channel is measured on agy (L3: `{}` denies): the warn stays in the ledger
        self.assertEqual(self.write({"guard_paths.py": warn("METODO-WARN scope-outside: stay in scope")}), "")
        self.assertEqual(self.scripts_run(), ["guard_paths.py", "budget.py"])

    def test_a_warn_does_not_hide_a_later_deny(self):
        out = self.verdict(self.write({"guard_paths.py": warn(), "budget.py": pretool("deny", "budget exhausted")}))
        self.assertEqual(out["decision"], "deny")

    def test_a_warn_line_and_a_deny_line_from_one_script_is_a_deny(self):
        for stdout in (warn() + "\n" + pretool("deny", "both"), pretool("deny", "both") + "\n" + warn(),
                       "noise before\n" + pretool("deny", "both") + "\n"):
            with self.subTest(stdout=stdout[:20]):
                self.clear()
                self.assertEqual(self.verdict(self.write({"guard_paths.py": stdout})), {"decision": "deny", "reason": "both"})

    def test_an_allow_is_never_passed_on(self):
        self.assertEqual(self.write({"guard_paths.py": pretool("allow"), "budget.py": pretool("allow")}), "")

    def test_noise_and_empty_objects_are_neutral(self):
        for stdout in ("not json", "{}", "[]", "null", '"deny"', json.dumps({"hookSpecificOutput": "deny"}),
                       json.dumps({"hookSpecificOutput": {"permissionDecision": "later"}})):
            with self.subTest(stdout=stdout):
                self.assertEqual(self.write({"guard_paths.py": stdout}), "")

    def test_an_owner_gate_forces_the_owner_prompt(self):
        out = self.verdict(self.write({"guard_paths.py": pretool("ask", "owner gate")}))
        self.assertEqual(out, {"decision": "force_ask", "reason": "owner gate"})

    def test_an_owner_gate_does_not_hide_a_later_deny(self):
        out = self.verdict(self.write({"guard_paths.py": pretool("ask", "owner gate"), "budget.py": pretool("deny", "no")}))
        self.assertEqual(out, {"decision": "deny", "reason": "no"})

    def test_an_owner_gate_inside_a_subagent_is_a_deny(self):
        out = self.verdict(self.write({"guard_paths.py": pretool("ask", "owner gate")}, **self.child()))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("owner gate", out["reason"])
        self.assertIn("report it in your output", out["reason"])

    def test_post_tool_use_never_prints(self):
        loud = {script: pretool("deny") for script in ("guard_gates.py", "touched_paths.py", "output_author.py")}
        loud["touched_paths.py"] = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {"stdout": "x"}}})
        self.assertEqual(self.tool("PostToolUse", "write_file", {"Path": "/r/a.kt", "Content": "x"}, out=loud), "")
        self.assertEqual(self.tool("PostToolUse", "run_command", {"CommandLine": "ls"}, out=loud), "")
        self.assertEqual(self.scripts_run(), ["touched_paths.py", "output_author.py", "guard_gates.py"])

    def test_a_launch_is_recorded_unless_it_was_denied(self):
        launch = {"TypeName": "generic-proposer", "Prompt": "Propose the change", "Role": "r"}

        def role_seen_by_the_child(conversation: str) -> str:
            self.clear()
            self.tool("PreToolUse", "read_file", {"Path": "/r/a.kt"}, conversation=conversation,
                      transcript=self.subagent_transcript(conversation, prompt="Propose the change"))
            return self.calls()[0]["payload"]["agent_type"]

        self.tool("PreToolUse", "invoke_subagent", launch, out={"guard_spawn.py": pretool("deny", "no goal")})
        self.assertEqual(role_seen_by_the_child("child-a"), "agy-subagent")
        self.tool("PreToolUse", "invoke_subagent", launch, out={"guard_spawn.py": warn("METODO-WARN spawn-no-goal: write the brief")})
        self.assertEqual(role_seen_by_the_child("child-b"), "generic-proposer")

    def test_a_stop_block_sends_the_agent_back(self):
        transcript = self.owner_transcript(reply="Done.")
        out = self.verdict(self.stop("owner-1", transcript, out={"done_gate.py": json.dumps({"decision": "block", "reason": "DONE-GATE: BLOCK 1"})}))
        self.assertEqual(out, {"decision": "continue", "reason": "DONE-GATE: BLOCK 1"})

    def test_a_stop_message_and_anything_else_is_neutral(self):
        transcript = self.owner_transcript(reply="Done.")
        for stdout in (json.dumps({"systemMessage": "DONE-GATE: BLOCK 0 · FLAG 1"}), json.dumps({"decision": "approve"}), "{}", "not json", ""):
            with self.subTest(stdout=stdout):
                self.assertEqual(self.stop("owner-1", transcript, out={"done_gate.py": stdout}), "")

    def test_a_subagent_stop_joins_both_blocks(self):
        transcript = self.subagent_transcript("child-9", prompt="unrecorded", reply="not json")
        out = self.verdict(self.stop("child-9", transcript, out={
            FRONTMATTER_SCRIPT: json.dumps({"decision": "block", "reason": "must be JSON"}),
            "done_gate.py": json.dumps({"decision": "block", "reason": "DONE-GATE: BLOCK 1"})}))
        self.assertEqual(out["decision"], "continue")
        self.assertEqual(out["reason"].splitlines(), ["must be JSON", "DONE-GATE: BLOCK 1"])

    def test_session_status_becomes_a_system_message(self):
        start = {"conversationId": "owner-1", "lastUserInput": "hello"}
        plain = self.run_bridge("SessionStart", start, out={"session_start_status.py": "[metodo] RDD warn mode\nsecond line\n"})
        self.assertEqual(self.verdict(plain), {"injectSteps": [{"systemMessage": {"systemMessage": "[metodo] RDD warn mode\nsecond line"}}]})
        wrapped = self.run_bridge("SessionStart", start, out={
            "session_start_status.py": warn("[metodo] RDD warn mode\n[metodo] goal: ship it", event="SessionStart")})
        self.assertEqual(self.verdict(wrapped), {"injectSteps": [{"systemMessage": {"systemMessage": "[metodo] RDD warn mode\n[metodo] goal: ship it"}}]})
        self.assertEqual(self.run_bridge("SessionStart", start, out={"session_start_status.py": "  \n"}), "")

    def test_a_subagent_session_start_is_silent_and_runs_nothing(self):
        self.assertEqual(self.run_bridge("SessionStart", {"conversationId": "child-1", "lastUserInput": ""},
                                         out={"session_start_status.py": "[metodo] RDD warn mode"}), "")
        self.assertEqual(self.calls(), [])

    def test_broken_input_fails_open(self):
        for raw in ("", "not json", "[]"):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_bridge("PreToolUse", {}, raw=raw), "")

    def test_an_event_the_kit_has_no_row_for_prints_nothing(self):
        for event in ("PreInvocation", "PostInvocation", ""):
            with self.subTest(event=event):
                self.assertEqual(self.run_bridge(event, {"conversationId": "owner-1"}), "")
        self.assertEqual(self.calls(), [])


class ParityTests(unittest.TestCase):
    """S4, S9: every entry of hooks.settings.json has a bridge row or a stated exemption, in bridge.ROWS and bridge.EXEMPT."""

    def settings(self) -> dict:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))

    def test_every_settings_entry_has_a_row_or_a_stated_exemption(self):
        self.assertEqual(bridge.parity_gaps(self.settings()), {"missing": [], "stale": [], "both": []})
        self.assertEqual(sorted(set(bridge.ROWS) | set(bridge.EXEMPT)), sorted(set(settings_entries())))

    def test_an_entry_with_neither_a_row_nor_an_exemption_is_a_gap(self):
        settings = self.settings()
        template = settings["hooks"]["PreToolUse"][0]["hooks"][0]
        planted = dict(template, command=template["command"].replace("guard_paths.py", "planted_guard.py"))
        settings["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [planted]})
        settings["hooks"]["SessionEnd"] = [{"matcher": "", "hooks": [dict(planted)]}]
        self.assertEqual(bridge.parity_gaps(settings)["missing"],
                         [("PreToolUse", "Bash", "planted_guard.py"), ("SessionEnd", "", "planted_guard.py")])

    def test_a_changed_matcher_or_a_second_hook_in_an_entry_is_a_gap(self):
        settings = self.settings()
        settings["hooks"]["PreToolUse"][2]["matcher"] = "Task|Agent|Spawn"
        extra = dict(settings["hooks"]["Stop"][0]["hooks"][0])
        extra["command"] = extra["command"].replace("done_gate.py", "second.py")
        settings["hooks"]["Stop"][0]["hooks"].append(extra)
        gaps = bridge.parity_gaps(settings)
        self.assertEqual(gaps["missing"], [("PreToolUse", "Task|Agent|Spawn", "guard_spawn.py"), ("Stop", "", "second.py")])
        self.assertEqual(gaps["stale"], [("PreToolUse", "Task|Agent", "guard_spawn.py")])

    def test_a_row_for_an_entry_the_kit_dropped_is_stale(self):
        settings = self.settings()
        del settings["hooks"]["SubagentStop"]
        self.assertEqual(bridge.parity_gaps(settings)["stale"], [("SubagentStop", "", "done_gate.py")])

    def test_every_row_and_exemption_says_how_or_why(self):
        for table in (bridge.ROWS, bridge.EXEMPT):
            for key, text in table.items():
                with self.subTest(entry=key):
                    self.assertGreaterEqual(len(text.split()), 5)
        for key, reason in bridge.EXEMPT.items():
            with self.subTest(exempt=key):
                self.assertRegex(reason, r"agy 1\.4\.7|agy has no")

    def test_the_launch_gate_and_this_trees_native_entries_have_rows(self):
        for key in (("PreToolUse", "Task|Agent", "guard_spawn.py"), ("PreToolUse", "", "budget.py"),
                    ("PreToolUse", GATES_MATCHER, "guard_gates.py"), ("Stop", "", "done_gate.py"),
                    ("SubagentStop", "", "done_gate.py"), ("PostToolUse", "Edit|Write|MultiEdit", "output_author.py"),
                    ("PostToolUse", "mcp__metodo__output_write", "output_author.py")):
            with self.subTest(entry=key):
                self.assertIn(key, bridge.ROWS)

    def test_the_matrix_is_read_from_hooks_settings(self):
        settings = self.settings()["hooks"]
        matrix = bridge.load_matrix()
        self.assertEqual(sorted(matrix), sorted(settings))
        for event, entries in settings.items():
            expected = [(entry["matcher"], bridge.script_of(hook["command"]), hook["timeout"])
                        for entry in entries for hook in entry["hooks"]]
            self.assertEqual(matrix[event], expected)
            self.assertTrue(all(script for _, script, _ in expected))

    def test_scripts_for_anchors_matchers(self):
        names = lambda event, tool: [script for script, _ in bridge.scripts_for(event, tool)]  # noqa: E731
        self.assertIn("guard_paths.py", names("PreToolUse", "Write"))
        self.assertNotIn("guard_paths.py", names("PreToolUse", "Writer"))
        self.assertEqual(names("PreToolUse", "anything"), ["budget.py"])
        self.assertEqual(names("PreToolUse", "Task"), ["guard_spawn.py", "budget.py"])


class TemplateTests(unittest.TestCase):
    def spec(self) -> dict:
        hooks = json.loads((HOOKS / "agy" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(list(hooks), ["metodo"])
        return hooks["metodo"]

    def handlers(self, event: str, entries: list) -> list:
        if event.endswith("ToolUse"):
            self.assertEqual([entry["matcher"] for entry in entries], ["*"])
            return entries[0]["hooks"]
        return entries

    def test_hooks_template_routes_every_agy_event_through_the_bridge(self):
        spec = self.spec()
        self.assertEqual(sorted(spec), ["PostToolUse", "PreToolUse", "SessionStart", "Stop"])
        for event, entries in spec.items():
            for handler in self.handlers(event, entries):
                with self.subTest(event=event):
                    self.assertEqual(handler["type"], "command")
                    self.assertTrue(handler["command"].startswith(": metodo-hook;"))
                    self.assertTrue(handler["command"].endswith(f'/agy/bridge.py" {event}'))
                    self.assertIn("__TOOLS_DEFAULT__", handler["command"])
                    self.assertIn("__REPO_DEFAULT__", handler["command"])
                    self.assertIn("|| exit 0", handler["command"])

    def test_each_timeout_leaves_room_for_the_scripts_of_its_event(self):
        spec = self.spec()
        for event, entries in spec.items():
            (handler,) = self.handlers(event, entries)
            with self.subTest(event=event):
                # 35 s is the longest timeout the Spanish tree shipped to agy 1.4.7; a longer one is not measured
                self.assertLessEqual(handler["timeout"], 35)
                self.assertEqual(handler["timeout"], bridge.BUDGET_S[event] + 2)
        tools = ("Bash", "Write", "Edit", "Read", "Task", "mcp__metodo__receipt_finalize", "mcp__metodo__output_write", "other")
        for event in ("PreToolUse", "PostToolUse"):
            worst = max(sum(timeout for _, timeout in bridge.scripts_for(event, tool)) for tool in tools)
            self.assertLessEqual(worst, bridge.BUDGET_S[event], event)
        self.assertLessEqual(sum(t for _, t in bridge.scripts_for("SessionStart", "startup")), bridge.BUDGET_S["SessionStart"])
        for kit_event in ("Stop", "SubagentStop"):
            self.assertLessEqual(max(t for _, t in bridge.scripts_for(kit_event, "")), bridge.BUDGET_S["Stop"], kit_event)


class TranscriptTests(unittest.TestCase):
    def test_last_reply_is_read_from_the_transcript(self):
        tmp = Path(tempfile.mkdtemp(prefix="agy-transcript-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "t.jsonl"
        rows = [{"type": "USER_INPUT", "content": "q"},
                {"type": "PLANNER_RESPONSE", "content": "first"},
                {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file"}]},
                {"type": "PLANNER_RESPONSE", "content": "final answer"},
                {"type": "GENERIC", "content": "tool output"}]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        self.assertEqual(bridge.last_reply(str(path)), "final answer")
        self.assertEqual(bridge.last_reply(str(tmp / "missing.jsonl")), "")


class BridgeFixture(AgyInputs):
    """The real bridge over this tree's real hook scripts, on a scratch repo."""

    def setUp(self):
        self.make_tmp("agy-bridge-")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "app").mkdir()
        (self.repo / "app" / "Foo.kt").write_text("class Foo\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.config_path = self.tmp / "project.json"
        self.set_config()

    def set_config(self, enabled=True, mode="warn", hook_modes=None) -> None:
        self.config_path.write_text(json.dumps({
            "shared_build_files": ["settings.gradle", "app/build.gradle"],
            "rdd": {"enabled": enabled, "mode": mode, "hook_modes": hook_modes or {}, "exempt_globs": ["**/*.md"]},
        }), encoding="utf-8")

    def run_bridge(self, event: str, payload: dict, raw: str | None = None, **env_extra) -> str:
        body = dict({"workspacePaths": [str(self.repo)], "modelName": "auto"}, **payload)
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_REPO=str(self.repo), METODO_MEMORY="off",
                   METODO_PROJECT_CONFIG=str(self.config_path), METODO_HOOKS_DIR=str(self.hooks_dir),
                   METODO_RDD_DIR=str(self.tmp / "rdd"), METODO_ROUTING_LOG=str(self.tmp / "runs" / "routing.jsonl"),
                   METODO_RUNS_DIR=str(self.tmp / "runs-dir"))
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.update(env_extra)
        proc = subprocess.run(["python3", str(BRIDGE), event], input=raw if raw is not None else json.dumps(body),
                              capture_output=True, text=True, env=env, cwd=str(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_agy_safe(event, proc.stdout)
        return proc.stdout

    def write(self, rel: str, conversation="owner-1", transcript: str | None = None) -> str:
        return self.tool("PreToolUse", "write_file", {"Path": str(self.repo / rel), "Content": "x\n", "Overwrite": True},
                         conversation=conversation, transcript=transcript)

    def invoke(self, type_name: str, prompt: str, role="r", conversation="owner-1", transcript: str | None = None) -> str:
        return self.tool("PreToolUse", "invoke_subagent", {"TypeName": type_name, "Prompt": prompt, "Role": role},
                         conversation=conversation, transcript=transcript)

    def ledger(self, conversation: str) -> list[dict]:
        path = self.hooks_dir / conversation / "ledger.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def last_line(self, conversation: str) -> dict:
        rows = self.ledger(conversation)
        self.assertTrue(rows, f"no ledger line for {conversation}")
        return rows[-1]


class GuardTests(BridgeFixture):
    def test_owner_normal_write_prints_nothing(self):
        self.assertEqual(self.write("app/Foo.kt"), "")

    def test_owner_build_file_write_forces_the_owner_prompt(self):
        out = self.verdict(self.write("settings.gradle"))
        self.assertEqual(out["decision"], "force_ask")
        self.assertIn("settings.gradle", out["reason"])

    def test_owner_agent_config_write_prints_nothing(self):
        self.assertEqual(self.write(".agents/plugins/metodo/hooks.json"), "")

    def test_known_subagent_is_denied_on_agent_config_and_build_files(self):
        self.assertEqual(self.invoke("generic-proposer", "Propose the change"), "")
        transcript = self.subagent_transcript(prompt="Propose the change")
        for rel in (".agents/plugins/metodo/hooks.json", "app/build.gradle"):
            with self.subTest(path=rel):
                out = self.verdict(self.write(rel, "child-1", transcript))
                self.assertEqual(out["decision"], "deny")
                self.assertIn(rel, out["reason"])
        rows = self.ledger("child-1")
        self.assertTrue(rows)
        self.assertTrue(all((row["agent_id"], row["agent_type"]) == ("child-1", "generic-proposer") for row in rows))

    def test_subagent_with_unknown_role_is_still_a_subagent(self):
        out = self.verdict(self.write("app/build.gradle", "child-2", self.subagent_transcript("child-2", prompt="no pending")))
        self.assertEqual(out["decision"], "deny")
        self.assertEqual(self.last_line("child-2")["agent_type"], "agy-subagent")

    def test_an_unparsed_system_message_from_another_conversation_fails_closed(self):
        transcript = self.transcript("child-3", {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE",
                                                 "content": "[Message] sender=owner-1 priority=HIGH body changed format"})
        out = self.verdict(self.write("app/build.gradle", "child-3", transcript))
        self.assertEqual(out["decision"], "deny")

    def test_a_conversation_id_cannot_escape_the_hooks_dir(self):
        self.write("app/Foo.kt", "../../escape", self.owner_transcript("escape"))
        self.write("settings.gradle", "../../escape", self.owner_transcript("escape"))
        outside = [p for p in self.tmp.rglob("*") if p.is_file() and "escape" in p.name
                   and self.hooks_dir not in p.parents and self.transcripts not in p.parents]
        self.assertEqual(outside, [])
        self.assertFalse((self.tmp.parent / "escape").exists())

    def test_owner_gate_inside_a_subagent_is_a_deny_with_a_report_hint(self):
        self.invoke("generic-proposer", "Propose the change")
        out = self.verdict(self.write("settings.gradle", "child-1", self.subagent_transcript()))
        self.assertEqual(out["decision"], "deny")

    def test_a_force_push_is_denied_through_run_command(self):
        out = self.verdict(self.tool("PreToolUse", "run_command", {"CommandLine": "git push --force origin main"}))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("--force-with-lease", out["reason"])
        self.assertEqual(self.tool("PreToolUse", "run_command", {"CommandLine": "git status"}), "")

    def test_a_subagent_over_its_budget_is_denied_on_any_tool(self):
        agents = self.repo / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "generic-proposer.contract.json").write_text(json.dumps(
            {"agent": "generic-proposer", "may_write": ["app/**"], "max_tool_calls": 2}), encoding="utf-8")
        self.invoke("generic-proposer", "Propose the change")
        transcript = self.subagent_transcript(prompt="Propose the change")
        read = lambda: self.tool("PreToolUse", "read_file", {"Path": str(self.repo / "app/Foo.kt")},  # noqa: E731
                                 conversation="child-1", transcript=transcript)
        self.assertEqual((read(), read()), ("", ""))
        out = self.verdict(read())
        self.assertEqual(out["decision"], "deny")
        self.assertIn("budget exhausted", out["reason"])

    def test_post_tool_use_records_and_prints_nothing(self):
        out = self.tool("PostToolUse", "write_file", {"Path": str(self.repo / "app/Foo.kt"), "Content": "y"})
        self.assertEqual(out, "")
        touched = (self.hooks_dir / "owner-1" / "touched.jsonl").read_text(encoding="utf-8")
        self.assertIn("app/Foo.kt", touched)

    def test_broken_input_fails_open(self):
        for raw in ("", "not json", "[]"):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_bridge("PreToolUse", {}, raw=raw), "")

    def test_a_subagent_cannot_rewrite_its_own_contract(self):
        # the plugin ships each role's contract under .agents/, which is always forbidden to a subagent
        rel = ".agents/plugins/metodo/contracts/generic-proposer.contract.json"
        (self.repo / rel).parent.mkdir(parents=True)
        (self.repo / rel).write_text(json.dumps({"agent": "generic-proposer", "may_write": ["app/**"], "max_tool_calls": 60}),
                                     encoding="utf-8")
        self.assertEqual(self.invoke("generic-proposer", "Propose the change"), "")
        transcript = self.subagent_transcript(prompt="Propose the change")
        path = str(self.repo / rel)
        for name, args in (("write_file", {"Path": path, "Content": "{}\n", "Overwrite": True}),
                           ("edit_file", {"Path": path, "Target": "60", "Replacement": "600000"})):
            with self.subTest(tool=name):
                out = self.verdict(self.tool("PreToolUse", name, args, conversation="child-1", transcript=transcript))
                self.assertEqual(out["decision"], "deny")
                self.assertIn("agent-config", out["reason"])
        self.assertEqual(self.last_line("child-1")["agent_type"], "generic-proposer")

    def test_unknown_event_prints_nothing(self):
        self.assertEqual(self.run_bridge("PreInvocation", {"conversationId": "owner-1"}), "")


class LaunchGateTests(BridgeFixture):
    """S9: agy's invoke_subagent reaches guard_spawn.py as a Task launch."""

    def child_role(self, conversation: str, prompt: str) -> str:
        out = self.verdict(self.write("app/build.gradle", conversation, self.subagent_transcript(conversation, prompt=prompt)))
        self.assertEqual(out["decision"], "deny")
        return self.last_line(conversation)["agent_type"]

    def test_a_launch_with_a_goal_contract_is_silent_and_names_the_child(self):
        self.set_config(mode="block")
        self.assertEqual(self.invoke("generic-proposer", BRIEF), "")
        self.assertEqual(self.ledger("owner-1"), [])
        self.assertEqual(self.child_role("child-1", BRIEF), "generic-proposer")

    def test_a_launch_without_a_goal_is_denied_in_block_mode(self):
        self.set_config(mode="warn", hook_modes={"guard_spawn": "block"})
        out = self.verdict(self.invoke("generic-proposer", "Look around the repo and fix whatever seems wrong."))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("04-templates/brief.md", out["reason"])
        line = self.last_line("owner-1")
        self.assertEqual((line["hook"], line["kind"], line["decision"], line["tool"]), ("guard_spawn", "spawn-no-goal", "deny", "Task"))
        # a denied launch names no child
        self.assertEqual(self.child_role("child-1", "Look around the repo and fix whatever seems wrong."), "agy-subagent")

    def test_a_launch_without_a_goal_in_warn_mode_is_neutral_and_ledgered(self):
        self.assertEqual(self.invoke("generic-proposer", "Look around the repo and fix whatever seems wrong."), "")
        line = self.last_line("owner-1")
        self.assertEqual((line["hook"], line["kind"], line["decision"], line["mode"]), ("guard_spawn", "spawn-no-goal", "warn", "warn"))
        self.assertEqual(self.child_role("child-1", "Look around the repo and fix whatever seems wrong."), "generic-proposer")

    def test_the_gate_judges_typename_never_role(self):
        self.set_config(mode="block")
        out = self.verdict(self.invoke("generic-challenger", BRIEF, role="generic-proposer"))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("the launched role is generic-challenger", out["reason"])
        self.assertEqual(self.last_line("owner-1")["kind"], "spawn-role-mismatch")

    def test_a_kit_role_subagent_launches_nothing_even_with_rdd_off(self):
        self.set_config(enabled=False)
        self.assertEqual(self.invoke("generic-proposer", "Propose the change"), "")
        out = self.verdict(self.invoke("generic-challenger", BRIEF, conversation="child-1",
                                     transcript=self.subagent_transcript(prompt="Propose the change")))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("generic-proposer may not launch generic-challenger", out["reason"])
        line = self.last_line("child-1")
        self.assertEqual((line["kind"], line["agent_type"], line["agent_id"]), ("spawn-not-allowed", "generic-proposer", "child-1"))

    def test_rdd_off_leaves_an_owner_launch_alone(self):
        self.set_config(enabled=False)
        self.assertEqual(self.invoke("generic-proposer", "do the thing"), "")
        self.assertEqual(self.ledger("owner-1"), [])


class StopTests(BridgeFixture):
    """This tree's Stop and SubagentStop rows: the done gate, plus the output check a role's frontmatter carries."""

    def claim(self) -> str:
        (self.repo / "app" / "Foo.kt").write_text("class Foo { val x = 1 }\n", encoding="utf-8")
        return self.owner_transcript(reply="Done, the change is finished.")

    def block_rule(self, rule_id: str) -> None:
        config = json.loads(DONE_GATE_CONFIG.read_text(encoding="utf-8"))
        config["rules"][rule_id]["mode"] = "BLOCK"
        (self.tmp / "done-gate.json").write_text(json.dumps(config), encoding="utf-8")  # beside project.json

    def test_an_unproven_done_under_a_block_rule_sends_the_owner_session_back_once(self):
        self.block_rule("DONE-02")
        transcript = self.claim()
        out = self.verdict(self.stop("owner-1", transcript))
        self.assertEqual(out["decision"], "continue")
        self.assertIn("DONE-GATE: BLOCK 1", out["reason"])
        line = self.last_line("owner-1")
        self.assertEqual((line["hook"], line["kind"], line["decision"], line["event"]), ("done_gate", "done-gate", "block", "Stop"))
        self.assertEqual(self.stop("owner-1", transcript, execution_num=1), "")
        self.assertEqual(self.last_line("owner-1")["kind"], "done-unproven")

    def test_an_unproven_done_under_a_flag_rule_is_neutral_and_ledgered(self):
        self.assertEqual(self.stop("owner-1", self.claim()), "")
        line = self.last_line("owner-1")
        self.assertEqual((line["hook"], line["kind"], line["decision"]), ("done_gate", "done-gate", "warn"))

    def test_a_reply_without_a_done_claim_is_silent(self):
        self.assertEqual(self.stop("owner-1", self.owner_transcript(reply="Which option do you prefer, A or B?")), "")
        self.assertEqual(self.ledger("owner-1"), [])

    def test_a_schema_role_with_an_invalid_final_message_is_sent_back(self):
        self.set_config(mode="warn", hook_modes={"validate_subagent_output": "block"})
        self.invoke("generic-judge", "Judge the round")
        transcript = self.subagent_transcript(prompt="Judge the round", reply="I think it is fine.")
        out = self.verdict(self.stop("child-1", transcript))
        self.assertEqual(out["decision"], "continue")
        self.assertIn("verdict.schema.json", out["reason"])
        line = self.last_line("child-1")
        self.assertEqual((line["hook"], line["kind"], line["event"], line["agent_type"]),
                         ("validate_subagent_output", "output-invalid", "SubagentStop", "generic-judge"))


class SessionStartTests(BridgeFixture):
    def test_the_owner_session_gets_the_status_line_as_a_system_message(self):
        out = self.verdict(self.run_bridge("SessionStart", {"conversationId": "owner-1", "lastUserInput": "hello"}))
        text = out["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("[metodo] RDD warn mode", text)
        self.assertEqual(self.last_line("owner-1")["kind"], "session-start")

    def test_a_subagent_start_is_silent(self):
        self.assertEqual(self.run_bridge("SessionStart", {"conversationId": "child-1", "lastUserInput": ""}), "")
        self.assertEqual(self.ledger("child-1"), [])


if __name__ == "__main__":
    unittest.main()
