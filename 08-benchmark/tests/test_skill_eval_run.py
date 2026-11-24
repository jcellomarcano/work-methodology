"""Tests for the skill-eval runner: lib/skill_eval_native.py and lib/skill_eval_run.py.

No test starts a real `claude`: the binary is the stub `fixtures/skill-evals/stub/claude`, named
by CLAUDE_BIN as the A/B runner does. The stub plays a scenario and leaves a result file and kept
directories shaped like the real ones. Every command runs under `python3 -I`.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import skill_eval  # noqa: E402
import skill_eval_native as native  # noqa: E402
import skill_eval_run as runner  # noqa: E402

LIB = ROOT / "lib" / "skill_eval.py"
FIXTURES = ROOT / "tests" / "fixtures" / "skill-evals"
STUB = FIXTURES / "stub" / "claude"
SMOKE = "demo-skill/smoke-basic"
FIXED = {"src/app.py": 'def greeting():\n    return "Hello, world."\n'}
GOOD_RUN = {"write": FIXED}
BOTH_GOOD = {"smoke-basic": {"with": GOOD_RUN, "without": GOOD_RUN}}


def unseal(folder):
    """Give back the permissions a kept directory took away, so a temp folder can be removed."""
    for current, dirnames, _filenames in os.walk(folder):
        for name in dirnames:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                os.chmod(path, 0o700)


class RunnerTest(unittest.TestCase):
    """A private kit, evals root, out folder and stub `claude` under one temp folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(os.path.realpath(tmp.name))
        self.addCleanup(unseal, self.tmp)
        self.kit = self.tmp / "kit"
        shutil.copytree(FIXTURES / "kit", self.kit)
        self.root = self.tmp / "evals"
        shutil.copytree(FIXTURES / "good", self.root)
        self.out, self.kept = self.tmp / "out", self.tmp / "kept"
        self.kept.mkdir()
        self.log, self.scenario = self.tmp / "stub.log", self.tmp / "scenario.json"
        self.claude = self.tmp / "claude"  # a wrapper, so the test does not lean on a file mode
        self.claude.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{STUB}" "$@"\n')
        self.claude.chmod(0o755)
        self.case = self.root / "demo-skill" / "smoke-basic"

    def play(self, **scenario):
        self.scenario.write_text(json.dumps(scenario))

    def cli(self, *args, **env):
        env = {**os.environ, "CLAUDE_BIN": str(self.claude), "STUB_LOG": str(self.log),
               "STUB_KEPT": str(self.kept), "STUB_SCENARIO": str(self.scenario), **env}
        return subprocess.run([sys.executable, "-I", str(LIB), *args], capture_output=True, text=True, env=env)

    def where(self):
        return ["--root", str(self.root), "--kit", str(self.kit), "--out", str(self.out)]

    def run_real(self, *extra, skill="demo-skill", tier="smoke", **env):
        tier_args = ["--tier", tier] if tier else []
        return self.cli("run", "--skill", skill, *self.where(), *tier_args, "--real", *extra, **env)

    def report(self, *extra, skill="demo-skill"):
        return self.cli("report", "--skill", skill, *self.where(), *extra)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def stored(self, case=SMOKE):
        files = sorted((self.out / "store" / case).glob("*.json"))
        self.assertEqual(len(files), 1, f"expected one stored result for {case}, found {files}")
        return json.loads(files[0].read_text())

    def statuses(self, case=SMOKE):
        record = self.stored(case)
        return {arm: [run["status"] for run in record["arms"][arm]] for arm in ("with", "without")}

    def edit_case(self, **changes):
        raw = json.loads((self.case / "case.json").read_text())
        raw.update(changes)
        (self.case / "case.json").write_text(json.dumps(raw))

    def assert_clean(self, res, code):
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stdout + res.stderr)


class Plan(RunnerTest):
    def test_run_without_real_prints_the_plan_and_its_ceiling_and_spends_nothing(self):
        res = self.cli("run", "--skill", "demo-skill", *self.where())
        self.assert_clean(res, 0)
        for said in ("demo-skill: 2 case(s), 2 to run, 0 cached", "arms with, without", "8 native run(s)",
                     "ceiling USD 0.50", "demo-skill/core-trigger [core]: to run, 3 run(s) per arm",
                     "demo-skill/smoke-basic [smoke]: to run, 1 run(s) per arm",
                     "plan only: nothing was run and nothing was spent"):
            self.assertIn(said, res.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.out / "store").exists())

    def test_plan_is_printed_for_a_skill_the_kit_does_not_hold(self):
        shutil.rmtree(self.kit / "02-skills" / "demo-skill")
        res = self.cli("run", "--skill", "demo-skill", *self.where())
        self.assert_clean(res, 0)
        self.assertIn("skill folder not found", res.stdout)
        self.assertEqual(self.calls(), [])

    def test_real_run_prints_the_cost_ceiling_first(self):
        self.play(cases=BOTH_GOOD)
        res = self.run_real("--max-cost-usd", "0.25")
        self.assert_clean(res, 0)
        self.assertTrue(res.stdout.splitlines()[0].startswith("skill-eval: cost ceiling USD 0.25"), res.stdout)

    def test_skill_with_no_case_and_bad_flags_are_one_line_and_exit_2(self):
        for args, said in ((["--skill", "no-such-skill"], "no case"), (["--tier", "nightly"], "nightly"),
                           (["--max-cost-usd", "0"], "--max-cost-usd"), (["--runs", "0"], "--runs")):
            res = self.cli("run", *self.where(), *args)
            self.assertEqual((res.returncode, res.stdout), (2, ""), res.stderr)
            self.assertEqual(len(res.stderr.splitlines()), 1, res.stderr)
            self.assertTrue(res.stderr.startswith("skill-eval: "), res.stderr)
            self.assertIn(said, res.stderr)

    def test_plan_with_json_writes_the_plan_to_the_file_and_spends_nothing(self):  # B1
        self.play(cases=BOTH_GOOD)
        self.assert_clean(self.run_real(), 0)  # smoke-basic is stored, so the plan has a cached case
        target = self.tmp / "plan.json"
        res = self.cli("run", "--skill", "demo-skill", *self.where(), "--max-cost-usd", "0.25", "--json", str(target))
        self.assert_clean(res, 0)
        self.assertIn("plan only: nothing was run and nothing was spent", res.stdout)
        self.assertTrue(target.is_file(), "the plan was not written to the file --json names")
        data = json.loads(target.read_text())
        self.assertEqual((data["mode"], data["runner_version"], data["max_cost_usd"], data["ceiling_usd"]),
                         ("plan", runner.RUNNER_VERSION, 0.25, 0.25))
        self.assertNotIn("thresholds", data)  # a plan is not a report
        (skill,) = data["skills"]
        self.assertEqual((skill["skill"], skill["arms"], skill["to_run"], skill["cached"], skill["native_runs"],
                          skill["ceiling_usd"]), ("demo-skill", ["with", "without"], 1, 1, 6, 0.25))
        cases = {case["case"]: case for case in skill["cases"]}
        self.assertEqual({name: (case["tier"], case["state"], case["runs"]) for name, case in cases.items()},
                         {"demo-skill/core-trigger": ("core", "to run", 3), "demo-skill/smoke-basic": ("smoke", "cached", 1)})
        self.assertEqual(cases[SMOKE]["hash"], self.stored()["hash"])
        self.assertEqual(len(self.calls()), 1, "a plan must not start the tool")
        res = self.cli("run", "--skill", "demo-skill", *self.where(), "--json", str(self.tmp / "absent" / "plan.json"))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("skill-eval: cannot write", res.stderr)

    def test_json_file_of_a_real_run_keeps_its_shape(self):  # previous behavior of --json with --real
        self.play(cases=BOTH_GOOD)
        target = self.tmp / "report.json"
        self.assert_clean(self.run_real("--json", str(target)), 0)
        data = json.loads(target.read_text())
        self.assertEqual(sorted(data), ["runner_version", "skills", "thresholds"])
        (skill,) = data["skills"]
        self.assertEqual(sorted(skill), ["cached", "cases", "measured_as", "reasons", "selected", "signal", "size_tokens",
                                         "skill", "summary", "token_method", "verdict", "without_arm"])
        self.assertEqual(sorted(skill["cases"][0]), ["arms", "case", "hash", "state", "tier"])
        for key in ("arms", "cases", "runs_per_arm", "with_score", "without_score", "delta", "cheated", "spend_usd"):
            self.assertIn(key, skill["summary"])

    def test_exempt_path_that_no_staged_file_matches_is_said_in_the_plan(self):
        self.edit_case(ablation_exempt_paths=["notes.txt", "absent/**"])
        res = self.cli("run", "--skill", "demo-skill", *self.where())
        self.assert_clean(res, 0)
        self.assertIn("ablation_exempt_paths 'absent/**' matches no staged file", res.stdout)
        self.assertNotIn("'notes.txt' matches no staged file", res.stdout)


