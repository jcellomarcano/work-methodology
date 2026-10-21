"""T11 (WU12): hooks/tool_output_filter.py on PostToolUse Bash.

Claude Code documents `updatedToolOutput` on PostToolUse: it "Replaces the
tool's output with the provided value before it is sent to Claude. The value
must match the tool's output shape" (Bash: stdout, stderr, interrupted,
isImage; hooks.md, read 2026-10-18). Over the cap the hook saves the full
output under out/hooks/<session>/outputs/<seq>.txt and replaces stdout with a
deterministic summary: head, tail and every error/failure line, so the line
that mattered is never hidden, plus `METODO-OUTPUT full: <path>`."""
import json
import math
from pathlib import Path

from tests.test_hooks import HOOKS, HookFixture, _git

SETTINGS = HOOKS / "hooks.settings.json"
FULL = "METODO-OUTPUT full: "


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def long_output(lines=5000, errors=None):
    """`lines` plain lines; `errors` maps a 1-based line number to its text."""
    out = [f"ok step {i} compiled module_{i} without trouble" for i in range(1, lines + 1)]
    for number, text in (errors or {}).items():
        out[number - 1] = text
    return "\n".join(out) + "\n"


ERRORS = {
    1000: "Traceback (most recent call last):",
    1800: "AssertionError: expected 3, got 4",
    2600: "FAILED tests/test_x.py::test_y - assert 3 == 4",
    3300: "build step failed with status 2",
    4100: "java.lang.IllegalStateException: boom",
}


class ToolOutputFixture(HookFixture):
    def bash(self, stdout, stderr="", session="s1", tool="Bash", env_extra=None, **response):
        payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {"command": "make test"},
                   "tool_response": dict({"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False},
                                         **response)}
        out, _ = self.run_hook("tool_output_filter.py", payload, session=session, env_extra=env_extra)
        return out

    def summary(self, out):
        specific = out.get("hookSpecificOutput") or {}
        self.assertEqual(specific.get("hookEventName"), "PostToolUse", out)
        updated = specific.get("updatedToolOutput")
        self.assertIsInstance(updated, dict, out)
        return updated

    def saved_path(self, text):
        line = [l for l in text.splitlines() if l.startswith(FULL)]
        self.assertEqual(len(line), 1, text)
        return Path(line[0][len(FULL):])

    def set_context(self, **context):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["context"] = context
        self.config_path.write_text(json.dumps(config), encoding="utf-8")


class UnderTheCap(ToolOutputFixture):
    def test_short_output_is_silent_and_saves_nothing(self):
        out = self.bash("hello\nERROR: but short\n")
        self.assertEqual(out, {})
        self.assertFalse((self.hooks_dir / "s1" / "outputs").exists())
        self.assertEqual(self.ledger(), [])

    def test_exactly_at_the_cap_is_silent(self):
        # 2000 tokens = 8000 chars; the cap is inclusive
        self.assertEqual(self.bash("x" * 7999 + "\n"), {})


