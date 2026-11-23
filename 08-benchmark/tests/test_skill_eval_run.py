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
                        {"allow_tools": ["Edit"], "scaffold": True}):
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