class NativeSuite(RunnerTest):
    def setUp(self):
        super().setUp()
        self.play(cases=BOTH_GOOD)

    def test_every_native_invocation_carries_the_protecting_flags(self):
        self.assert_clean(self.run_real("--max-cost-usd", "0.25"), 0)
        self.assert_clean(self.run_real("--no-cache", "--runs", "2", "--model", "haiku", tier=None), 0)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            argv = call["argv"]
            self.assertEqual(argv[:2], ["plugin", "eval"])
            for flag in native.REQUIRED_FLAGS:
                self.assertIn(flag, argv)
            for flag in ("--output-dir", "--json"):
                self.assertTrue(argv[argv.index(flag) + 1].startswith(str(self.out) + os.sep), argv)
            self.assertGreater(float(argv[argv.index("--max-cost-usd") + 1]), 0)
            self.assertNotIn("--publish-report", argv)
        self.assertEqual(calls[0]["argv"][calls[0]["argv"].index("--max-cost-usd") + 1], "0.25")

    def test_build_argv_never_drops_a_protecting_flag(self):
        self.assertEqual(native.REQUIRED_FLAGS, ("--no-publish", "--trust-plugin", "--json", "--keep-temp",
                                                 "--output-dir", "--max-cost-usd"))
        for options in ({}, {"tier": "smoke"}, {"runs": 3, "model": "haiku", "judge_model": "haiku"},
                        {"allow_tools": ["Edit"], "scaffold": True}, {"ablation": "none", "real_servers": True}):
            argv = native.build_argv("claude", "/p", "/o", max_cost_usd=0.5, **options)
            for flag in native.REQUIRED_FLAGS:
                self.assertIn(flag, argv, options)

    def test_plugin_holds_only_that_skill_and_each_case_in_the_native_layout(self):
        self.assert_clean(self.run_real(), 0)
        call = self.calls()[0]
        self.assertIn(".claude-plugin/plugin.json", call["files"])
        self.assertEqual([f for f in call["files"] if f.startswith("skills/")], ["skills/demo-skill/SKILL.md"])
        self.assertIn("evals/smoke-basic/case.yaml", call["files"])
        self.assertFalse([f for f in call["files"] if "testdata" in f or "validators" in f], call["files"])
        case = call["cases"]["smoke-basic"]
        self.assertEqual((case["schema_version"], case["name"], case["runs"]), ("1.1", "smoke-basic", 1))
        self.assertEqual(case["execution"]["prompt"], (self.case / "prompt.md").read_text())
        self.assertEqual((case["execution"]["max_turns"], case["execution"]["timeout_seconds"]), (8, 300))

    def test_tier_becomes_a_native_tag_and_the_tier_flag_selects_it(self):
        self.assert_clean(self.run_real(tier="smoke"), 0)
        self.assert_clean(self.run_real("--no-cache", tier=None), 0)
        smoke, every = self.calls()
        self.assertEqual(smoke["argv"][smoke["argv"].index("--tag") + 1], "smoke")
        self.assertEqual({name: case["tags"] for name, case in smoke["cases"].items()}, {"smoke-basic": ["smoke"]})
        self.assertNotIn("--tag", every["argv"])
        self.assertEqual({name: case["tags"] for name, case in every["cases"].items()},
                         {"core-trigger": ["core"], "smoke-basic": ["smoke"]})

    def test_expected_skills_become_skill_tool_graders(self):
        self.assert_clean(self.run_real(), 0)
        graders = self.calls()[0]["cases"]["smoke-basic"]["graders"]
        triggers = [g for g in graders if g["type"] == "tool_used"]
        self.assertEqual([(g["name"], g["tool"]) for g in triggers], [("trigger-01", "Skill")])
        self.assertRegex(json.dumps({"skill": "demo-skill:demo-skill"}), triggers[0]["input_match"])

    def test_forbidden_paths_become_graders_that_fail_a_run_touching_them(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "touch": ["secrets/key.txt"]}, "without": GOOD_RUN}})
        self.assert_clean(self.run_real(), 0)
        graders = [g for g in self.calls()[0]["cases"]["smoke-basic"]["graders"] if g["name"].startswith("forbidden")]
        self.assertEqual([(g["type"], g["target"], g["match"]) for g in graders], [("regex", "trace", "not_contains")] * 2)
        record = self.stored()  # the stub applies each pattern to the trace, as the real tool does
        self.assertEqual(record["arms"]["with"][0]["native_graders"]["forbidden-01"], False)
        self.assertEqual(record["arms"]["with"][0]["native_graders"]["forbidden-02"], True)
        self.assertEqual(record["arms"]["without"][0]["native_graders"]["forbidden-01"], True)

    def test_expectations_become_one_llm_grader_each(self):
        self.assert_clean(self.run_real(skill="other-skill"), 0)
        graders = self.calls()[0]["cases"]["smoke-judge"]["graders"]
        self.assertEqual([(g["name"], g["type"]) for g in graders], [("expect-01", "llm"), ("expect-02", "llm")])
        self.assertIn("The answer is one paragraph.", graders[0]["criteria"])
        self.assertIn("The answer states a next step.", graders[1]["criteria"])

    def test_setup_files_become_a_scaffold_script_that_stages_them(self):
        check = self.case / "validators" / "check_output.py"
        check.write_text("import pathlib, sys\n"
                         "ok = pathlib.Path('notes.txt').read_text() == 'The greeting must read: Hello, world.\\n'\n"
                         "sys.exit(0 if ok and pathlib.Path('src/app.py').is_file() else 1)\n")
        self.play()
        self.assert_clean(self.run_real(), 0)
        call = self.calls()[0]
        self.assertIn("--scaffold", call["argv"])
        self.assertEqual(call["cases"]["smoke-basic"]["context"], {"scaffold_script": "scaffold.sh"})
        for staged in ("scaffold.sh", "files/notes.txt", "files/src/app.py"):
            self.assertIn(f"evals/smoke-basic/{staged}", call["files"])
        self.assertEqual(self.statuses(), {"with": ["passed"], "without": ["passed"]})  # the staged files were there

    def test_gated_tools_of_a_case_are_granted_and_skill_is_always_allowed(self):
        self.edit_case(allowed_tools=["Read", "Edit"])
        self.assert_clean(self.run_real(), 0)
        call = self.calls()[0]
        self.assertEqual(call["argv"][call["argv"].index("--allow-tools") + 1], "Edit")
        self.assertEqual(call["cases"]["smoke-basic"]["execution"]["allowed_tools"], ["Read", "Edit", "Skill"])


class NativeFailures(RunnerTest):
    def assert_not_measured(self, res, said):
        self.assert_clean(res, 1)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertIn(said, res.stdout)
        errors = [line for line in res.stderr.splitlines() if line.startswith("skill-eval: demo-skill: ")]
        self.assertEqual(len(errors), 1, res.stderr)
        self.assertIn(said, errors[0])
        self.assertFalse((self.out / "store").exists(), "a failed run must not be stored as a result")

    def test_native_exit_1_is_not_measured_with_its_reason(self):
        self.play(exit=1, stderr="case file failed to load", cases=BOTH_GOOD)
        self.assert_not_measured(self.run_real(), "the native tool exited 1")

    def test_native_exit_2_is_not_measured_and_its_kept_folders_are_removed(self):
        self.play(exit=2, partial=True, cases=BOTH_GOOD)
        self.assert_not_measured(self.run_real(), "the native tool exited 2")
        self.assertEqual(list(self.kept.iterdir()), [])

    def test_partial_result_is_not_measured_even_on_exit_0(self):
        self.play(partial=True, cases=BOTH_GOOD)
        self.assert_not_measured(self.run_real(), "partial")

    def test_missing_result_file_is_not_measured(self):
        self.play(result="none")
        self.assert_not_measured(self.run_real(), "left no result file")

    def test_malformed_result_file_is_not_measured(self):
        for kind in ("garbage", "shape"):
            self.play(result=kind)
            self.assert_not_measured(self.run_real(), "result file")

    def test_binary_that_cannot_start_is_not_measured(self):
        self.assert_not_measured(self.run_real(CLAUDE_BIN=str(self.tmp / "no-such-claude")), "cannot start")

    def test_relative_claude_bin_is_resolved_where_the_command_was_started(self):
        self.play(cases=BOTH_GOOD)
        env = {**os.environ, "CLAUDE_BIN": "./claude", "STUB_LOG": str(self.log), "STUB_KEPT": str(self.kept),
               "STUB_SCENARIO": str(self.scenario)}
        res = subprocess.run([sys.executable, "-I", str(LIB), "run", "--skill", "demo-skill", *self.where(),
                              "--tier", "smoke", "--real"], capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_skill_that_cannot_be_packed_is_not_measured_and_nothing_runs(self):
        os.remove(self.kit / "02-skills" / "demo-skill" / "BUILD.json")
        self.assert_not_measured(self.run_real(), "cannot be packed")
        self.assertEqual(self.calls(), [])

    def test_result_that_lacks_a_case_is_not_measured(self):
        self.play(drop=["smoke-basic"], cases=BOTH_GOOD)
        self.assert_not_measured(self.run_real(), "has no case smoke-basic")


class ReviewFindings(RunnerTest):
    """The findings the native review of the runner left (feature skill-evals, L12)."""

    def test_native_run_that_outlives_its_timeout_is_stopped_with_the_processes_it_started(self):  # R4-native-timeout-leaks-and-may-hang
        slow = self.tmp / "slow"
        slow.write_text(f'#!/bin/sh\nsleep 20 &\necho $! > "{self.tmp}/child.pid"\nwait\n')
        slow.chmod(0o755)
        started = time.monotonic()
        with self.assertRaises(native.NativeError) as caught:
            native.run_native([str(slow)], self.tmp, timeout=1)
        self.assertLess(time.monotonic() - started, 12, "the runner waited for a process the tool had started")
        self.assertIn("did not end within 1s", str(caught.exception))
        child = int((self.tmp / "child.pid").read_text())
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail(f"process {child}, started by the stopped tool, is still running")

    def test_native_run_that_ends_gives_its_exit_code_and_both_outputs(self):  # previous behavior of run_native
        quick = self.tmp / "quick"
        quick.write_text("#!/bin/sh\necho said\necho warned >&2\nexit 3\n")
        quick.chmod(0o755)
        self.assertEqual(native.run_native([str(quick)], self.tmp, timeout=30), (3, "said\n", "warned\n"))

    def test_unexpected_error_in_one_skill_does_not_end_the_run(self):  # R4-run-loop-catches-only-native-error
        (self.out / "native").mkdir(parents=True)
        (self.out / "native" / "demo-skill").write_text("a file where the runner needs a folder\n")
        self.play(cases=BOTH_GOOD)
        res = self.cli("run", *self.where(), "--real")
        self.assert_clean(res, 1)
        self.assertIn("demo-skill: not measured", res.stdout)
        errors = [line for line in res.stderr.splitlines() if line.startswith("skill-eval: demo-skill: unexpected error")]
        self.assertEqual(len(errors), 1, res.stderr)
        self.assertEqual(len(self.calls()), 1, "the other skill must still reach the tool")
        self.assertTrue(any(line.startswith("other-skill: ") for line in res.stdout.splitlines()), res.stdout)
        self.assertNotIn("other-skill: not measured - unexpected", res.stdout)

    def test_stored_result_is_not_reused_for_another_model_or_run_count(self):  # R3-cache-ignores-run-settings
        self.play(cases=BOTH_GOOD)
        self.assert_clean(self.run_real("--model", "haiku"), 0)
        self.assert_clean(self.run_real("--model", "haiku"), 0)
        self.assertEqual(len(self.calls()), 1)  # previous behavior: the same settings are served from the store
        self.assert_clean(self.run_real("--model", "sonnet"), 0)
        self.assertEqual(len(self.calls()), 2)
        self.assert_clean(self.run_real("--model", "sonnet", "--judge-model", "sonnet"), 0)
        self.assertEqual(len(self.calls()), 3)
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--model", "sonnet",
                        "--judge-model", "sonnet", "--runs", "2")
        self.assert_clean(plan, 0)
        self.assertIn("demo-skill/smoke-basic [smoke]: to run, 2 run(s) per arm", plan.stdout)
        self.assertIn("the stored result used other settings: runs per arm 1, now 2", plan.stdout)
        self.assertEqual(len(self.calls()), 3)
        shown = self.report()  # previous behavior: the report shows what is stored, whatever it was run with
        self.assert_clean(shown, 0)
        self.assertIn("with: passed | without: passed", shown.stdout)

    def test_run_the_tool_reports_as_errored_is_errored_also_when_it_left_no_trace(self):  # R3-errored-run-without-trace-unreadable
        for trace in ("missing", None):  # None: previous behavior, an errored run with its trace
            broken = {**GOOD_RUN, "error": "API error 529", **({"trace": trace} if trace else {})}
            self.play(cases={"smoke-basic": {"with": broken, "without": GOOD_RUN}})
            res = self.run_real("--no-cache")
            self.assert_clean(res, 0)
            self.assertEqual(self.statuses()["with"], ["errored"], trace)
            self.assertIn("API error 529", res.stdout)
            shutil.rmtree(self.out / "store")