class OverTheCap(ToolOutputFixture):
    def test_summary_fits_the_cap_and_keeps_head_tail_and_every_error_line(self):
        text = long_output(errors=ERRORS)
        updated = self.summary(self.bash(text))
        summary = updated["stdout"]
        self.assertLessEqual(tokens(summary), 2000)
        lines = summary.splitlines()
        self.assertTrue(lines[0].startswith("METODO-OUTPUT filtered: 5000 lines"), lines[0])
        self.assertIn("ok step 1 compiled module_1 without trouble", lines)
        self.assertIn("ok step 5000 compiled module_5000 without trouble", lines)
        for error in ERRORS.values():
            self.assertIn(error, lines)
        self.assertNotIn("ok step 2500 compiled module_2500 without trouble", lines)
        self.assertIn("[... ", summary)
        self.assertTrue(lines[-1].startswith(FULL), lines[-1])

    def test_replacement_keeps_the_bash_output_shape(self):
        updated = self.summary(self.bash(long_output(), stderr="warning: noisy\n"))
        self.assertEqual(set(updated), {"stdout", "stderr", "interrupted", "isImage"})
        self.assertEqual((updated["stderr"], updated["interrupted"], updated["isImage"]), ("", False, False))

    def test_full_output_is_saved_outside_the_repo(self):
        text = long_output(errors=ERRORS)
        before = _git(self.repo, "status", "--porcelain")
        path = self.saved_path(self.summary(self.bash(text, stderr="ERROR: stderr says boom\n"))["stdout"])
        self.assertEqual(path, self.hooks_dir / "s1" / "outputs" / "1.txt")
        saved = path.read_text(encoding="utf-8")
        self.assertTrue(saved.startswith(text), "stdout saved byte for byte")
        self.assertIn("ERROR: stderr says boom", saved)
        self.assertFalse(path.resolve().is_relative_to(self.repo.resolve()))
        self.assertEqual(_git(self.repo, "status", "--porcelain"), before)

    def test_stderr_error_line_reaches_the_summary(self):
        summary = self.summary(self.bash(long_output(), stderr="ERROR: stderr says boom\n"))["stdout"]
        self.assertIn("ERROR: stderr says boom", summary.splitlines())

    def test_each_call_gets_its_own_file(self):
        first = self.saved_path(self.summary(self.bash(long_output()))["stdout"])
        second = self.saved_path(self.summary(self.bash(long_output(lines=6000)))["stdout"])
        self.assertEqual((first.name, second.name), ("1.txt", "2.txt"))

    def test_the_run_is_ledgered(self):
        self.bash(long_output())
        line = self.ledger()[-1]
        self.assertEqual((line["hook"], line["kind"], line["tool"]), ("tool_output_filter", "tool-output-filtered", "Bash"))
        self.assertEqual(Path(line["path"]).name, "1.txt")

    def test_many_error_lines_still_fit_and_say_how_many_were_cut(self):
        text = long_output(errors={i: f"ERROR case {i}: something went wrong here" for i in range(30, 4970, 2)})
        summary = self.summary(self.bash(text))["stdout"]
        self.assertLessEqual(tokens(summary), 2000)
        self.assertRegex(summary.splitlines()[0], r"kept \d+ of 2470 matching lines")
        self.assertIn("ERROR case 30: something went wrong here", summary)
        self.assertTrue(summary.splitlines()[-1].startswith(FULL))

    def test_one_huge_line_is_cut_around_the_match(self):
        line = "x" * 20000 + " fatal ERROR here " + "y" * 20000
        summary = self.summary(self.bash(line + "\n"))["stdout"]
        self.assertLessEqual(tokens(summary), 2000)
        self.assertIn("fatal ERROR here", summary)

    def test_the_summary_is_deterministic(self):
        text = long_output(errors=ERRORS)
        a = self.summary(self.bash(text, session="a"))["stdout"]
        b = self.summary(self.bash(text, session="b"))["stdout"]
        strip = lambda s: [l for l in s.splitlines() if not l.startswith(FULL)]  # noqa: E731
        self.assertEqual(strip(a), strip(b))
        self.assertNotEqual(a, b, "only the saved path differs")


class Patterns(ToolOutputFixture):
    def test_lowercase_patterns_ignore_case(self):
        text = long_output(errors={2500: "Build Failed: 3 modules", 2600: "Unhandled Exception in worker"})
        lines = self.summary(self.bash(text))["stdout"].splitlines()
        self.assertIn("Build Failed: 3 modules", lines)
        self.assertIn("Unhandled Exception in worker", lines)

    def test_patterns_with_capitals_are_case_sensitive(self):
        self.set_context(tool_output_patterns=["FAILED"])
        text = long_output(errors={2500: "FAILED test_a", 2600: "failed test_b"})
        lines = self.summary(self.bash(text))["stdout"].splitlines()
        self.assertIn("FAILED test_a", lines)
        self.assertNotIn("failed test_b", lines)


