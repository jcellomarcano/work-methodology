"""lib/engram_rule.py: the Engram read/write rule (odd/research/context/engram.md
section 5, owner decision D4). One test per row of the first-match table, the
kill switch, subagents always off, the byte and result caps, the auto-off
boundary, determinism and the CLI. The rule is pure: nothing here runs the
engram binary or writes to the real ~/.engram/engram.db."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import engram_rule  # noqa: E402

KEYS = {"reads", "writes", "max_bytes", "searches", "results", "reasons", "rule"}
OFF = {"reads": [], "writes": [], "max_bytes": 0, "searches": 0, "results": 0}


def base(**over):
    """A main-session, resolved-project, memory-on start: the rows below the
    guards decide. Every test states only what it changes."""
    inputs = {"memory_env": "", "memory_enabled": True, "binary": True, "caller": "main",
              "sensitive": False, "project_resolved": True, "phase": "start",
              "kind": "standard", "mentions_earlier": False}
    inputs.update(over)
    return inputs


def subset(result, expected):
    return {k: result[k] for k in expected}


class RowTests(unittest.TestCase):
    def test_result_carries_exactly_the_contract_keys(self):
        self.assertEqual(set(engram_rule.decide(base())), KEYS)

    def test_row1_memory_disabled_in_config_is_all_off(self):
        got = engram_rule.decide(base(memory_enabled=False, phase="resume"))
        self.assertEqual(got["rule"], 1)
        self.assertEqual(subset(got, OFF), OFF)

    def test_row1_no_binary_is_all_off(self):
        got = engram_rule.decide(base(binary=False, phase="compact"))
        self.assertEqual(got["rule"], 1)
        self.assertEqual(subset(got, OFF), OFF)
        self.assertTrue(any("binary" in r for r in got["reasons"]))

    def test_row2_subagent_is_all_off(self):
        got = engram_rule.decide(base(caller="subagent", phase="resume", kind="multi-session"))
        self.assertEqual(got["rule"], 2)
        self.assertEqual(subset(got, OFF), OFF)

    def test_row3_sensitive_reads_explicit_project_only_and_never_writes(self):
        got = engram_rule.decide(base(sensitive=True, phase="resume"))
        self.assertEqual(got["rule"], 3)
        self.assertEqual(got["writes"], [])
        self.assertEqual(got["reads"], ["mem_search"])
        self.assertEqual((got["searches"], got["results"], got["max_bytes"]), (1, 5, 0))
        self.assertTrue(any("explicit project" in r for r in got["reasons"]))
        self.assertTrue(any("all_projects" in r for r in got["reasons"]))

    def test_row4_unresolved_project_reads_explicit_project_only(self):
        got = engram_rule.decide(base(project_resolved=False, phase="resume"))
        self.assertEqual(got["rule"], 4)
        self.assertEqual(got["writes"], [])
        self.assertEqual(got["reads"], ["mem_search"])
        self.assertTrue(any("explicit project" in r for r in got["reasons"]))

    def test_row5_just_compacted_reads_compact_context_once(self):
        got = engram_rule.decide(base(phase="compact"))
        self.assertEqual(got["rule"], 5)
        self.assertEqual(got["reads"], ["mem_context"])
        self.assertEqual((got["max_bytes"], got["searches"], got["results"]), (4096, 0, 0))
        self.assertEqual(got["writes"], ["session_summary"])

    def test_row6_resume_reads_task_doc_first_then_context_and_two_searches(self):
        got = engram_rule.decide(base(phase="resume"))
        self.assertEqual(got["rule"], 6)
        self.assertEqual(got["reads"], ["task_doc", "mem_context", "mem_search"])
        self.assertEqual((got["max_bytes"], got["searches"], got["results"]), (4096, 2, 5))
        self.assertEqual(got["writes"], ["decision", "handoff"])

    def test_row7_new_multi_session_task_searches_once_before_exploring(self):
        for phase in ("start", "task"):
            got = engram_rule.decide(base(phase=phase, kind="multi-session"))
            self.assertEqual(got["rule"], 7, phase)
            self.assertEqual(got["reads"], ["mem_search"])
            self.assertEqual((got["max_bytes"], got["searches"], got["results"]), (0, 1, 5))
            self.assertEqual(got["writes"], ["decision", "handoff"])

    def test_row8_trivial_reads_nothing_and_writes_only_the_non_obvious(self):
        got = engram_rule.decide(base(kind="trivial", mentions_earlier=True))
        self.assertEqual(got["rule"], 8)
        self.assertEqual(got["reads"], [])
        self.assertEqual((got["max_bytes"], got["searches"], got["results"]), (0, 0, 0))
        self.assertEqual(got["writes"], ["non_obvious_bugfix", "non_obvious_decision"])

    def test_row9_searches_once_only_when_the_prompt_names_earlier_work(self):
        quiet = engram_rule.decide(base(phase="task"))
        self.assertEqual(quiet["rule"], 9)
        self.assertEqual((quiet["reads"], quiet["searches"], quiet["results"]), ([], 0, 0))
        self.assertEqual(quiet["writes"], ["decision"])
        named = engram_rule.decide(base(phase="task", mentions_earlier=True))
        self.assertEqual(named["rule"], 9)
        self.assertEqual((named["reads"], named["searches"], named["results"]), (["mem_search"], 1, 5))

    def test_first_match_wins_in_table_order(self):
        # every guard true at once: row 1 is the first match, then each guard removed in turn
        inputs = base(memory_enabled=False, caller="subagent", sensitive=True, project_resolved=False,
                      phase="compact", kind="trivial", mentions_earlier=True)
        order = [("memory_enabled", True, 2), ("caller", "main", 3), ("sensitive", False, 4),
                 ("project_resolved", True, 5), ("phase", "resume", 6), ("phase", "start", 8),
                 ("kind", "multi-session", 7)]
        self.assertEqual(engram_rule.decide(inputs)["rule"], 1)
        for key, value, row in order:
            inputs[key] = value
            self.assertEqual(engram_rule.decide(inputs)["rule"], row, (key, value))


class KillSwitchTests(unittest.TestCase):
    def test_metodo_memory_off_beats_every_other_input(self):
        for value in ("off", "OFF", "Off"):
            for phase in engram_rule.PHASES:
                got = engram_rule.decide(base(memory_env=value, phase=phase, kind="multi-session"))
                self.assertEqual(got["rule"], 1, (value, phase))
                self.assertEqual(subset(got, OFF), OFF)
                self.assertTrue(any("METODO_MEMORY" in r for r in got["reasons"]))

    def test_config_disabled_names_the_config_key(self):
        got = engram_rule.decide(base(memory_enabled=False))
        self.assertTrue(any("memory.enabled" in r for r in got["reasons"]))

    def test_other_env_values_do_not_switch_memory_off(self):
        for value in ("", "on", "1"):
            self.assertNotEqual(engram_rule.decide(base(memory_env=value))["rule"], 1, value)


class SubagentTests(unittest.TestCase):
    def test_a_subagent_never_reads_or_writes_in_any_combination(self):
        for phase in engram_rule.PHASES:
            for kind in engram_rule.KINDS:
                for flag in (False, True):
                    got = engram_rule.decide(base(caller="subagent", phase=phase, kind=kind,
                                                  mentions_earlier=flag, sensitive=flag,
                                                  project_resolved=not flag))
                    self.assertIn(got["rule"], (1, 2))
                    self.assertEqual(subset(got, OFF), OFF, (phase, kind, flag))


class CapTests(unittest.TestCase):
    def test_no_row_exceeds_the_byte_search_and_result_caps(self):
        for phase in engram_rule.PHASES:
            for kind in engram_rule.KINDS:
                for flags in ((False, True, False), (True, True, False), (False, False, False),
                              (False, True, True)):
                    sensitive, resolved, mentions = flags
                    got = engram_rule.decide(base(phase=phase, kind=kind, sensitive=sensitive,
                                                  project_resolved=resolved, mentions_earlier=mentions))
                    self.assertLessEqual(got["max_bytes"], engram_rule.CONTEXT_MAX_BYTES)
                    self.assertLessEqual(got["searches"], 2)
                    self.assertLessEqual(got["results"], engram_rule.SEARCH_LIMIT)
                    # the byte cap is set exactly when mem_context is read, searches when mem_search is
                    self.assertEqual(got["max_bytes"] > 0, "mem_context" in got["reads"])
                    self.assertEqual(got["searches"] > 0, "mem_search" in got["reads"])
                    self.assertEqual(got["results"] > 0, got["searches"] > 0)
                    self.assertNotIn("all_projects", got["reads"])

    def test_constants_match_the_research_rule(self):
        self.assertEqual(engram_rule.CONTEXT_MAX_BYTES, 4096)
        self.assertEqual(engram_rule.SEARCH_LIMIT, 5)


class InputValidationTests(unittest.TestCase):
    def test_unknown_phase_caller_or_kind_is_an_error(self):
        for bad in ({"phase": "later"}, {"caller": "parent"}, {"kind": "huge"}):
            with self.assertRaises(ValueError):
                engram_rule.decide(base(**bad))

    def test_missing_inputs_take_the_safe_defaults(self):
        # absent binary/enabled facts are not assumed true: the rule stays off
        got = engram_rule.decide({"phase": "resume"})
        self.assertEqual(got["rule"], 1)
        self.assertEqual(subset(got, OFF), OFF)


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_give_the_same_output_and_inputs_are_not_mutated(self):
        inputs = base(phase="resume")
        frozen = dict(inputs)
        first = engram_rule.decide(inputs)
        for _ in range(5):
            self.assertEqual(engram_rule.decide(inputs), first)
        self.assertEqual(inputs, frozen)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(engram_rule.decide(dict(frozen)), sort_keys=True))


class ShouldDisableTests(unittest.TestCase):
    def test_nineteen_sessions_never_disable(self):
        self.assertFalse(engram_rule.should_disable({"sessions": 19, "recall_used_rate": 0.0}))

    def test_twenty_sessions_below_the_rate_disable(self):
        self.assertTrue(engram_rule.should_disable({"sessions": 20, "recall_used_rate": 0.19}))

    def test_twenty_sessions_at_the_rate_keep_memory_on(self):
        self.assertFalse(engram_rule.should_disable({"sessions": 20, "recall_used_rate": 0.2}))

    def test_rate_from_counts(self):
        self.assertFalse(engram_rule.should_disable({"sessions": 20, "recalls": 5, "recalls_used": 1}))
        self.assertTrue(engram_rule.should_disable({"sessions": 25, "recalls": 100, "recalls_used": 19}))

    def test_twenty_sessions_with_no_recall_at_all_disable(self):
        self.assertTrue(engram_rule.should_disable({"sessions": 20, "recalls": 0, "recalls_used": 0}))

    def test_missing_stats_never_disable(self):
        self.assertFalse(engram_rule.should_disable({}))
        self.assertFalse(engram_rule.should_disable({"sessions": 30}))

    def test_thresholds_are_the_d4_values(self):
        self.assertEqual(engram_rule.DISABLE_MIN_SESSIONS, 20)
        self.assertEqual(engram_rule.DISABLE_MIN_RATE, 0.2)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engram-rule-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = self.tmp / "project.json"
        self.config.write_text(json.dumps({"memory": {"enabled": True}}), encoding="utf-8")

    def run_main(self, argv, env, binary="/fake/engram"):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(engram_rule.shutil, "which", return_value=binary) as which, \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("engram must not run")), \
                contextlib.redirect_stdout(out):
            code = engram_rule.main(argv)
        which.assert_called_with("engram")
        return code, json.loads(out.getvalue())

    def test_cli_resume_on_the_main_session(self):
        env = {"METODO_MEMORY": "", "METODO_PROJECT_CONFIG": str(self.config)}
        code, got = self.run_main(["--phase", "resume"], env)
        self.assertEqual(code, 0)
        self.assertEqual(got["rule"], 6)
        self.assertEqual(got["max_bytes"], 4096)

    def test_cli_flags_reach_the_rule(self):
        env = {"METODO_MEMORY": "", "METODO_PROJECT_CONFIG": str(self.config)}
        cases = [(["--phase", "start", "--caller", "subagent"], 2), (["--phase", "start", "--sensitive"], 3),
                 (["--phase", "task", "--trivial"], 8), (["--phase", "task", "--mentions-earlier"], 9),
                 (["--phase", "compact"], 5), (["--phase", "start", "--multi-session"], 7),
                 (["--phase", "start", "--project-unresolved"], 4)]
        for argv, row in cases:
            self.assertEqual(self.run_main(argv, env)[1]["rule"], row, argv)
        self.assertEqual(self.run_main(["--phase", "task", "--mentions-earlier"], env)[1]["searches"], 1)

    def test_cli_reads_the_config_kill_switch_and_a_missing_binary(self):
        env = {"METODO_MEMORY": "", "METODO_PROJECT_CONFIG": str(self.config)}
        self.assertEqual(self.run_main(["--phase", "resume"], env, binary=None)[1]["rule"], 1)
        self.config.write_text(json.dumps({"memory": {"enabled": False}}), encoding="utf-8")
        self.assertEqual(self.run_main(["--phase", "resume"], env)[1]["rule"], 1)

    def test_cli_as_a_process_honours_metodo_memory_off(self):
        env = dict(os.environ, METODO_MEMORY="off", METODO_PROJECT_CONFIG=str(self.config))
        proc = subprocess.run([sys.executable, str(TOOLS_ROOT / "lib" / "engram_rule.py"), "--phase", "resume"],
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual(got["rule"], 1)
        self.assertEqual(set(got), KEYS)

    def test_cli_rejects_an_unknown_phase(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            engram_rule.main(["--phase", "later"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