class ClosingPass(RunnerTest):
    """The findings the native reviews of T4 and T5 left for the closing pass (feature skill-evals, L17 and L19)."""

    def test_native_run_that_ends_leaves_no_process_of_its_group_behind(self):  # R3-normal-exit-leaves-group, R4-001
        leaves = self.tmp / "leaves"
        leaves.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{self.tmp}/left.pid"\necho said\nexit 4\n')
        leaves.chmod(0o755)

        def end(pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass

        result = native.run_native([str(leaves)], self.tmp, timeout=30)
        child = int((self.tmp / "left.pid").read_text())
        self.addCleanup(end, child)
        self.assertEqual(result, (4, "said\n", ""))  # previous behavior: the exit code and both outputs
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail(f"process {child}, started by a tool that has ended, is still running")

    def test_declaration_that_cannot_be_read_at_all_declares_nothing_and_is_never_a_traceback(self):  # R3-declared-needs-narrow-except
        declaration = self.kit / "02-skills" / "demo-skill" / "BUILD.json"
        declaration.write_text("[" * 200000)  # nested past what the JSON reader can follow: not a ValueError
        self.assertEqual(runner.declared_needs({"kit": self.kit}, "demo-skill"), ([], False))
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke")
        self.assert_clean(plan, 0)
        self.assertIn("demo-skill/smoke-basic [smoke]: to run", plan.stdout)
        self.play(cases=BOTH_GOOD)
        res = self.run_real()  # the run itself says the skill cannot be packed, in one line
        self.assert_clean(res, 1)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertEqual(len([line for line in res.stderr.splitlines() if line.startswith("skill-eval: demo-skill: ")]), 1,
                         res.stderr)
        self.assertEqual(self.calls(), [])

    def test_declaration_that_can_be_read_still_says_what_the_skill_needs(self):  # previous behavior of declared_needs
        skill = self.kit / "02-skills" / "demo-skill"
        (skill / "BUILD.json").write_text(json.dumps({"schema_version": 1, "agent_skill": {
            "srcs": ["SKILL.md"], "deps": ["mcp__metodo__demo_tool", "03-tools/lib"]}}))
        with open(skill / "SKILL.md", "a") as handle:
            handle.write("\nRun `__TOOLS_DEFAULT__/lib/x.py`.\n")
        self.assertEqual(runner.declared_needs({"kit": self.kit}, "demo-skill"), (["mcp__metodo__demo_tool"], True))
        self.assertEqual(runner.declared_needs({"kit": self.kit}, "other-skill"), ([], False))


class WhatARunDid(RunnerTest):
    """The trace is removed once it is scored, so the stored result keeps the tools a run called."""

    def test_stored_run_lists_the_tools_it_called_in_order_and_the_report_shows_them_for_a_run_that_failed(self):
        self.play(cases={"smoke-basic": {"with": {"bash": ["python3 render.py"], "skill_error": True}, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        record = self.stored()
        self.assertEqual(record["arms"]["with"][0]["tools_called"], ["Skill (error)", "Bash"])
        self.assertEqual(record["arms"]["without"][0]["tools_called"], ["Edit"])
        self.assertIn("    with run 1 called: Skill (error), Bash", res.stdout)
        self.assertNotIn("without run 1 called", res.stdout)  # a run that passed needs no explaining


class KitMcp(RunnerTest):
    """A skill that declares tools of the kit's MCP server: with the opt-in flag and without it."""

    TOOL = "mcp__metodo__demo_tool"
    EXPOSED = "mcp__plugin_demo-skill_metodo__demo_tool"
    BETTER = {"smoke-basic": {"with": {**GOOD_RUN, "mcp": [EXPOSED]}, "without": {}}}  # alone, this reads `works`

    def setUp(self):
        super().setUp()
        self.play(cases=self.BETTER)

    def declare(self, *deps, line=""):
        """Make demo-skill need `deps`: its BUILD.json, its allowed-tools line and one line of its text."""
        catalog = self.kit / "03-tools" / "mcp"
        catalog.mkdir(parents=True)
        (catalog / "__init__.py").write_text("")
        (catalog / "catalog.py").write_text('BY_NAME = {"demo_tool": None}\n')
        skill = self.kit / "02-skills" / "demo-skill"
        (skill / "BUILD.json").write_text(json.dumps({"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md"], "deps": list(deps)}}))
        tools = ", ".join(["Read", "Edit", *(dep for dep in deps if dep.startswith("mcp__"))])
        head, rest = (skill / "SKILL.md").read_text().split("\n---\n", 1)
        (skill / "SKILL.md").write_text(f"{head}\nallowed-tools: [{tools}]\n---\n{rest}{line}")

    def test_without_the_flag_the_plan_and_the_report_say_it_ran_without_its_tools_and_it_cannot_work(self):
        self.declare(self.TOOL, line=f"4. Check the result with `{self.TOOL}`.\n")
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke")
        self.assert_clean(plan, 0)
        said = "demo-skill declares 1 MCP tool(s) of the kit's server, which this run does not start: the skill runs without its tools"
        self.assertIn(said, plan.stdout)
        self.assertIn("--kit-mcp", plan.stdout)
        res = self.run_real()
        self.assert_clean(res, 0)
        call = self.calls()[0]
        self.assertNotIn(".mcp.json", call["files"])
        self.assertNotIn("--allow-real-servers", call["argv"])
        self.assertFalse([arg for arg in call["argv"] if "mcp__" in arg])
        self.assertIn(self.TOOL, call["skill_text"])  # the skill is run as it is packed
        for shown in (res, self.report()):
            self.assertIn("demo-skill: not measured", shown.stdout)
            self.assertIn("it ran without its MCP tools", shown.stdout)
            self.assertNotIn("demo-skill: works", shown.stdout)
            self.assertIn("score: with 1.00, without 0.00", shown.stdout)

    def test_the_flag_gives_the_skill_the_kit_server_and_its_tools_under_the_plugin_names(self):
        self.declare(self.TOOL, line=f"4. Check the result with `{self.TOOL}`.\n")
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--kit-mcp")
        self.assertIn("--kit-mcp starts this checkout's MCP server", plan.stdout)
        res = self.run_real("--kit-mcp")
        self.assert_clean(res, 0)
        call = self.calls()[0]
        self.assertIn(".mcp.json", call["files"])
        self.assertEqual(call["mcp"]["mcpServers"]["metodo"]["args"], [str(self.kit / "03-tools" / "mcp" / "server.py")])
        self.assertIn("--allow-real-servers", call["argv"])
        granted = call["argv"][call["argv"].index("--allow-tools") + 1:]
        self.assertIn(self.EXPOSED, granted)
        self.assertIn(self.EXPOSED, call["cases"]["smoke-basic"]["execution"]["allowed_tools"])
        self.assertEqual(call["skill_text"].count(self.EXPOSED), 2)
        self.assertNotIn(self.TOOL, call["skill_text"])
        for flag in native.REQUIRED_FLAGS:
            self.assertIn(flag, call["argv"])
        self.assertIn("demo-skill: works", res.stdout)
        self.assertIn("kit MCP server: started for 1 case(s); 1 call(s) to its tools", res.stdout)
        self.assertTrue(self.stored()["mcp"]["served"])

    def test_result_stored_without_the_server_is_not_reused_with_it(self):
        self.declare(self.TOOL)
        self.assert_clean(self.run_real(), 0)
        self.assert_clean(self.run_real("--kit-mcp"), 0)
        self.assertEqual(len(self.calls()), 3)  # one invocation without the server, then one per arm with it (S14)
        self.assert_clean(self.run_real("--kit-mcp"), 0)
        self.assertEqual(len(self.calls()), 3)

    def test_the_flag_starts_nothing_for_a_skill_that_declares_no_mcp_tool(self):  # previous behavior of a plain skill
        res = self.run_real("--kit-mcp")
        self.assert_clean(res, 0)
        call = self.calls()[0]
        self.assertNotIn(".mcp.json", call["files"])
        self.assertNotIn("--allow-real-servers", call["argv"])
        self.assertIn("demo-skill: works", res.stdout)
        self.assertNotIn("without its", res.stdout)

    def test_the_tools_root_a_skill_names_is_rendered_for_the_run_and_the_plan_says_so(self):
        self.declare("03-tools", line='5. Run `python3 "${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/x.py"`.\n')
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke")
        self.assertIn(f"its files name the kit's tools root, rendered to {self.kit / '03-tools'} for the run", plan.stdout)
        self.assert_clean(self.run_real(), 0)
        text = self.calls()[0]["skill_text"]
        self.assertIn(f"${{METODO_TOOLS:-{self.kit / '03-tools'}}}/lib/x.py", text)
        self.assertNotIn("__TOOLS_DEFAULT__", text)


class KitPlugin(RunnerTest):
    """`--kit-plugin`: the skill is evaluated from the kit plugin, whose server runs from the plugin's own files."""

    TOOL = "mcp__metodo__demo_tool"
    EXPOSED = "mcp__plugin_demo-kit_metodo__demo_tool"
    BETTER = {"smoke-basic": {"with": {**GOOD_RUN, "mcp": [EXPOSED]}, "without": {}}}
    FORM = "measured as: the kit plugin demo-kit 0.3.0, invoked as demo-kit:demo-skill"
    OWN = "measured as: its own package demo-skill 0.1.0, invoked as demo-skill:demo-skill"

    def setUp(self):
        super().setUp()
        self.play(cases=self.BETTER)
        server = self.kit / "03-tools" / "mcp"
        server.mkdir(parents=True)
        (server / "__init__.py").write_text("")
        (server / "catalog.py").write_text('BY_NAME = {"demo_tool": None}\n')
        (server / "server.py").write_text("print('a server that no test starts')\n")
        self.kit_build = self.kit / "02-skills" / "BUILD.json"
        self.kit_build.write_text(json.dumps({"schema_version": 1, "kit_plugin": {
            "name": "demo-kit", "version": "0.3.0", "description": "The demo kit as one plugin.",
            "marketplace": "demo-market", "owner": "Demo Owner"}}))
        skill = self.kit / "02-skills" / "demo-skill"
        (skill / "BUILD.json").write_text(json.dumps({"schema_version": 1,
                                                      "agent_skill": {"srcs": ["SKILL.md"], "deps": [self.TOOL]}}))
        head, rest = (skill / "SKILL.md").read_text().split("\n---\n", 1)
        (skill / "SKILL.md").write_text(f"{head}\nallowed-tools: [Read, Edit, {self.TOOL}]\n---\n{rest}"
                                        f"4. Check the result with `{self.TOOL}`.\n")

    def test_the_flag_evaluates_the_skill_from_the_kit_plugin_with_the_plugins_own_server(self):
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--kit-plugin")
        self.assert_clean(plan, 0)
        self.assertIn("demo-skill: --kit-plugin evaluates it from the kit plugin", plan.stdout)
        self.assertNotIn("which this run does not start", plan.stdout)
        res = self.run_real("--kit-plugin")
        self.assert_clean(res, 0)
        call = self.calls()[0]
        self.assertIn("skills/other-skill/SKILL.md", call["files"])  # the whole kit, not a package of one skill
        self.assertIn("tools/mcp/server.py", call["files"])
        self.assertEqual(call["mcp"]["mcpServers"]["metodo"]["args"], ["${CLAUDE_PLUGIN_ROOT}/tools/mcp/server.py"])
        self.assertNotIn(str(self.kit), json.dumps(call["mcp"]))  # the server of the plugin, not of this checkout
        self.assertIn("--allow-real-servers", call["argv"])
        self.assertIn(self.EXPOSED, call["argv"][call["argv"].index("--allow-tools") + 1:])
        self.assertIn(self.EXPOSED, call["cases"]["smoke-basic"]["execution"]["allowed_tools"])
        self.assertIn(self.EXPOSED, call["skill_text"])
        self.assertNotIn(self.TOOL, call["skill_text"])
        for flag in native.REQUIRED_FLAGS:
            self.assertIn(flag, call["argv"])
        self.assertIn("demo-skill: works", res.stdout)
        self.assertIn("kit MCP server: started for 1 case(s); 1 call(s) to its tools", res.stdout)
        self.assertTrue(self.stored()["mcp"]["served"])

    def test_a_stored_run_keeps_what_each_served_tool_answered(self):
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        record = self.stored()
        self.assertEqual(record["arms"]["with"][0]["mcp_answers"], [{"tool": self.EXPOSED, "error": False, "answer": "ok"}])
        self.assertEqual(record["arms"]["without"][0]["mcp_answers"], [])
        long = native.answer_text([{"type": "text", "text": "x" * 900}, {"type": "image"}])
        self.assertEqual(len(long), native.MAX_ANSWER_CHARS)  # an excerpt: a result may be a whole file
        self.assertEqual(native.answer_text("  two\n lines "), "two lines")

    def test_the_report_says_the_kit_plugin_was_measured(self):
        res = self.run_real("--kit-plugin")
        self.assert_clean(res, 0)
        shown = self.report("--json", str(self.tmp / "report.json"))
        for said in (res, shown):
            self.assertIn(self.FORM, said.stdout)
            self.assertNotIn("its own package", said.stdout)
        self.assertEqual(self.stored()["package"], {"form": "kit_plugin", "plugin": "demo-kit", "version": "0.3.0",
                                                    "invoke": "demo-kit:demo-skill"})
        self.assertTrue(self.stored()["settings"]["kit_plugin"])
        data = json.loads((self.tmp / "report.json").read_text())
        self.assertEqual(data["skills"][0]["measured_as"], [self.FORM[len("measured as: "):]])

    def test_without_the_flag_the_skill_package_is_measured_and_the_report_says_so(self):  # previous behavior
        res = self.run_real()
        self.assert_clean(res, 0)
        call = self.calls()[0]
        self.assertNotIn("skills/other-skill/SKILL.md", call["files"])
        self.assertNotIn(".mcp.json", call["files"])
        self.assertFalse([name for name in call["files"] if name.startswith("tools/")])
        self.assertIn(self.TOOL, call["skill_text"])
        self.assertIn(self.OWN, res.stdout)
        self.assertEqual(self.stored()["package"]["form"], "skill_package")
        self.assertFalse(self.stored()["settings"]["kit_plugin"])

    def test_under_the_kit_plugin_the_trigger_is_read_as_the_plugin_then_the_skill(self):
        other = {"smoke-basic": {"with": {**GOOD_RUN, "skill_as": "demo-skill:demo-skill"}, "without": {}}}
        self.play(cases=other)  # the name the skill has in a package of its own: not this plugin's skill
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        self.assertEqual(self.statuses()["with"], ["not_triggered"])
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "skill_as": "demo-kit:demo-skill"}, "without": {}}})
        self.assert_clean(self.run_real("--kit-plugin", "--no-cache"), 0)
        self.assertEqual(self.statuses()["with"], ["passed"])
        self.play(cases=other)  # previous behavior: for the skill's own package any prefix names it
        self.assert_clean(self.run_real("--no-cache"), 0)
        self.assertEqual(self.statuses()["with"], ["passed"])

    def test_a_result_of_one_form_is_not_reused_for_the_other(self):
        self.assert_clean(self.run_real(), 0)
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        self.assertEqual(len(self.calls()), 3)  # one invocation for the package, then one per arm for the kit plugin (S14)
        again = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--kit-plugin")
        self.assertIn("1 cached", again.stdout)
        back = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke")
        self.assertIn("the stored result used other settings: the kit plugin True, now False", back.stdout)

    def test_a_result_stored_before_the_flag_existed_is_still_reused_without_it(self):  # previous behavior of the cache
        self.assert_clean(self.run_real(), 0)
        path = sorted((self.out / "store" / SMOKE).glob("*.json"))[0]
        record = json.loads(path.read_text())
        del record["settings"]["kit_plugin"], record["package"]
        path.write_text(json.dumps(record))
        res = self.run_real()
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("  measured as: its own package\n", res.stdout)

    def test_a_change_in_the_server_or_in_another_packed_skill_runs_the_case_again(self):  # R3-kit-plugin-cache-ignores-server-and-other-skills
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        again = self.run_real("--kit-plugin")
        self.assert_clean(again, 0)
        self.assertEqual(len(self.calls()), 2)  # previous behavior: nothing changed, so it is served from the store
        self.assertIn("demo-skill/smoke-basic [smoke]: cached", again.stdout)
        (self.kit / "03-tools" / "mcp" / "server.py").write_text("print('another server that no test starts')\n")
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--kit-plugin")
        self.assert_clean(plan, 0)
        self.assertIn("demo-skill/smoke-basic [smoke]: to run", plan.stdout)
        self.assertIn("the stored result used other settings: another build of the kit plugin", plan.stdout)
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        self.assertEqual(len(self.calls()), 4)  # under the kit plugin every measurement is one invocation per arm (S14)
        with open(self.kit / "02-skills" / "other-skill" / "SKILL.md", "a") as handle:
            handle.write("\nOne more line in a skill that is not the one measured.\n")
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        self.assertEqual(len(self.calls()), 6)
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        self.assertEqual(len(self.calls()), 6)  # and the new result is reused while the plugin stays as it is
        shown = self.report()  # previous behavior: the report shows what is stored and packs nothing
        self.assert_clean(shown, 0)
        self.assertIn(self.FORM, shown.stdout)

    def test_a_change_in_the_server_does_not_run_the_skills_own_package_again(self):  # previous behavior of the cache
        self.assert_clean(self.run_real(), 0)
        (self.kit / "03-tools" / "mcp" / "server.py").write_text("print('another server that no test starts')\n")
        res = self.run_real()
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("demo-skill/smoke-basic [smoke]: cached", res.stdout)

    def test_the_kit_plugin_and_the_checkout_server_together_are_a_usage_error(self):
        res = self.run_real("--kit-plugin", "--kit-mcp")
        self.assert_clean(res, 2)
        self.assertEqual(len(res.stderr.splitlines()), 1, res.stderr)
        self.assertIn("--kit-plugin or --kit-mcp, not both", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_kit_plugin_that_cannot_be_packed_or_lacks_the_skill_is_not_measured(self):
        (self.kit / "02-skills" / "demo-skill" / "BUILD.json").unlink()
        res = self.run_real("--kit-plugin")
        self.assert_clean(res, 1)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertIn("the kit plugin does not hold the skill demo-skill", res.stderr)
        self.kit_build.unlink()
        res = self.run_real("--kit-plugin")
        self.assert_clean(res, 1)
        self.assertIn("the kit plugin cannot be packed", res.stderr)
        self.assertEqual(self.calls(), [])


class ArmWithoutTheSkill(RunnerTest):
    """S14: when a run carries the kit's MCP server, the arm without the skill is the same plugin less the skill's folder."""

    TOOL = "mcp__metodo__demo_tool"
    OWN = "mcp__plugin_demo-skill_metodo__demo_tool"  # as the skill's own package exposes it (--kit-mcp)
    KIT = "mcp__plugin_demo-kit_metodo__demo_tool"    # as the kit plugin exposes it (--kit-plugin)

    def setUp(self):
        super().setUp()
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "mcp": [self.OWN]}, "without": {}}})
        server = self.kit / "03-tools" / "mcp"
        server.mkdir(parents=True)
        (server / "__init__.py").write_text("")
        (server / "catalog.py").write_text('BY_NAME = {"demo_tool": None}\n')
        (server / "server.py").write_text("print('a server that no test starts')\n")
        (self.kit / "02-skills" / "BUILD.json").write_text(json.dumps({"schema_version": 1, "kit_plugin": {
            "name": "demo-kit", "version": "0.3.0", "description": "The demo kit as one plugin.",
            "marketplace": "demo-market", "owner": "Demo Owner"}}))
        skill = self.kit / "02-skills" / "demo-skill"
        (skill / "BUILD.json").write_text(json.dumps({"schema_version": 1,
                                                      "agent_skill": {"srcs": ["SKILL.md"], "deps": [self.TOOL]}}))
        head, rest = (skill / "SKILL.md").read_text().split("\n---\n", 1)
        (skill / "SKILL.md").write_text(f"{head}\nallowed-tools: [Read, Edit, {self.TOOL}]\n---\n{rest}"
                                        f"4. Check the result with `{self.TOOL}`.\n")

    @staticmethod
    def after(argv, flag):
        return argv[argv.index(flag) + 1]

    def assert_same_plugin_less_the_skill(self, used, bare, exposed):
        """Read from what the stub recorded of each invocation: its command line and the folder it was given."""
        gone = [name for name in used["files"] if name.startswith("skills/demo-skill/")]
        self.assertIn("skills/demo-skill/SKILL.md", gone)
        self.assertEqual(bare["files"], [name for name in used["files"] if name not in gone])
        self.assertEqual(bare["sha256"], {name: digest for name, digest in used["sha256"].items() if name not in gone})
        self.assertEqual((bare["plugin"], bare["cases"]), (used["plugin"], used["cases"]))
        self.assertIsNotNone(used["mcp"])
        self.assertEqual(bare["mcp"], used["mcp"])
        self.assertNotEqual(bare["argv"][2], used["argv"][2])  # a folder of its own
        self.assertIn(exposed, bare["cases"]["smoke-basic"]["execution"]["allowed_tools"])
        for call in (used, bare):
            self.assertEqual(self.after(call["argv"], "--ablation"), "none")
            self.assertIn("--allow-real-servers", call["argv"])
            self.assertIn(exposed, call["argv"][call["argv"].index("--allow-tools") + 1:])
        self.assertEqual(self.statuses(), {"with": ["passed"], "without": ["validator_failed"]})

    def test_with_the_checkout_server_the_arm_without_the_skill_is_the_same_plugin_less_the_skills_folder(self):
        res = self.run_real("--kit-mcp")
        self.assert_clean(res, 0)
        used, bare = self.calls()
        self.assert_same_plugin_less_the_skill(used, bare, self.OWN)
        self.assertEqual((used["plugin"], bare["skill_text"]), ("demo-skill", ""))
        self.assertIn("demo-skill: works", res.stdout)

    def test_with_the_kit_plugin_only_the_measured_skill_leaves_and_the_other_skills_stay(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "mcp": [self.KIT]}, "without": {}}})
        self.assert_clean(self.run_real("--kit-plugin"), 0)
        used, bare = self.calls()
        self.assert_same_plugin_less_the_skill(used, bare, self.KIT)
        self.assertEqual(used["plugin"], "demo-kit")
        for kept in ("skills/other-skill/SKILL.md", "tools/mcp/server.py", ".mcp.json"):
            self.assertIn(kept, bare["files"])

    def test_every_command_line_of_both_arms_carries_the_protecting_flags_and_the_ceilings_fit_the_owners(self):
        for flag, ceiling in (("--kit-mcp", "0.25"), ("--kit-mcp", "0.3333333"), ("--kit-plugin", "7")):
            self.log.unlink(missing_ok=True)
            self.assert_clean(self.run_real(flag, "--no-cache", "--max-cost-usd", ceiling), 0)
            calls = self.calls()
            self.assertEqual(len(calls), 2, (flag, ceiling))
            for call in calls:
                for required in native.REQUIRED_FLAGS:
                    self.assertIn(required, call["argv"], (flag, ceiling))
                self.assertNotIn("--publish-report", call["argv"])
                self.assertGreater(float(self.after(call["argv"], "--max-cost-usd")), 0)
                for path in ("--output-dir", "--json"):
                    self.assertTrue(self.after(call["argv"], path).startswith(str(self.out) + os.sep), call["argv"])
            self.assertNotEqual(self.after(calls[0]["argv"], "--output-dir"), self.after(calls[1]["argv"], "--output-dir"))
            self.assertLessEqual(sum(float(self.after(call["argv"], "--max-cost-usd")) for call in calls), float(ceiling),
                                 (flag, ceiling))

    def test_without_a_server_the_command_line_is_the_one_built_before(self):  # previous behavior, byte for byte
        self.assert_clean(self.run_real("--max-cost-usd", "0.25"), 0)
        (call,) = self.calls()
        out = pathlib.Path(self.after(call["argv"], "--output-dir"))
        self.assertEqual(out.parent, self.out / "native" / "demo-skill")
        self.assertEqual(call["argv"], [
            "plugin", "eval", str(self.out / "work" / "demo-skill" / "plugin"), "--no-publish", "--trust-plugin",
            "--keep-temp", "--ablation", "with-without", "--threshold", "0", "--max-cost-usd", "0.25",
            "--output-dir", str(out), "--json", str(out / "result.json"), "--scaffold", "--tag", "smoke",
            "--allow-tools", "Edit"])
        self.assertEqual(json.loads((out / "command.json").read_text())[1:], call["argv"])
        self.assertNotIn(".mcp.json", call["files"])

    def test_the_plan_says_how_many_native_invocations_will_run_and_starts_nothing(self):
        target = self.tmp / "plan.json"
        plan = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--kit-mcp", "--json", str(target))
        self.assert_clean(plan, 0)
        for said in ("2 native run(s) in 2 native invocation(s); ceiling USD 0.50",
                     "the arm without the skill runs on the same plugin with only skills/demo-skill/ removed",
                     "--ablation none", "under USD 0.25 and at most USD 0.25 of the ceiling",
                     "plan only: nothing was run and nothing was spent"):
            self.assertIn(said, plan.stdout)
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertEqual((skill["native_invocations"], skill["without_arm"], skill["ceilings_usd"], skill["ceiling_usd"]),
                         (2, "skill_removed", [0.25, 0.25], 0.5))
        plain = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--json", str(target))
        self.assert_clean(plain, 0)
        self.assertNotIn("--ablation none", plain.stdout)
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertEqual((skill["native_invocations"], skill["without_arm"], skill["ceilings_usd"]),
                         (1, "native_ablation", [0.5]))
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.out / "store").exists())

    def test_without_a_server_the_plan_is_the_one_printed_before_and_names_no_invocation(self):  # T10 B3, previous output
        target = self.tmp / "plan.json"
        plain = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--json", str(target))
        self.assert_clean(plain, 0)
        self.assertEqual(plain.stdout.splitlines()[0],
                         "demo-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 2 native run(s); ceiling USD 0.50")
        self.assertNotIn("invocation", plain.stdout)
        data = json.loads(target.read_text())
        (skill,) = data["skills"]
        before = {"skill": "demo-skill", "has_skill": True, "arms": ["with", "without"], "to_run": 1, "cached": 0,
                  "native_runs": 2, "ceiling_usd": 0.5, "kit_mcp": False, "kit_plugin": False, "mcp_tools": [self.TOOL]}
        self.assertEqual({key: skill[key] for key in before}, before)  # every key the plan had before S14, as it was
        self.assertEqual((data["mode"], data["max_cost_usd"], data["ceiling_usd"]), ("plan", 0.5, 0.5))
        self.assertEqual(self.calls(), [])

    def test_a_ceiling_that_is_not_a_finite_number_is_never_a_traceback(self):  # T10 A1
        plain = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--max-cost-usd", "inf")
        self.assert_clean(plain, 0)  # no server: the plan the older runner printed
        self.assertEqual(plain.stdout.splitlines()[0],
                         "demo-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 2 native run(s); ceiling USD inf")
        for flags in (["--kit-mcp"], ["--kit-plugin"], ["--kit-mcp", "--real"]):
            res = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--max-cost-usd", "inf", *flags)
            self.assertNotIn("Traceback", res.stdout + res.stderr, flags)
            self.assertEqual((res.returncode, res.stdout), (2, ""), (flags, res.stderr))
            self.assertEqual(len(res.stderr.splitlines()), 1, res.stderr)
            self.assertTrue(res.stderr.startswith("skill-eval: --max-cost-usd inf"), res.stderr)
            self.assertIn("finite", res.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.out / "store").exists())

    def test_a_failure_of_either_invocation_names_and_reports_all_that_was_spent_so_far(self):  # T10 B2
        target = self.tmp / "report.json"
        runs = {"smoke-basic": {"with": {**GOOD_RUN, "mcp": [self.OWN]}, "without": {}}}  # USD 0.011 each

        def failed(started, *flags, **scenario):
            """The failure line, the report's spend as data and the report as printed."""
            self.log.unlink(missing_ok=True)
            self.play(cases=runs, **scenario)
            res = self.run_real("--kit-mcp", "--runs", "1", "--json", str(target), *flags)
            self.assert_clean(res, 1)
            self.assertEqual(len(self.calls()), started)
            (line,) = [line for line in res.stderr.splitlines() if line.startswith("skill-eval: demo-skill: ")]
            self.assertIn("demo-skill: not measured", res.stdout)
            self.assertFalse((self.out / "store").exists(), "a failed run must not be stored as a result")
            self.assertEqual(sorted(self.kept.glob("e-*")), [])  # nothing half-made is left
            return line, json.loads(target.read_text())["skills"][0]["summary"], res.stdout

        line, summary, printed = failed(2, exit_bare=1, stderr="the suite failed to load")  # the second fails alone
        self.assertIn("the arm without the skill: the native tool exited 1", line)
        self.assertIn("USD 0.0220 spent by the two invocations, USD 0.0110 of it by the arm with the skill", line)
        self.assertAlmostEqual(summary["spend_usd"], 0.022)
        self.assertAlmostEqual(summary["spend_unstored_usd"], 0.022)
        self.assertIn("  spend that left no stored result: USD 0.0220", printed)

        line, summary, printed = failed(1, exit=1, stderr="the suite failed to load")  # the first fails: no second
        self.assertIn("the arm with the skill: the native tool exited 1", line)
        self.assertIn("USD 0.0110 spent", line)
        self.assertAlmostEqual(summary["spend_usd"], 0.011)
        self.assertIn("  spend that left no stored result: USD 0.0110", printed)

        runs["smoke-basic"]["with"]["cost"] = 0.30  # the first leaves nothing of the ceiling: the second is not started
        line, summary, printed = failed(1, "--max-cost-usd", "0.25")
        self.assertIn("the arm with the skill spent USD 0.3010 of the ceiling of USD 0.25", line)
        self.assertAlmostEqual(summary["spend_usd"], 0.301)
        self.assertIn("  spend that left no stored result: USD 0.3010", printed)

    def test_a_failure_with_no_server_is_reported_as_before(self):  # previous output of a run with one invocation
        target = self.tmp / "report.json"
        self.play(exit=1, stderr="the suite failed to load", cases=BOTH_GOOD)
        res = self.run_real("--json", str(target))
        self.assert_clean(res, 1)
        self.assertIn("skill-eval: demo-skill: the native tool exited 1", res.stderr)
        self.assertIn("USD 0.0220 spent: the suite failed to load; nothing was stored\n", res.stderr)
        self.assertNotIn("spend that left no stored result", res.stdout)
        summary = json.loads(target.read_text())["skills"][0]["summary"]
        self.assertEqual((summary["spend_usd"], "spend_unstored_usd" in summary), (0.0, False))

    def test_the_report_and_the_stored_result_say_how_the_arm_without_the_skill_was_built(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "mcp": [self.OWN]}, "without": {"mcp": [self.OWN]}}})
        res = self.run_real("--kit-mcp")
        self.assert_clean(res, 0)
        shown = self.report("--json", str(self.tmp / "report.json"))
        said = ("  arm without the skill: the same plugin with only skills/demo-skill/ removed, in a second invocation of "
                "the tool: its MCP server and tools stay; 1 call(s) to its tools in the runs without the skill\n")
        for output in (res, shown):
            self.assertIn(said, output.stdout)
        record = self.stored()
        self.assertEqual(record["without_arm"], {"how": "skill_removed", "invocations": 2, "ceilings_usd": [0.25, 0.25]})
        self.assertEqual(record["arms"]["without"][0]["mcp_calls"], 1)  # the tool was there to be called
        data = json.loads((self.tmp / "report.json").read_text())
        self.assertEqual(data["skills"][0]["without_arm"], [said.strip()[len("arm without the skill: "):]])
        res = self.run_real("--no-cache")  # no server: the tool's own ablation, as before
        self.assert_clean(res, 0)
        self.assertIn("  arm without the skill: the tool's own ablation, which removes the whole plugin\n", res.stdout)
        self.assertEqual(self.stored()["without_arm"], {"how": "native_ablation", "invocations": 1, "ceilings_usd": [0.5]})

    def test_when_the_first_arm_leaves_nothing_of_the_ceiling_the_second_is_not_started_and_nothing_is_a_verdict(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "mcp": [self.OWN], "cost": 0.30}, "without": {}}})
        res = self.run_real("--kit-mcp", "--max-cost-usd", "0.25")
        self.assert_clean(res, 1)
        self.assertEqual(len(self.calls()), 1, "the arm without the skill must not be started")
        self.assertIn("nothing is left for the arm without it", res.stderr)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertNotIn("demo-skill: works", res.stdout)
        self.assertFalse((self.out / "store").exists())
        self.assertEqual(sorted(self.kept.glob("e-*")), [])  # the first arm's kept folders are not left behind

    def test_a_result_stored_by_the_older_runner_under_a_server_is_measured_again(self):
        self.assert_clean(self.run_real("--kit-mcp"), 0)
        self.assertEqual(len(self.calls()), 2)
        (path,) = sorted((self.out / "store" / SMOKE).glob("*.json"))
        os.replace(path, path.with_name(f"{self.stored()['hash']}.v4.json"))  # the name the runner before S14 gave it
        res = self.run_real("--kit-mcp")
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 4, "a result of the older runner was reused")
        self.assertNotIn("demo-skill/smoke-basic [smoke]: cached", res.stdout)


