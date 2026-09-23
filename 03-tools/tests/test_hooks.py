"""Each hook as a subprocess with synthetic stdin, over a temporary git repo,
a temporary config (METODO_PROJECT_CONFIG), and a temporary ledger
directory (METODO_HOOKS_DIR). The absolute set is tested with RDD off; the
non-absolute set in warn and in block; and the no-op when there is no config."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOKS = TOOLS_ROOT / "hooks"

FINDINGS = {"round": "r", "role": "challenger", "summary": "ok", "findings": [
    {"id": "F-01", "lens": "simplicidad", "claim": "c", "attack": "a", "failure_scenario": "f", "evidence": ["x.kt:1"],
     "verdict": "OK", "epistemic": "Probado", "simpler_alternative": "none"}]}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class HookFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hooks-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "app").mkdir()
        (self.repo / "app" / "build.gradle").write_text("x\n", encoding="utf-8")
        (self.repo / "app" / "Foo.kt").write_text("class Foo\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.tree = _git(self.repo, "rev-parse", "HEAD^{tree}")
        agents = self.repo / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "generic-proposer.contract.json").write_text(json.dumps(
            {"agent": "generic-proposer", "may_write": ["app/**"], "max_tool_calls": 3}), encoding="utf-8")
        (agents / "generic-challenger.contract.json").write_text(json.dumps(
            {"agent": "generic-challenger", "may_write": [], "max_tool_calls": 40}), encoding="utf-8")
        self.hooks_dir = self.tmp / "hooks-out"
        self.rdd_dir = self.tmp / "rdd"
        self.config_path = self.tmp / "project.json"
        self.set_config(enabled=True, mode="warn")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_config(self, enabled=True, mode="warn", hook_modes=None):
        self.config_path.write_text(json.dumps({
            "shared_build_files": ["settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle"],
            "rdd": {"enabled": enabled, "mode": mode, "hook_modes": hook_modes or {}, "exempt_globs": ["**/*.md"]},
        }), encoding="utf-8")

    def run_hook(self, name: str, payload: dict, session="s1", env_extra=None):
        payload = dict({"session_id": session, "cwd": str(self.repo), "hook_event_name": "PreToolUse"}, **payload)
        env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_PROJECT_CONFIG=str(self.config_path),
                   METODO_HOOKS_DIR=str(self.hooks_dir), METODO_RDD_DIR=str(self.rdd_dir), CLAUDE_PROJECT_DIR=str(self.repo))
        env.update(env_extra or {})
        proc = subprocess.run(["python3", str(HOOKS / name)], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        try:
            return (json.loads(proc.stdout) if proc.stdout.strip() else {}), proc
        except json.JSONDecodeError:
            return {}, proc

    def decision(self, out):
        return (out.get("hookSpecificOutput") or {}).get("permissionDecision")

    def ledger(self, session="s1"):
        path = self.hooks_dir / session / "ledger.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def write_receipt(self, verdict="approved", state="finalized", scope_globs=None, tree=None):
        self.rdd_dir.mkdir(exist_ok=True)
        receipt = {"tree_sha": tree or self.tree, "state": state, "verdict": verdict, "round_dir": "~/round", "correction_index": 0,
                   "risk": {"tier": "low", "consent": "n/a"}, "scope_globs": scope_globs or []}
        (self.rdd_dir / f"{tree or self.tree}.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


class GuardPathsTests(HookFixture):
    def _edit(self, path, **extra):
        return {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / path)}, **extra}

    def test_subagent_on_build_file_is_denied_even_with_rdd_off(self):
        self.set_config(enabled=False)
        out, _ = self.run_hook("guard_paths.py", self._edit("app/build.gradle", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(self.decision(out), "deny")
        self.assertEqual(self.ledger()[0]["kind"], "forbidden-path")

    def test_subagent_on_claude_dir_is_denied(self):
        out, _ = self.run_hook("guard_paths.py", self._edit(".claude/agents/x.md", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(self.decision(out), "deny")

    def test_main_session_on_build_file_asks(self):
        out, _ = self.run_hook("guard_paths.py", self._edit("settings.gradle"))
        self.assertEqual(self.decision(out), "ask")

    def test_main_session_normal_edit_is_silent(self):
        # negative control
        out, proc = self.run_hook("guard_paths.py", self._edit("app/Foo.kt"))
        self.assertEqual(out, {})
        self.assertEqual(proc.stdout, "")

    def test_scope_outside_warns_then_denies_in_block(self):
        out, _ = self.run_hook("guard_paths.py", self._edit("domain/Bar.kt", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "scope-outside")
        self.set_config(enabled=True, mode="block")
        out, _ = self.run_hook("guard_paths.py", self._edit("domain/Bar.kt", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(self.decision(out), "deny")
        out, _ = self.run_hook("guard_paths.py", self._edit("app/Foo.kt", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(out, {})

    def test_receipt_scope_extends_allowlist(self):
        self.set_config(enabled=True, mode="block")
        self.write_receipt(state="started", verdict=None, scope_globs=["domain/**"])
        out, _ = self.run_hook("guard_paths.py", self._edit("domain/Bar.kt", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(out, {})

    def test_same_input_same_output(self):
        a, _ = self.run_hook("guard_paths.py", self._edit("app/build.gradle", agent_type="generic-proposer", agent_id="a1"))
        b, _ = self.run_hook("guard_paths.py", self._edit("app/build.gradle", agent_type="generic-proposer", agent_id="a1"))
        self.assertEqual(a, b)


class GuardGatesTests(HookFixture):
    def _bash(self, command, **extra):
        return {"tool_name": "Bash", "tool_input": {"command": command}, **extra}

    def test_force_push_denied_in_any_mode(self):
        self.set_config(enabled=False)
        out, _ = self.run_hook("guard_gates.py", self._bash("git push --force origin feat"))
        self.assertEqual(self.decision(out), "deny")
        out, _ = self.run_hook("guard_gates.py", self._bash("git push -f origin feat"))
        self.assertEqual(self.decision(out), "deny")

    def test_push_text_inside_echo_or_grep_is_not_a_push(self):
        # negative control: real case, the hook denied an echo carrying the command's text inside
        self.set_config(enabled=False)
        for cmd in ("echo '{\"command\":\"git push --force origin x\"}' | python3 hook.py",
                    "grep -n 'git push --force' docs/notes.md",
                    "cat <<'EOF'\ngit push --force origin x\nEOF"):
            out, _ = self.run_hook("guard_gates.py", self._bash(cmd))
            self.assertEqual(out, {}, cmd)

    def test_force_push_in_compound_commands_is_still_denied(self):
        self.set_config(enabled=False)
        for cmd in ("cd /tmp/x && git push --force origin feat", "git -C /tmp/x push -f origin feat", "GIT_SSH=x git push --force"):
            out, _ = self.run_hook("guard_gates.py", self._bash(cmd))
            self.assertEqual(self.decision(out), "deny", cmd)

    def test_force_with_lease_allowed(self):
        # negative control
        self.set_config(enabled=False)
        out, _ = self.run_hook("guard_gates.py", self._bash("git push --force-with-lease origin feat"))
        self.assertEqual(out, {})

    def test_subagent_push_pr_tag_receipt_denied(self):
        for cmd in ("git push origin feat", "gh pr create --fill", "git tag v1", "python3 lib/rdd_receipt.py finalize --tree x"):
            out, _ = self.run_hook("guard_gates.py", self._bash(cmd, agent_type="generic-proposer", agent_id="a1"))
            self.assertEqual(self.decision(out), "deny", cmd)
        out, _ = self.run_hook("guard_gates.py", {"tool_name": "mcp__metodo__receipt_acknowledge", "tool_input": {"tree": "x"},
                                                  "agent_type": "generic-verifier", "agent_id": "a2"})
        self.assertEqual(self.decision(out), "deny")

    def test_main_push_without_receipt_warns_in_warn_and_asks_in_block(self):
        out, _ = self.run_hook("guard_gates.py", self._bash("git push origin main"))
        self.assertEqual(out, {})
        line = self.ledger()[-1]
        self.assertEqual((line["kind"], line["decision"], line["receipt"]), ("gate-push", "warn", "none"))
        self.set_config(enabled=True, mode="block")
        out, _ = self.run_hook("guard_gates.py", self._bash("git push origin main"))
        self.assertEqual(self.decision(out), "ask")

    def test_main_push_with_approved_receipt_is_allowed_and_logged(self):
        self.set_config(enabled=True, mode="block")
        self.write_receipt()
        out, _ = self.run_hook("guard_gates.py", self._bash("git push origin main"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["receipt"], "approved")

    def test_no_verify_is_only_logged(self):
        out, _ = self.run_hook("guard_gates.py", self._bash("git commit --no-verify -m x"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "no-verify")

    def test_rdd_disabled_skips_the_gate(self):
        self.set_config(enabled=False)
        out, _ = self.run_hook("guard_gates.py", self._bash("git push origin main"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger(), [])

    def test_post_tool_use_only_records(self):
        out, _ = self.run_hook("guard_gates.py", dict(self._bash("git push origin main"), hook_event_name="PostToolUse"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "gate-push-outcome")


class BudgetTests(HookFixture):
    def _call(self, n_calls, agent_type="generic-proposer", agent_id="a1"):
        out = None
        for _ in range(n_calls):
            out, _ = self.run_hook("budget.py", {"tool_name": "Read", "tool_input": {}, "agent_type": agent_type, "agent_id": agent_id})
        return out

    def test_main_session_creates_nothing(self):
        out, _ = self.run_hook("budget.py", {"tool_name": "Read", "tool_input": {}})
        self.assertEqual(out, {})
        self.assertFalse(self.hooks_dir.exists())

    def test_denies_past_the_contract_cap(self):
        self.assertEqual(self._call(3), {})
        out = self._call(1)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("truncated:true", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual((self.hooks_dir / "s1" / "budget-generic-proposer-a1.count").read_text().strip(), "4")
        self.assertIn("budget-deny", [l["kind"] for l in self.ledger()])

    def test_unknown_agent_without_contract_is_uncapped(self):
        # negative control
        out = self._call(5, agent_type="emv-redteam", agent_id="z")
        self.assertEqual(out, {})


class ValidateOutputTests(HookFixture):
    def _stop(self, message, agent_type="generic-challenger", **extra):
        return {"hook_event_name": "SubagentStop", "agent_type": agent_type, "agent_id": "a9", "last_assistant_message": message, **extra}

    def test_valid_json_passes(self):
        out, _ = self.run_hook("validate_subagent_output.py", self._stop(json.dumps(FINDINGS)))
        self.assertEqual(out, {})

    def test_fenced_json_passes_and_is_noted(self):
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("Here:\n```json\n" + json.dumps(FINDINGS) + "\n```"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "output-fenced")

    def test_invalid_in_warn_only_logs(self):
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("I attacked the claims and found nothing."))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "output-invalid")

    def test_invalid_in_block_blocks_once_then_lets_through(self):
        self.set_config(enabled=True, mode="block")
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("prose"))
        self.assertEqual(out["decision"], "block")
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("prose"))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["decision"], "invalid-let-through")

    def test_stop_hook_active_and_unknown_agent_are_noops(self):
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("prose", stop_hook_active=True))
        self.assertEqual(out, {})
        out, _ = self.run_hook("validate_subagent_output.py", self._stop("prose", agent_type="emv-redteam"))
        self.assertEqual(out, {})

    def test_truncated_is_noted_not_blocked(self):
        self.set_config(enabled=True, mode="block")
        out, _ = self.run_hook("validate_subagent_output.py", self._stop(json.dumps(dict(FINDINGS, truncated=True, not_covered=["C"]))))
        self.assertEqual(out, {})
        self.assertEqual(self.ledger()[-1]["kind"], "output-truncated")


class SessionStartTouchedReplyTests(HookFixture):
    def test_session_start_prints_status_and_run_meta(self):
        self.write_receipt()
        _, proc = self.run_hook("session_start_status.py", {"hook_event_name": "SessionStart", "source": "startup"})
        lines = proc.stdout.strip().splitlines()
        self.assertLessEqual(len(lines), 10)
        self.assertIn("verdict=approved", proc.stdout)
        self.assertTrue((self.hooks_dir / "s1" / "run-meta.json").exists())

    def test_session_start_silent_when_disabled(self):
        self.set_config(enabled=False)
        _, proc = self.run_hook("session_start_status.py", {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(proc.stdout, "")

    def test_touched_paths_appends(self):
        self.run_hook("touched_paths.py", {"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                           "tool_input": {"file_path": str(self.repo / "app" / "Foo.kt")}, "agent_type": "generic-proposer"})
        lines = (self.hooks_dir / "s1" / "touched.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0]), {"path": "app/Foo.kt", "agent_type": "generic-proposer"})

    def test_reply_lint_never_blocks(self):
        text = ("Vale, entonces te cuento: " + "esto es una frase larga que no dice nada concreto y sigue y sigue " * 12)
        out, _ = self.run_hook("reply_lint.py", {"hook_event_name": "Stop", "last_assistant_message": text})
        self.assertEqual(out, {})

    def test_hooks_are_noops_without_any_config(self):
        missing = self.tmp / "nope.json"
        for name, payload in (("guard_gates.py", {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}),
                              ("session_start_status.py", {"hook_event_name": "SessionStart"}),
                              ("touched_paths.py", {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": "a"}})):
            _, proc = self.run_hook(name, payload, env_extra={"METODO_PROJECT_CONFIG": str(missing)})
            self.assertEqual(proc.stdout, "", name)


class LatencyTests(HookFixture):
    def test_each_hook_under_a_second(self):
        import time
        for name, payload in (("guard_paths.py", {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / "app" / "Foo.kt")}}),
                              ("guard_gates.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                              ("budget.py", {"tool_name": "Read", "tool_input": {}})):
            t0 = time.time()
            self.run_hook(name, payload)
            self.assertLess(time.time() - t0, 1.0, name)
