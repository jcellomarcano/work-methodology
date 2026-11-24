"""Tests for bin/skill-eval.sh, the short entry point of the skill-eval runner (S18).

The wrapper is run with `bash`, as the owner types it. No test passes `--real`, and the `claude`
named by CLAUDE_BIN is a script that leaves a marker, so a test that started it would say so.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "bin" / "skill-eval.sh"
LIB = ROOT / "lib"
EVALS = ROOT / "evals"
FIXTURES = ROOT / "tests" / "fixtures" / "skill-evals"
NOTHING_SPENT = "plan only: nothing was run and nothing was spent"


class WrapperTest(unittest.TestCase):
    """A private kit, evals root and out folder under one temp folder, and a `claude` that must not start."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(os.path.realpath(tmp.name))
        self.kit, self.root, self.out = self.tmp / "kit", self.tmp / "evals", self.tmp / "out"
        shutil.copytree(FIXTURES / "kit", self.kit)
        shutil.copytree(FIXTURES / "good", self.root)
        self.started = self.tmp / "claude-was-started"
        self.claude = self.tmp / "claude"
        self.claude.write_text(f'#!/bin/sh\necho started > "{self.started}"\nexit 1\n')
        self.claude.chmod(0o755)

    def wrapper(self, *args, script=WRAPPER):
        env = {**os.environ, "CLAUDE_BIN": str(self.claude)}
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=env)

    def where(self):
        return ["--root", str(self.root), "--kit", str(self.kit), "--out", str(self.out)]

    def planned(self, res):
        """The skills a plan names, in the order printed; fails unless the command only planned."""
        self.assertEqual((res.returncode, res.stderr), (0, ""), res.stdout)
        self.assertIn(NOTHING_SPENT, res.stdout.splitlines()[-1])
        self.assert_nothing_ran()
        return [line.split(":")[0] for line in res.stdout.splitlines() if not line.startswith((" ", "skill-eval:"))]

    def assert_nothing_ran(self):
        self.assertFalse(self.started.exists(), "the wrapper started `claude`")
        self.assertFalse((self.out / "store").exists(), "a plan stored a result")

    def assert_one_line_exit_2(self, res, said):
        self.assertEqual((res.returncode, res.stdout), (2, ""), res.stderr)
        self.assertEqual(len(res.stderr.splitlines()), 1, res.stderr)
        self.assertTrue(res.stderr.startswith("skill-eval: "), res.stderr)
        self.assertIn(said, res.stderr)
        self.assert_nothing_ran()


class Wrapper(WrapperTest):
    def test_the_wrapper_is_a_thin_exec_of_the_runner_under_an_isolated_python(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn('exec python3 -I "$BENCH_ROOT/lib/skill_eval.py" "$@"', text)

    def test_list_prints_one_line_per_skill_of_the_kit_with_its_cases_and_tiers(self):
        res = self.wrapper("list")
        self.assertEqual((res.returncode, res.stderr), (0, ""), res.stdout)
        lines = res.stdout.splitlines()
        with_a_case = sorted({path.parent.parent.name for path in EVALS.glob("*/*/case.json")})
        self.assertGreaterEqual(len(with_a_case), 17)
        self.assertEqual([line.split(":")[0] for line in lines], with_a_case)
        self.assertIn("change-card: smoke-missing-field [smoke]", lines)
        for line in lines:
            self.assertRegex(line, r"^[a-z0-9-]+: [a-z0-9-]+ \[(smoke|core|deep)\](, [a-z0-9-]+ \[(smoke|core|deep)\])*$")

    def test_list_of_another_root_names_its_skills(self):
        res = self.wrapper("list", "--root", str(self.root))
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        self.assertEqual(res.stdout, "demo-skill: core-trigger [core], smoke-basic [smoke]\n"
                                     "other-skill: smoke-judge [smoke]\n")

    def test_run_with_a_name_plans_that_skill_only_and_spends_nothing(self):
        res = self.wrapper("run", "demo-skill", *self.where())
        self.assertEqual(self.planned(res), ["demo-skill"])
        self.assertIn("  demo-skill/smoke-basic [smoke]: to run, 1 run(s) per arm", res.stdout)

    def test_run_with_two_names_plans_exactly_those(self):
        third = self.root / "third-skill"
        shutil.copytree(self.root / "other-skill", third)
        case_json = third / "smoke-judge" / "case.json"
        case_json.write_text(json.dumps({**json.loads(case_json.read_text()), "skill": "third-skill"}))
        self.assertEqual(self.planned(self.wrapper("run", "third-skill", "demo-skill", *self.where())),
                         ["demo-skill", "third-skill"])

    def test_run_all_plans_every_skill(self):
        self.assertEqual(self.planned(self.wrapper("run", "--all", *self.where())), ["demo-skill", "other-skill"])

    def test_names_together_with_all_are_a_usage_error(self):
        self.assert_one_line_exit_2(self.wrapper("run", "demo-skill", "--all", *self.where()), "--all, not both")

    def test_a_skill_with_no_case_is_one_line_that_names_it(self):
        self.assert_one_line_exit_2(self.wrapper("run", "no-such-skill", *self.where()), "'no-such-skill'")

    def test_validate_and_report_pass_through(self):
        res = self.wrapper("validate", str(self.root))
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        self.assertEqual(res.stdout, "skill-eval: 3 cases, 3 valid, 0 with problems, 0 problems\n")
        res = self.wrapper("report", "--skill", "demo-skill", *self.where())
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        self.assertTrue(res.stdout.startswith("skill-eval report (runner v"), res.stdout)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertNotIn("other-skill", res.stdout)
        self.assert_nothing_ran()

    def test_help_names_every_command_and_the_ways_to_choose_skills(self):
        res = self.wrapper("--help")
        self.assertEqual((res.returncode, res.stderr), (0, ""), res.stdout)
        for command in ("list", "run", "validate", "report"):
            self.assertRegex(res.stdout, rf"(?m)^\s+{command}\s+\S")
        res = self.wrapper("run", "--help")
        self.assertEqual((res.returncode, res.stderr), (0, ""), res.stdout)
        for said in ("SKILL", "--all", "--skill NAME", "--real"):
            self.assertIn(said, res.stdout)

    def test_no_command_is_one_line_and_exits_2(self):
        self.assert_one_line_exit_2(self.wrapper(), "COMMAND")


class SyncedInstance(WrapperTest):
    """An instance gets the script and the modules under bench/, and no case: one line, never a traceback."""

    def setUp(self):
        super().setUp()
        bench = self.tmp / "instance" / "bench"
        shutil.copytree(LIB, bench / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        (bench / "bin").mkdir()
        self.script = pathlib.Path(shutil.copy2(WRAPPER, bench / "bin" / "skill-eval.sh"))

    def test_list_and_run_without_an_evals_root_are_one_line_and_exit_2(self):
        for args in (["list"], ["run"], ["run", "--all"], ["run", "change-card"]):
            with self.subTest(args=args):
                res = self.wrapper(*args, script=self.script)
                self.assert_one_line_exit_2(res, "cannot read the evals root")
                self.assertNotIn("Traceback", res.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