class Cascade(RunnerTest):
    def test_run_that_did_not_trigger_is_not_judged_and_its_judge_spend_is_shown_apart(self):
        self.play(cases={"smoke-basic": {"with": {"skill": False, "judge": False, "judge_cost": 0.002},
                                         "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        run = self.stored()["arms"]["with"][0]
        self.assertEqual((run["status"], run["judge_counted"], run["validators"]), ("not_triggered", False, []))
        self.assertIn("with: not triggered, quality not judged", res.stdout)
        self.assertIn("demo-skill: review", res.stdout)
        self.assertIn("it does not trigger when it should (look at the description)", res.stdout)
        self.assertNotIn("the judge rejects it", res.stdout)
        self.assertNotIn("fails a validator", res.stdout)
        self.assertIn("on runs not triggered USD 0.0020", res.stdout)

    def test_skill_call_that_came_back_as_an_error_is_not_a_trigger(self):
        # Measured on 2.1.330: the Skill tool can be called for a skill that is not loaded, and the
        # native grader counts the call. The kit asks for a call that worked.
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "skill_error": True}, "without": GOOD_RUN}})
        self.assert_clean(self.run_real(), 0)
        run = self.stored()["arms"]["with"][0]
        self.assertEqual((run["native_graders"]["trigger-01"], run["status"]), (True, "not_triggered"))

    def test_validators_run_on_the_files_the_run_left_with_the_answer_key_at_hand(self):
        self.play(cases={"smoke-basic": {"with": GOOD_RUN, "without": {}}})
        res = self.run_real()
        self.assert_clean(res, 0)
        record = self.stored()
        self.assertEqual(self.statuses(), {"with": ["passed"], "without": ["validator_failed"]})
        self.assertEqual(record["arms"]["with"][0]["validators"],
                         [{"script": "validators/check_output.py", "passed": True, "detail": ""}])
        self.assertIn("does not return 'Hello, world.'", record["arms"]["without"][0]["validators"][0]["detail"])
        self.assertIn("demo-skill: works", res.stdout)

    def test_validator_failure_outranks_the_judge(self):
        self.play(cases={"smoke-basic": {"with": {"judge": True}, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        run = self.stored()["arms"]["with"][0]
        self.assertEqual((run["status"], run["judge_counted"]), ("validator_failed", False))
        self.assertIn("its output fails a validator", res.stdout)
        self.assertNotIn("the judge rejects it", res.stdout)

    def test_judge_counts_once_the_trigger_and_the_validators_passed(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "judge": False}, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        run = self.stored()["arms"]["with"][0]
        self.assertEqual((run["status"], run["judge_counted"]), ("judge_rejected", True))
        self.assertEqual(run["judge"], [{"name": "expect-01", "passed": False}])
        self.assertIn("demo-skill: review", res.stdout)
        self.assertIn("the judge rejects it", res.stdout)

    def test_judge_that_did_not_run_is_never_a_pass(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "skipped_paid": True}, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        self.assertEqual(self.statuses()["with"], ["unreadable"])
        self.assertIn("demo-skill: not measured", res.stdout)

    def test_validator_gets_the_workspace_and_the_answer_key_and_a_timeout(self):
        workspace = self.tmp / "ws"
        workspace.mkdir()
        (self.case / "validators" / "args.py").write_text(
            "import os, sys\n"
            "ok = os.path.samefile(os.getcwd(), sys.argv[1]) and os.path.isfile(os.path.join(sys.argv[2], 'expected.txt'))\n"
            "sys.exit(0 if ok and os.environ['SKILL_EVAL_TESTDATA'] == sys.argv[2] else 3)\n")
        (self.case / "validators" / "slow.py").write_text("import time\ntime.sleep(30)\n")
        self.edit_case(validators=["validators/args.py", "validators/slow.py"])
        results = runner.run_validators(skill_eval.load_case(self.case), workspace, timeout=0.5)
        self.assertEqual(results[0], {"script": "validators/args.py", "passed": True, "detail": ""})
        self.assertEqual((results[1]["passed"], results[1]["detail"]), (False, "timed out after 0.5s"))
        self.assertGreater(runner.VALIDATOR_TIMEOUT_SECONDS, 0)


class AntiCheat(RunnerTest):
    def test_run_that_touched_a_forbidden_path_is_cheated_whatever_the_native_graders_said(self):
        cheat = {**GOOD_RUN, "touch": ["secrets/key.txt"], "native_forbidden": True}
        self.play(cases={"smoke-basic": {"with": cheat, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        run = self.stored()["arms"]["with"][0]
        self.assertEqual(run["native_graders"]["forbidden-01"], True)  # the native grader was told to pass
        self.assertEqual((run["status"], run["judge_counted"], run["validators"]), ("cheated", False, []))
        self.assertIn("secrets/**", run["cheat"][0])
        self.assertIn("with: cheated", res.stdout)
        self.assertIn("cheated 1", res.stdout)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertIn("every run with the skill touched a forbidden path", res.stdout)

    def test_cheated_run_scores_nothing_and_is_counted_apart_from_the_others(self):
        cheat = {**GOOD_RUN, "bash": ["cat testdata/expected.txt"]}
        self.play(cases={"smoke-basic": {"with": [cheat, GOOD_RUN], "without": [{}, {}]}})
        res = self.run_real("--runs", "2")
        self.assert_clean(res, 0)
        self.assertEqual(self.statuses()["with"], ["cheated", "passed"])
        self.assertIn("score: with 1.00, without 0.00, delta +1.00", res.stdout)
        self.assertIn("cheated 1", res.stdout)

    def test_forbidden_globs_match_the_paths_a_tool_call_names(self):
        def hit(glob, tool, **tool_input):
            return bool(native.touched([glob], [{"name": tool, "input": tool_input}]))
        self.assertTrue(hit("secrets/**", "Read", file_path="/private/tmp/e-abc123/home/cwd/secrets/key.txt"))
        self.assertTrue(hit("secrets/**", "Bash", command="cat secrets/key.txt | head"))
        self.assertTrue(hit("secrets/**", "Glob", pattern="secrets/*", path="/w"))
        self.assertTrue(hit("secrets/**", "Bash", command="ls secrets"))
        self.assertTrue(hit("*.key", "Read", file_path="/w/deep/server.key"))
        self.assertTrue(hit("**/answers.json", "Read", file_path="/w/a/b/answers.json"))
        self.assertFalse(hit("secrets/**", "Read", file_path="/w/mysecrets/key.txt"))
        self.assertFalse(hit("secrets/**", "Read", file_path="/w/secrets.md"))
        self.assertFalse(hit("*.key", "Read", file_path="/w/server.keystore"))
        self.assertFalse(hit("secrets/**", "Write", file_path="/w/notes.md", content="see secrets/key.txt"))

    SECRET = "passphrase: marigold-tango-7-delta"

    def stage_secret(self, more=""):
        """Stage `secrets/key.txt`, a file under the case's forbidden glob, beside the other setup files."""
        folder = self.case / "setup" / "secrets"
        folder.mkdir()
        (folder / "key.txt").write_text(f"# key\n\n{self.SECRET}\n}}\n{more}")
        raw = json.loads((self.case / "case.json").read_text())
        raw["setup"]["files"].append({"from": "setup/secrets", "to": "secrets"})
        (self.case / "case.json").write_text(json.dumps(raw))

    def test_run_whose_broad_search_returned_a_forbidden_file_is_cheated(self):  # B2
        self.stage_secret()
        searches = (
            ("a recursive grep", "Bash", {"command": "grep -rn pass ."}, f"./notes.txt:1:a note\n./secrets/key.txt:3:{self.SECRET}"),
            ("a pattern search with no path", "Grep", {"pattern": "passphrase", "output_mode": "content"},
             f"secrets/key.txt:3:{self.SECRET}"),
            ("a cat through a glob", "Bash", {"command": "cat */key.txt"}, f"# key\n\n{self.SECRET}\n}}"),
        )
        for label, tool, tool_input, result in searches:
            with self.subTest(label):
                self.assertEqual(native.touched(["secrets/**"], [{"name": tool, "input": tool_input}]), [],
                                 "the call names no forbidden path, so only its result can tell")
                call = {"name": tool, "input": tool_input, "result": result}
                self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "calls": [call]}, "without": GOOD_RUN}})
                res = self.run_real("--no-cache")
                self.assert_clean(res, 0)
                self.assertEqual(self.statuses(), {"with": ["cheated"], "without": ["passed"]})
                run = self.stored()["arms"]["with"][0]
                self.assertEqual(run["cheat"], [f"{tool} returned line 3 of secrets/key.txt, which is under 'secrets/**'"])
                self.assertEqual((run["judge_counted"], run["validators"]), (False, []))
                self.assertIn("demo-skill: not measured", res.stdout)
                self.assertNotIn("marigold", json.dumps(self.stored()) + res.stdout)  # the hit never quotes the file
                shutil.rmtree(self.out / "store")

    def test_run_whose_search_returned_nothing_of_a_forbidden_file_is_not_cheated(self):  # B2, the miss
        self.stage_secret()
        # The result holds the blank line, the bracket and the short comment of the forbidden file: none tells.
        call = {"name": "Bash", "input": {"command": "grep -rn greeting ."},
                "result": "./src/app.py:1:def greeting():\n\n}\n# key\n"}
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "calls": [call]}, "without": GOOD_RUN}})
        self.assert_clean(self.run_real(), 0)
        self.assertEqual(self.statuses(), {"with": ["passed"], "without": ["passed"]})

    def test_only_a_telling_line_of_a_forbidden_staged_file_counts(self):  # B2, the rule
        (self.case / "setup" / "notes.txt").write_text("a line the notes file also holds\n")
        self.stage_secret(more="----------------\nreturn None\n  a line the notes file also holds\n"
                          + "0123456789abcdef" * 20 + " tail\n")
        lines = native.telling_lines(skill_eval.load_case(self.case))
        self.assertEqual(lines, [(self.SECRET, "line 3 of secrets/key.txt, which is under 'secrets/**'"),
                                 (("0123456789abcdef" * 20)[:native.TELLING_MAX_CHARS],
                                  "line 8 of secrets/key.txt, which is under 'secrets/**'")])

        def hit(result):
            return native.returned(lines, [{"name": "Bash", "input": {"command": "ls"}, "result": result}])
        self.assertEqual(hit(f"1\t{self.SECRET}"), ["Bash returned line 3 of secrets/key.txt, which is under 'secrets/**'"])
        self.assertEqual(hit("0123456789abcdef" * 14 + " ... [truncated]"), ["Bash returned line 8 of secrets/key.txt, which is under 'secrets/**'"])
        self.assertEqual(hit("----------------\nreturn None\na line the notes file also holds\n\n}\n# key"), [])
        self.assertEqual(native.returned(lines, [{"name": "Read", "input": {}}]), [])  # a call with no result kept

    def test_only_the_kept_folders_the_result_names_are_opened_and_removed(self):
        precious = self.tmp / "precious"
        (precious / "out").mkdir(parents=True)
        (precious / "out" / "trace.jsonl").write_text("{}\n")
        self.play(stray=True, cases={"smoke-basic": {
            "with": {**GOOD_RUN, "trace_path": str(precious / "out" / "trace.jsonl")}, "without": GOOD_RUN}})
        res = self.run_real()
        self.assert_clean(res, 0)
        self.assertTrue((precious / "out" / "trace.jsonl").is_file(), "a folder not shaped like a kept one was removed")
        self.assertEqual(self.statuses(), {"with": ["unreadable"], "without": ["passed"]})
        # e-000001 was never named by the result (its run named `precious`), e-stray0 by no run at all.
        self.assertEqual(sorted(p.name for p in self.kept.iterdir()), ["e-000001", "e-stray0"])
        self.assertIn("demo-skill: not measured", res.stdout)

    def test_trace_that_is_missing_or_not_json_is_never_a_pass(self):
        for kind in ("missing", "garbage"):
            self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "trace": kind}, "without": GOOD_RUN}})
            res = self.run_real("--no-cache")
            self.assert_clean(res, 0)
            self.assertEqual(self.statuses()["with"], ["unreadable"], kind)
            self.assertIn("demo-skill: not measured", res.stdout)
            self.assertEqual(list(self.kept.iterdir()), [])
            shutil.rmtree(self.out / "store")