class Configuration(ToolOutputFixture):
    def test_the_threshold_comes_from_the_config(self):
        text = long_output(lines=40)  # ~ 480 tokens, under the default 2000
        self.assertEqual(self.bash(text), {})
        self.set_context(tool_output_max_tokens=100)
        summary = self.summary(self.bash(text, session="s2"))["stdout"]
        self.assertLessEqual(tokens(summary), 100)
        self.assertTrue(summary.splitlines()[-1].startswith(FULL))

    def test_zero_turns_the_filter_off(self):
        self.set_context(tool_output_max_tokens=0)
        self.assertEqual(self.bash(long_output()), {})


class NotFiltered(ToolOutputFixture):
    def test_non_bash_tools_are_never_filtered(self):
        for tool in ("Read", "Grep", "mcp__metodo__docs_lint"):
            self.assertEqual(self.bash(long_output(), tool=tool), {}, tool)
        self.assertFalse((self.hooks_dir / "s1" / "outputs").exists())

    def test_image_output_is_left_alone(self):
        self.assertEqual(self.bash(long_output(), isImage=True), {})

    def test_missing_tool_response_is_silent(self):
        out, _ = self.run_hook("tool_output_filter.py", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                                          "tool_input": {"command": "ls"}})
        self.assertEqual(out, {})

    def test_save_dir_inside_the_target_repo_is_refused(self):
        inside = self.repo / "hook-out"
        before = _git(self.repo, "status", "--porcelain")
        out = self.bash(long_output(), env_extra={"METODO_HOOKS_DIR": str(inside)})
        self.assertEqual(out, {}, "no summary without a saved full output")
        self.assertFalse(inside.exists())
        self.assertEqual(_git(self.repo, "status", "--porcelain"), before)


class ActivationMode(ToolOutputFixture):
    """L10 follow-up: the filter honors hook_mode; OFF passes the output through untouched."""

    def with_tier(self, tier):
        import shutil
        from tests.test_hooks import TOOLS_ROOT
        shutil.copyfile(TOOLS_ROOT / "config" / "activation.json", self.tmp / "activation.json")
        self.write_receipt(verdict=None, state="started")
        path = self.rdd_dir / f"{self.tree}.receipt.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["risk"]["tier"] = tier
        path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_owner_hook_mode_off_passes_through(self):
        self.set_config(enabled=True, mode="warn", hook_modes={"tool_output_filter": "off"})
        self.assertEqual(self.bash(long_output()), {})
        self.assertFalse((self.hooks_dir / "s1" / "outputs").exists())

    def test_bare_profile_passes_through(self):
        self.set_config(enabled=False)
        self.with_tier("low")
        self.assertEqual(self.bash(long_output()), {})
        self.assertFalse((self.hooks_dir / "s1" / "outputs").exists())

    def test_a_short_output_never_computes_the_profile(self):
        # T16 (B-008): the cheap size cap runs before hook_mode; resolving the
        # profile records the session floor (profile.json), a short output must not
        self.with_tier("low")
        (self.hooks_dir / "s1").mkdir(parents=True)
        self.assertEqual(self.bash("ok\n"), {})
        self.assertFalse((self.hooks_dir / "s1" / "profile.json").exists())
        self.assertIn(FULL, self.summary(self.bash(long_output()))["stdout"])
        self.assertTrue((self.hooks_dir / "s1" / "profile.json").exists())

    def test_light_profile_still_filters(self):
        self.with_tier("exempt")
        updated = self.summary(self.bash(long_output()))
        self.assertIn(FULL, updated["stdout"])


class Registration(ToolOutputFixture):
    def test_claude_settings_run_it_on_post_tool_use_bash(self):
        entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
        hits = [e for e in entries if any('"$H/tool_output_filter.py"' in h["command"] for h in e["hooks"])]
        self.assertEqual([e["matcher"] for e in hits], ["Bash"])
        self.assertIn(": metodo-hook;", hits[0]["hooks"][0]["command"])


if __name__ == "__main__":
    import unittest
    unittest.main()