def record(with_runs, without_runs, expected=True):
    """A stored result with one run per status name given."""
    def run(status):
        return {"status": status, "cost_usd": 0.01, "judge_cost_usd": 0.001, "judge_counted": status in ("passed", "judge_rejected")}
    return {"case": "demo-skill/x", "tier": "smoke", "expected_skills": ["demo-skill"] if expected else [],
            "arms": {"with": [run(s) for s in with_runs], "without": [run(s) for s in without_runs]}}


class Verdict(unittest.TestCase):
    def verdict(self, *records, selected=None):
        return runner.verdict(runner.summarize(list(records)), selected if selected is not None else len(records))

    def test_thresholds_live_in_one_named_table(self):
        self.assertEqual(sorted(runner.THRESHOLDS), ["delta_min", "judge_pass_min", "runs_per_arm_min",
                                                     "trigger_rate_min", "validator_pass_min"])
        self.assertEqual(runner.THRESHOLDS["runs_per_arm_min"], 3)

    def test_works_when_it_triggers_and_the_result_is_better_than_without_it(self):
        got = self.verdict(record(["passed"] * 3, ["judge_rejected"] * 3))
        self.assertEqual((got["verdict"], got["signal"]), ("works", False))
        self.assertEqual(got["reasons"], ["it triggers and the result is better than without it"])

    def test_review_when_it_does_not_trigger(self):
        got = self.verdict(record(["not_triggered"] * 3, ["passed"] * 3))
        self.assertEqual((got["verdict"], got["reasons"]),
                         ("review", ["it does not trigger when it should (look at the description)"]))

    def test_review_when_it_triggers_and_changes_nothing(self):
        got = self.verdict(record(["passed"] * 3, ["passed"] * 3))
        self.assertEqual((got["verdict"], got["reasons"]),
                         ("review", ["it triggers and changes nothing (dead weight: cut or shrink)"]))

    def test_review_when_it_triggers_and_the_result_is_worse_than_without_it(self):
        got = self.verdict(record(["passed"] * 5 + ["judge_rejected"], ["passed"] * 6))
        self.assertEqual((got["verdict"], got["reasons"]),
                         ("review", ["it triggers and the result is worse than without it"]))

    def test_review_when_its_output_fails_a_validator(self):
        got = self.verdict(record(["validator_failed"] * 3, ["passed"] * 3))
        self.assertEqual((got["verdict"], got["reasons"][0]), ("review", "its output fails a validator"))

    def test_review_when_the_judge_rejects_it(self):
        got = self.verdict(record(["judge_rejected"] * 3, ["passed"] * 3))
        self.assertEqual((got["verdict"], got["reasons"][0]), ("review", "the judge rejects it"))

    def test_not_measured_without_a_result_or_a_run_that_could_be_scored(self):
        self.assertEqual(self.verdict(selected=2)["verdict"], "not measured")
        self.assertIn("no stored result", self.verdict(selected=2)["reasons"][0])
        got = self.verdict(record(["unreadable", "errored"], ["passed", "passed"]))
        self.assertEqual(got["verdict"], "not measured")
        got = self.verdict(record(["passed"] * 3, ["cheated"] * 3))
        self.assertEqual(got["verdict"], "not measured")
        self.assertIn("nothing to compare", got["reasons"][0])

    def test_verdict_from_fewer_than_three_runs_per_arm_is_a_signal(self):
        self.assertTrue(self.verdict(record(["passed"] * 2, ["judge_rejected"] * 2))["signal"])
        self.assertTrue(self.verdict(record(["passed"] * 3, ["judge_rejected"] * 3),
                                     record(["passed"], ["judge_rejected"]))["signal"])
        self.assertFalse(self.verdict(record(["passed"] * 3, ["judge_rejected"] * 3))["signal"])

    def test_signal_is_decided_by_the_runs_scored_in_each_arm_not_by_the_runs_made(self):  # B3
        summary = runner.summarize([record(["errored", "unreadable", "passed"], ["judge_rejected"] * 3)])
        self.assertEqual((summary["runs_per_arm"], summary["scored_per_arm"]), (3, 1))
        self.assertEqual((runner.verdict(summary, 1)["verdict"], runner.verdict(summary, 1)["signal"]), ("works", True))
        self.assertTrue(self.verdict(record(["passed"] * 3, ["cheated", "judge_rejected", "judge_rejected"]))["signal"])
        self.assertFalse(self.verdict(record(["passed"] * 3 + ["errored"], ["judge_rejected"] * 4))["signal"])

    def test_case_with_no_expected_skill_is_not_said_to_trigger(self):
        got = self.verdict(record(["passed"] * 3, ["judge_rejected"] * 3, expected=False))
        self.assertEqual(got["reasons"], ["the result is better than without it"])


class Report(RunnerTest):
    def test_report_gives_the_verdict_and_what_stands_beside_it_and_spends_nothing(self):
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "cost": 0.02, "judge_cost": 0.003},
                                         "without": {"cost": 0.01, "judge_cost": 0.002}}})
        self.assert_clean(self.run_real(), 0)
        res = self.report("--tier", "smoke", "--json", str(self.tmp / "report.json"))
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 1, "report must not start the tool")
        tokens = runner.skill_tokens(self.kit / "02-skills" / "demo-skill")
        for said in ("demo-skill: works [signal: 1 run(s) per arm, a verdict needs 3]",
                     "it triggers and the result is better than without it",
                     "cases: 1 measured of 1 selected", "arms: with, without", "runs per arm: 1",
                     "score: with 1.00, without 0.00, delta +1.00", "triggered 1 of 1",
                     f"size: {tokens[0]} tokens", "docs_lint", "spend: USD 0.0350", "judge USD 0.0050",
                     "demo-skill/smoke-basic [smoke]: with: passed | without: failed a validator",
                     "done by the kit around the native tool"):
            self.assertIn(said, res.stdout)
        data = json.loads((self.tmp / "report.json").read_text())
        self.assertEqual((data["skills"][0]["skill"], data["skills"][0]["verdict"], data["skills"][0]["signal"]),
                         ("demo-skill", "works", True))
        self.assertEqual(data["thresholds"], runner.THRESHOLDS)

    def test_signal_label_says_how_many_of_the_runs_made_were_scored(self):  # B3
        failed = {**GOOD_RUN, "error": "API error"}
        self.play(cases={"smoke-basic": {"with": [failed, failed, GOOD_RUN], "without": [{}, {}, {}]}})
        res = self.run_real("--runs", "3", "--json", str(self.tmp / "report.json"))
        self.assert_clean(res, 0)
        self.assertEqual(self.statuses(), {"with": ["errored", "errored", "passed"], "without": ["validator_failed"] * 3})
        self.assertIn("demo-skill: works [signal: 1 of 3 run(s) per arm could be scored, a verdict needs 3] - ", res.stdout)
        self.assertIn("runs per arm: 3", res.stdout)
        skill = json.loads((self.tmp / "report.json").read_text())["skills"][0]
        self.assertEqual((skill["signal"], skill["summary"]["runs_per_arm"], skill["summary"]["scored_per_arm"]), (True, 3, 1))

    def test_report_of_a_skill_never_run_is_not_measured(self):
        res = self.report()
        self.assert_clean(res, 0)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertIn("no stored result", res.stdout)
        self.assertEqual(self.calls(), [])

    def test_skill_size_uses_the_kit_estimator(self):
        count, method = runner.skill_tokens(self.kit / "02-skills" / "demo-skill")
        text = (self.kit / "02-skills" / "demo-skill" / "SKILL.md").read_text()
        self.assertEqual(count, -(-len(text) // 4))  # BUILD.json is not part of what ships
        self.assertIn("docs_lint", method)


class Cache(RunnerTest):
    def setUp(self):
        super().setUp()
        self.play(cases=BOTH_GOOD)

    def test_stored_case_is_reported_as_cached_and_not_run_again(self):
        self.assert_clean(self.run_real(), 0)
        res = self.run_real()
        self.assert_clean(res, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("demo-skill/smoke-basic [smoke]: cached", res.stdout)
        self.assertIn("1 cached", res.stdout)
        self.assertIn("with: passed | without: passed", res.stdout)

    def test_no_cache_runs_it_again(self):
        self.assert_clean(self.run_real(), 0)
        self.assert_clean(self.run_real("--no-cache"), 0)
        self.assertEqual(len(self.calls()), 2)

    def test_change_in_the_skill_or_in_the_case_runs_it_again(self):
        self.assert_clean(self.run_real(), 0)
        with open(self.kit / "02-skills" / "demo-skill" / "SKILL.md", "a") as handle:
            handle.write("\nOne more line.\n")
        self.assert_clean(self.run_real(), 0)
        self.assertEqual(len(self.calls()), 2)
        (self.case / "prompt.md").write_text("Fix the greeting.\n")
        self.assert_clean(self.run_real(), 0)
        self.assertEqual(len(self.calls()), 3)
        self.assert_clean(self.run_real(), 0)
        self.assertEqual(len(self.calls()), 3)

    def test_result_is_stored_under_the_case_hash_and_the_runner_version(self):
        self.assert_clean(self.run_real(), 0)
        digest = skill_eval.case_hash(skill_eval.load_case(self.case), self.kit / "02-skills" / "demo-skill")
        stored = self.out / "store" / "demo-skill" / "smoke-basic" / f"{digest}.v{runner.RUNNER_VERSION}.json"
        self.assertTrue(stored.is_file(), sorted((self.out / "store").rglob("*.json")))
        record = json.loads(stored.read_text())
        self.assertEqual((record["hash"], record["runner_version"]), (digest, runner.RUNNER_VERSION))

    def test_only_the_cases_with_no_stored_result_reach_the_native_tool(self):
        self.assert_clean(self.run_real(tier="smoke"), 0)
        res = self.run_real(tier=None)
        self.assert_clean(res, 0)
        self.assertEqual(sorted(self.calls()[1]["cases"]), ["core-trigger"])
        self.assertIn("demo-skill: 2 case(s), 1 to run, 1 cached", res.stdout)


if __name__ == "__main__":
    unittest.main()
