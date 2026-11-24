"""Tests for the tool mocks a skill-eval case may carry (S19): `<case>/mocks/<server>/<tool>.md`.

The format is the native tool's own: the kit checks the files and copies them, it never rewrites
them. No test starts a real `claude`: the runner tests play the stub of test_skill_eval_run.py.
"""
import hashlib
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
sys.path.insert(0, str(ROOT / "tests"))
import skill_eval  # noqa: E402
import skill_eval_native as native  # noqa: E402
import skill_eval_run as runner  # noqa: E402
from test_skill_eval_run import FIXTURES, GOOD_RUN, LIB, RunnerTest  # noqa: E402

KIT_ROOT = ROOT.parent
BODY = "Verdict: PASS\nLane: sonnet\n"
MOCK = f"---\ntype: fixed\nexpect:\n  card_text: string\nerror: false\n---\n\n{BODY}"
TOOL = "mcp__metodo__demo_tool"
OTHER = "mcp__metodo__other_tool"
FLAGS = ("--kit-mcp", "--kit-plugin")
EXPOSED = "mcp__plugin_demo-skill_metodo__demo_tool"
MOCK_FILE = "evals/smoke-basic/mocks/metodo/demo_tool.md"
TOOLS_FILE = "evals/smoke-basic/mocks/metodo/_tools.json"
SCHEMA = {"type": "object", "properties": {"card_text": {"type": "string"}}, "additionalProperties": False}


def entry(tool):
    """What the fixture server lists for one tool, as `tools/list` answers it."""
    return {"name": tool, "description": f"The {tool} tool.", "inputSchema": SCHEMA}


def tool_list_bytes(*tools):
    """The tool list file the kit writes for these mocked tools."""
    return (json.dumps({"tools": [entry(tool) for tool in tools]}, indent=2, sort_keys=True) + "\n").encode()


def give_catalog(kit, *tools):
    """A kit whose MCP catalog names `tools`, as the fixture of the runner tests declares it."""
    server = kit / "03-tools" / "mcp"
    server.mkdir(parents=True, exist_ok=True)
    (server / "__init__.py").write_text("")
    (server / "catalog.py").write_text(f"BY_NAME = {dict.fromkeys(tools)!r}\n")
    (server / "server.py").write_text(  # never started: only its answer to `tools/list` is read
        f"def tools_list():\n    return {{'tools': [{{'name': name, 'description': f'The {{name}} tool.', "
        f"'inputSchema': {SCHEMA!r}}} for name in {sorted(tools)!r}]}}\n")


def load(case_dir, kit):
    """The loaded case; the kit is named only for a case that carries mocks."""
    return skill_eval.load_case(case_dir, kit=kit) if (case_dir / "mocks").exists() else skill_eval.load_case(case_dir)


def put(case, relative, text=MOCK):
    path = case / "mocks" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class CaseWithMocks(unittest.TestCase):
    """A private kit whose catalog names two tools, and a copy of the good cases."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(os.path.realpath(tmp.name))
        self.kit = self.tmp / "kit"
        shutil.copytree(FIXTURES / "kit", self.kit)
        give_catalog(self.kit, "demo_tool", "other_tool")
        self.root = self.tmp / "evals"
        shutil.copytree(FIXTURES / "good", self.root)
        self.case = self.root / "demo-skill" / "smoke-basic"



class MockValidation(CaseWithMocks):
    """`validate` on a case that carries a `mocks/` folder."""

    def problems(self):
        return skill_eval.validate_case(self.case, kit=self.kit)

    def test_a_mock_of_a_tool_of_the_kit_server_is_valid_and_the_loaded_case_names_it(self):
        put(self.case, "metodo/demo_tool.md")
        put(self.case, "metodo/other_tool.md", "No front matter: the whole file is the answer.\n")
        self.assertEqual(self.problems(), [])
        case = skill_eval.load_case(self.case, kit=self.kit)
        self.assertEqual(case["mocks"], ["demo_tool", "other_tool"])
        self.assertEqual(case["mocks_dir"], str(self.case / "mocks"))

    def test_a_case_with_no_mocks_folder_loads_with_none(self):  # previous behavior of a case
        case = skill_eval.load_case(self.case, kit=self.kit)
        self.assertEqual((case["mocks"], case["mocks_dir"]), ([], None))
        self.assertEqual(skill_eval.validate_case(self.case), [])  # and no kit has to be named for it

    def test_a_mock_under_a_server_that_is_not_the_kits_is_a_problem(self):
        put(self.case, "tracker/demo_tool.md")
        (problem,) = self.problems()
        self.assertIn("mocks/tracker/demo_tool.md", problem)
        self.assertIn("'tracker' is not the kit's MCP server ('metodo')", problem)

    def test_a_mock_of_a_tool_that_is_not_in_the_catalog_is_a_problem(self):
        put(self.case, "metodo/no_such_tool.md")
        (problem,) = self.problems()
        self.assertIn("mocks/metodo/no_such_tool.md", problem)
        self.assertIn("'no_such_tool' is not in the kit's MCP catalog", problem)

    def test_a_front_matter_key_the_native_format_does_not_name_is_a_problem(self):
        put(self.case, "metodo/demo_tool.md", "---\ntype: fixed\nreturns: json\nwhen:\n  card_text: x\n---\nbody\n")
        problems = self.problems()
        self.assertEqual(len(problems), 2, problems)
        for key, problem in zip(("returns", "when"), problems):
            self.assertIn("mocks/metodo/demo_tool.md", problem)
            self.assertIn(f"front matter key {key!r}", problem)
            self.assertIn("type, expect, error, abort_when", problem)

    def test_every_key_the_native_format_names_is_accepted(self):
        put(self.case, "metodo/demo_tool.md",
            "---\ntype: agent\nexpect:\n  card_text: string\n  lane: [opus, sonnet]\nabort_when: never\n---\nAnswer as the server.\n")
        put(self.case, "metodo/other_tool.md", "---\nerror: true\n---\nthe card cannot be read\n")
        self.assertEqual(self.problems(), [])

    def test_front_matter_that_is_never_closed_is_a_problem(self):
        put(self.case, "metodo/demo_tool.md", "---\ntype: fixed\nbody with no closing line\n")
        (problem,) = self.problems()
        self.assertIn("front matter is not closed", problem)

    def test_a_file_under_mocks_that_the_format_does_not_name_is_a_problem(self):
        put(self.case, "metodo/demo_tool.md")
        for stray in ("notes.txt", "metodo/readme.txt", "metodo/deep/demo_tool.md", "metodo/_notes.md"):
            path = put(self.case, stray, "x\n")
            (problem,) = self.problems()
            self.assertIn(f"mocks/{stray}", problem)
            self.assertIn("is not a file the native mock format names", problem)
            path.unlink()

    def test_the_other_files_the_format_names_are_accepted(self):
        put(self.case, "metodo/demo_tool.md")
        put(self.case, "metodo/_server.md", "---\ntype: agent\ntools: [other_tool]\n---\nAnswer as the server.\n")
        put(self.case, "metodo/_tools.json", '{"tools": []}\n')
        put(self.case, "metodo/fixtures/card.json", "{}\n")
        put(self.case, ".replay/metodo/0001.json", "{}\n")
        self.assertEqual(self.problems(), [])
        self.assertEqual(skill_eval.load_case(self.case, kit=self.kit)["mocks"], ["demo_tool"])

    def test_a_tool_list_file_that_is_not_json_and_a_link_are_problems(self):
        put(self.case, "metodo/demo_tool.md")
        put(self.case, "metodo/_tools.json", "{not json")
        os.symlink(self.case / "prompt.md", self.case / "mocks" / "metodo" / "other_tool.md")
        problems = self.problems()
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("mocks/metodo/_tools.json is not valid JSON", problems[0])
        self.assertIn("mocks/metodo/other_tool.md is a symlink", problems[1])

    def test_a_mocks_folder_that_holds_no_mock_is_a_problem(self):
        put(self.case, "metodo/fixtures/card.json", "{}\n")
        (problem,) = self.problems()
        self.assertIn("mocks/ holds no mock", problem)

    def test_validate_prints_one_line_per_problem_and_exits_1(self):
        put(self.case, "tracker/demo_tool.md")
        put(self.case, "metodo/no_such_tool.md")
        put(self.case, "metodo/demo_tool.md", "---\nreturns: json\n---\nbody\n")
        put(self.case, "notes.txt", "x\n")
        res = subprocess.run([sys.executable, "-I", str(LIB), "validate", str(self.root), "--kit", str(self.kit)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual(len(lines), 5, res.stdout)
        for line in lines[:4]:
            self.assertTrue(line.startswith("demo-skill/smoke-basic: mocks/"), line)
        self.assertIn("3 cases, 2 valid, 1 with problems, 4 problems", lines[4])

    def test_the_cases_of_the_kit_are_valid_and_a_real_tool_of_its_catalog_can_be_mocked(self):
        res = subprocess.run([sys.executable, "-I", str(LIB), "validate"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        copy = self.tmp / "real" / "change-card" / "smoke-missing-field"
        shutil.copytree(KIT_ROOT / "08-benchmark" / "evals" / "change-card" / "smoke-missing-field", copy)
        put(copy, "metodo/change_card_validate.md")
        self.assertEqual(skill_eval.validate_case(copy), [])  # no kit named: the catalog of this checkout
        put(copy, "metodo/no_such_tool.md")
        self.assertEqual(len(skill_eval.validate_case(copy)), 1)

    def test_a_mock_is_part_of_the_case_hash(self):  # previous behavior: the hash covers every file of the case
        skill = self.kit / "02-skills" / "demo-skill"
        before = skill_eval.case_hash(skill_eval.load_case(self.case, kit=self.kit), skill)
        put(self.case, "metodo/demo_tool.md")
        after = skill_eval.case_hash(skill_eval.load_case(self.case, kit=self.kit), skill)
        put(self.case, "metodo/demo_tool.md", MOCK + "one more line\n")
        self.assertEqual(len({before, after, skill_eval.case_hash(skill_eval.load_case(self.case, kit=self.kit), skill)}), 3)


class MockStaging(CaseWithMocks):
    """What the kit writes into the native case folder for the mocks of a case."""

    def suite(self, **how):
        case = load(self.case, self.kit)
        plugin = self.tmp / "plugin"
        shutil.rmtree(plugin, ignore_errors=True)
        native.write_suite(plugin, [case], **how)
        folder = plugin / "evals" / "smoke-basic"
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()), folder

    def test_the_native_case_folder_holds_the_mock_files_byte_for_byte(self):
        tricky = "---\nexpect:\n  title: string\n---\n\r\nCreated {{input.title}} á\n\n"
        put(self.case, "metodo/demo_tool.md", tricky)
        put(self.case, "metodo/_tools.json", '{"tools": [ ]}')
        put(self.case, "metodo/fixtures/card.json", "{}\n")
        files, folder = self.suite(mocks=True)
        for name in ("mocks/metodo/demo_tool.md", "mocks/metodo/_tools.json", "mocks/metodo/fixtures/card.json"):
            self.assertIn(name, files)
            self.assertEqual((folder / name).read_bytes(), (self.case / name).read_bytes(), name)
        self.assertEqual([name for name in files if name.startswith("mocks/")],
                         ["mocks/metodo/_tools.json", "mocks/metodo/demo_tool.md", "mocks/metodo/fixtures/card.json"])

    def test_the_tool_list_file_holds_what_the_kit_server_lists_for_the_mocked_tools_and_no_other(self):
        put(self.case, "metodo/demo_tool.md")
        listed, why = skill_eval.kit_tool_list(self.kit)
        self.assertIsNone(why)
        self.assertEqual((listed["server"], sorted(listed["tools"])), ("metodo", ["demo_tool", "other_tool"]))
        files, folder = self.suite(mocks=True, tool_list=listed)
        self.assertEqual([name for name in files if name.startswith("mocks/")],
                         ["mocks/metodo/_tools.json", "mocks/metodo/demo_tool.md"])
        self.assertEqual((folder / "mocks/metodo/_tools.json").read_bytes(), tool_list_bytes("demo_tool"))

    def test_a_tool_list_file_the_case_carries_is_kept_as_it_is(self):
        put(self.case, "metodo/demo_tool.md")
        put(self.case, "metodo/_tools.json", '{"tools": [ ]}')
        _files, folder = self.suite(mocks=True, tool_list=skill_eval.kit_tool_list(self.kit)[0])
        self.assertEqual((folder / "mocks/metodo/_tools.json").read_text(), '{"tools": [ ]}')

    def test_no_tool_list_file_is_written_when_none_is_given(self):
        put(self.case, "metodo/demo_tool.md")
        files, _folder = self.suite(mocks=True)
        self.assertEqual([name for name in files if name.startswith("mocks/")], ["mocks/metodo/demo_tool.md"])

    def test_a_mocked_tool_the_server_does_not_list_is_refused(self):
        put(self.case, "metodo/demo_tool.md")
        with self.assertRaises(native.NativeError) as caught:
            self.suite(mocks=True, tool_list={"server": "metodo", "tools": {"other_tool": entry("other_tool")}})
        self.assertIn("demo_tool", str(caught.exception))

    def test_the_tool_list_of_this_checkout_is_the_one_its_server_answers(self):
        listed, why = skill_eval.kit_tool_list()
        self.assertIsNone(why)
        tool = listed["tools"]["change_card_validate"]
        self.assertEqual(sorted(tool), ["description", "inputSchema", "name"])
        self.assertEqual((tool["inputSchema"]["type"], tool["inputSchema"]["additionalProperties"]), ("object", False))
        self.assertIn("card_path", tool["inputSchema"]["properties"])

    def test_a_server_that_cannot_list_its_tools_gives_none_and_says_why(self):
        (self.kit / "03-tools" / "mcp" / "server.py").write_text("raise RuntimeError('the server is broken')\n")
        listed, why = skill_eval.kit_tool_list(self.kit)
        self.assertIsNone(listed)
        self.assertIn("the server is broken", why)

    def test_the_mocks_are_left_out_unless_the_run_uses_them(self):
        put(self.case, "metodo/demo_tool.md")
        files, _folder = self.suite()
        self.assertEqual([name for name in files if "mocks" in name], [])

    def test_a_link_planted_after_the_case_was_loaded_is_refused_when_the_mocks_are_staged(self):
        put(self.case, "metodo/demo_tool.md")
        case = skill_eval.load_case(self.case, kit=self.kit)
        os.symlink(self.case / "prompt.md", self.case / "mocks" / "metodo" / "other_tool.md")
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.stage_mocks(case, self.tmp / "staged")
        self.assertIn("mocks/metodo/other_tool.md is a symlink", str(caught.exception))
        self.assertFalse((self.tmp / "staged").exists())

    def test_a_case_with_no_mocks_is_written_as_before(self):  # previous files, byte for byte
        files, folder = self.suite()
        self.assertEqual(files, ["case.yaml", "files/notes.txt", "files/src/app.py", "scaffold.sh"])
        case = load(self.case, self.kit)
        self.assertEqual((folder / "case.yaml").read_text(), json.dumps(native.native_case(case), indent=2) + "\n")
        self.assertEqual((folder / "scaffold.sh").read_text(), native.SCAFFOLD_TEXT)

    def test_a_case_with_no_mocks_is_written_the_same_when_the_run_uses_mocks(self):
        plain, folder = self.suite()
        before = {name: (folder / name).read_bytes() for name in plain}
        mocked, folder = self.suite(mocks=True)
        self.assertEqual({name: (folder / name).read_bytes() for name in mocked}, before)


class CommandLine(unittest.TestCase):
    def argv(self, **how):
        return native.build_argv("claude", "/p", "/o", max_cost_usd=0.25, **how)

    def test_a_mocked_run_names_the_mock_mode_and_never_the_real_servers(self):
        argv = self.argv(mocks=True, allow_tools=["Edit"])
        self.assertEqual(argv[argv.index("--mocks") + 1], "record")
        self.assertLess(argv.index("--mocks"), argv.index("--allow-tools"))
        self.assertNotIn("--allow-real-servers", argv)
        for flag in native.REQUIRED_FLAGS:
            self.assertIn(flag, argv)

    def test_mocks_and_the_real_servers_together_are_refused(self):
        with self.assertRaises(native.NativeError) as caught:
            self.argv(mocks=True, real_servers=True)
        self.assertIn("mocks", str(caught.exception))

    def test_without_mocks_the_command_line_is_the_one_built_before(self):  # previous command line, byte for byte
        self.assertEqual(self.argv(tier="smoke", runs=1, model="haiku", judge_model="haiku", allow_tools=["Edit"], scaffold=True), [
            "claude", "plugin", "eval", "/p", "--no-publish", "--trust-plugin", "--keep-temp", "--ablation", "with-without",
            "--threshold", "0", "--max-cost-usd", "0.25", "--output-dir", "/o", "--json", "/o/result.json", "--scaffold",
            "--tag", "smoke", "--runs", "1", "--model", "haiku", "--judge-model", "haiku", "--allow-tools", "Edit"])
        self.assertEqual(self.argv(real_servers=True, ablation="none", allow_tools=["mcp__x"]), [
            "claude", "plugin", "eval", "/p", "--no-publish", "--trust-plugin", "--keep-temp", "--ablation", "none",
            "--threshold", "0", "--max-cost-usd", "0.25", "--output-dir", "/o", "--json", "/o/result.json", "--no-scaffold",
            "--allow-real-servers", "--allow-tools", "mcp__x"])


class MockedRun(RunnerTest):
    """A skill whose case carries a mock: both arms answer the kit's tool from the file, with no real server."""

    ANSWERED = {"name": EXPOSED, "input": {"card_text": "x"}, "result": BODY}

    def setUp(self):
        super().setUp()
        give_catalog(self.kit, "demo_tool")
        (self.kit / "02-skills" / "BUILD.json").write_text(json.dumps({"schema_version": 1, "kit_plugin": {
            "name": "demo-kit", "version": "0.3.0", "description": "The demo kit as one plugin.",
            "marketplace": "demo-market", "owner": "Demo Owner"}}))
        skill = self.kit / "02-skills" / "demo-skill"
        (skill / "BUILD.json").write_text(json.dumps({"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md"], "deps": [TOOL]}}))
        head, rest = (skill / "SKILL.md").read_text().split("\n---\n", 1)
        (skill / "SKILL.md").write_text(f"{head}\nallowed-tools: [Read, Edit, {TOOL}]\n---\n{rest}4. Check the result with `{TOOL}`.\n")
        self.play(cases={"smoke-basic": {"with": {**GOOD_RUN, "calls": [self.ANSWERED]}, "without": {"calls": [self.ANSWERED]}}})
        self.plain_plan = self.plan().stdout  # before the case has a mock
        self.mock = put(self.case, "metodo/demo_tool.md")

    def plan(self, *extra):
        res = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", *extra)
        self.assert_clean(res, 0)
        return res

    @staticmethod
    def after(argv, flag):
        return argv[argv.index(flag) + 1]

    def test_the_plan_says_the_run_uses_mocks_how_many_tools_no_real_server_and_two_invocations(self):
        target = self.tmp / "plan.json"
        plan = self.plan("--json", str(target))
        for said in ("2 native run(s) in 2 native invocation(s)",
                     "demo-skill: mocks: 1 tool(s) of the kit's MCP server (demo_tool) answer from the mock files of its "
                     "case(s), in both arms; the real server is not started",
                     "--ablation none", "under USD 0.25 and at most USD 0.25 of the ceiling",
                     "plan only: nothing was run and nothing was spent"):
            self.assertIn(said, plan.stdout)
        self.assertNotIn("runs without its tools", plan.stdout)
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertEqual((skill["native_invocations"], skill["without_arm"], skill["ceilings_usd"]),
                         (2, "skill_removed", [0.25, 0.25]))
        self.assertEqual(skill["mocks"], {"used": True, "tools": ["demo_tool"], "cases": 1})
        self.assertEqual(self.calls(), [])

    def declare_other_tool(self):
        """The skill declares a second tool of the kit's server, which no case mocks."""
        give_catalog(self.kit, "demo_tool", "other_tool")
        build = self.kit / "02-skills" / "demo-skill" / "BUILD.json"
        build.write_text(json.dumps({"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md"], "deps": [TOOL, OTHER]}}))
        skill = self.kit / "02-skills" / "demo-skill" / "SKILL.md"
        skill.write_text(skill.read_text().replace(f"{TOOL}]", f"{TOOL}, {OTHER}]"))

    def test_the_plan_names_a_declared_tool_that_has_no_mock(self):
        self.declare_other_tool()
        self.assertIn("1 declared tool(s) have no mock and are not available: other_tool", self.plan().stdout)

    def test_with_no_server_flag_the_plan_of_a_mocked_skill_is_the_one_printed_before(self):  # previous plan text, byte for byte
        self.assertEqual(self.plan().stdout, (
            "demo-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 2 native run(s) in 2 native invocation(s); "
            "ceiling USD 0.50\n"
            "  demo-skill: mocks: 1 tool(s) of the kit's MCP server (demo_tool) answer from the mock files of its case(s), "
            "in both arms; the real server is not started\n"
            "  demo-skill: the arm without the skill runs on the same plugin with only skills/demo-skill/ removed, so the "
            "mocked tools stay in both arms: the tool is started twice with --ablation none, under USD 0.25 and at most "
            "USD 0.25 of the ceiling\n"
            "  demo-skill/smoke-basic [smoke]: to run, 1 run(s) per arm\n"
            "skill-eval: plan only: nothing was run and nothing was spent; a real run has a ceiling of USD 0.50 "
            "(add --real to run it)\n"))

    def test_under_either_server_flag_a_mocked_skill_still_answers_from_its_mocks_and_the_plan_says_so(self):
        plain = self.plan().stdout.splitlines()
        for flag in FLAGS:
            target = self.tmp / "plan.json"
            plan = self.plan(flag, "--json", str(target))
            reach = f"  demo-skill: {flag} does not reach it: a skill whose case(s) carry mocks always answers from them"
            # the plan of no flag, and one line more that names the flag
            self.assertEqual(plan.stdout.splitlines(), plain[:2] + [reach] + plain[2:], flag)
            self.assertIn("the real server is not started", plan.stdout)
            for never in ("starts this checkout's MCP server", "evaluates it from the kit plugin", "are left out"):
                self.assertNotIn(never, plan.stdout, flag)
            (skill,) = json.loads(target.read_text())["skills"]
            self.assertEqual(skill["mocks"], {"used": True, "tools": ["demo_tool"], "cases": 1})
            self.assertEqual((skill["kit_mcp"], skill["kit_plugin"], skill["without_arm"]), (False, False, "skill_removed"))

    def test_run_all_under_a_server_flag_starts_the_real_server_only_for_the_skills_whose_cases_carry_no_mock(self):
        mocked = self.plan().stdout.splitlines()[:2]
        other = {  # what a skill with no mock says under each flag, as before, byte for byte
            "--kit-mcp": ["other-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 6 native run(s); ceiling USD 0.50",
                          "  other-skill/smoke-judge [smoke]: to run, 3 run(s) per arm"],
            "--kit-plugin": [
                "other-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 6 native run(s) in 2 native invocation(s); "
                "ceiling USD 0.50",
                "  other-skill: --kit-plugin evaluates it from the kit plugin (every skill plus the kit's MCP server, started "
                "from the plugin's own files; it runs as you, outside the tool's sandbox) and allows the 0 tool(s) the skill "
                "declares",
                "  other-skill: the arm without the skill runs on the same plugin with only skills/other-skill/ removed, so "
                "the server and its tools stay in both arms: the tool is started twice with --ablation none, under USD 0.25 "
                "and at most USD 0.25 of the ceiling",
                "  other-skill/smoke-judge [smoke]: to run, 3 run(s) per arm"]}
        for flag in FLAGS:
            res = self.cli("run", "--all", *self.where(), "--tier", "smoke", flag)
            self.assert_clean(res, 0)
            lines = res.stdout.splitlines()
            start = lines.index(other[flag][0])
            self.assertEqual(lines[:2], mocked, flag)
            self.assertEqual(lines[start:-1], other[flag], flag)
            self.assertEqual(self.calls(), [])
        shutil.rmtree(self.case / "mocks")  # and a skill that declares tools and has no mock is served, as before
        self.assertIn("demo-skill: --kit-mcp starts this checkout's MCP server for its runs", self.plan("--kit-mcp").stdout)
        self.assertIn("demo-skill: --kit-plugin evaluates it from the kit plugin", self.plan("--kit-plugin").stdout)

    def test_both_arms_get_the_same_mocks_and_the_arm_without_the_skill_lacks_only_the_skill(self):
        res = self.run_real("--max-cost-usd", "0.25")
        self.assert_clean(res, 0)
        used, bare = self.calls()
        digest = hashlib.sha256(self.mock.read_bytes()).hexdigest()
        gone = [name for name in used["files"] if name.startswith("skills/demo-skill/")]
        self.assertIn("skills/demo-skill/SKILL.md", gone)
        self.assertEqual(bare["files"], [name for name in used["files"] if name not in gone])
        self.assertEqual(bare["sha256"], {name: value for name, value in used["sha256"].items() if name not in gone})
        self.assertEqual(bare["cases"], used["cases"])
        for call in (used, bare):
            self.assertEqual(call["sha256"][MOCK_FILE], digest)
            self.assertEqual([name for name in call["files"] if "/mocks/" in name], [TOOLS_FILE, MOCK_FILE])
            self.assertEqual(call["sha256"][TOOLS_FILE], hashlib.sha256(tool_list_bytes("demo_tool")).hexdigest())
            self.assertIn("metodo", call["mcp"]["mcpServers"])  # the server is declared, so the mock has a server to stand for
            self.assertEqual(self.after(call["argv"], "--ablation"), "none")
            self.assertEqual(self.after(call["argv"], "--mocks"), "record")
            self.assertNotIn("--allow-real-servers", call["argv"])
            self.assertIn(EXPOSED, call["argv"][call["argv"].index("--allow-tools") + 1:])
            self.assertIn(EXPOSED, call["cases"]["smoke-basic"]["execution"]["allowed_tools"])
            for flag in native.REQUIRED_FLAGS:
                self.assertIn(flag, call["argv"])
        self.assertLessEqual(sum(float(self.after(call["argv"], "--max-cost-usd")) for call in (used, bare)), 0.25)
        self.assertIn(EXPOSED, used["skill_text"])
        self.assertEqual(bare["skill_text"], "")

    def test_the_stored_result_keeps_what_the_mocked_tool_answered_in_each_arm_and_the_report_says_so(self):
        res = self.run_real()
        self.assert_clean(res, 0)
        record = self.stored()
        for arm in ("with", "without"):
            (run,) = record["arms"][arm]
            self.assertEqual(run["mcp_answers"], [{"tool": EXPOSED, "error": False, "answer": "Verdict: PASS Lane: sonnet"}])
            self.assertEqual(run["mcp_calls"], 1)
        self.assertEqual(record["mcp"], {"declared": [TOOL], "served": False, "mocks": True, "mocked": ["demo_tool"]})
        self.assertIs(record["settings"]["mocks"], True)
        self.assertEqual(record["without_arm"]["how"], "skill_removed")
        for shown in (res, self.report()):
            self.assertIn("mocked tools: answered from the mock files of 1 case(s), the real server not started; "
                          "1 call(s) to them in the runs with the skill", shown.stdout)
            self.assertIn("arm without the skill: the same plugin with only skills/demo-skill/ removed, in a second "
                          "invocation of the tool: the mocked tools stay; 1 call(s) to its tools in the runs without "
                          "the skill", shown.stdout)
            self.assertIn("demo-skill: works", shown.stdout)
            self.assertNotIn("kit MCP server: started", shown.stdout)
            self.assertNotIn("without its tools", shown.stdout)
            self.assertNotIn("no mock", shown.stdout)  # every declared tool has one

    def test_a_stored_result_of_a_mocked_run_is_reused_whichever_server_flag_is_given(self):
        self.assert_clean(self.run_real(), 0)
        first = self.stored()
        self.assertEqual(len(self.calls()), 2)
        for flag in FLAGS:
            res = self.run_real(flag)
            self.assert_clean(res, 0)
            self.assertEqual(len(self.calls()), 2, flag)  # nothing was started: the stored result stands
            self.assertIn("demo-skill/smoke-basic [smoke]: cached (stored", res.stdout)
            self.assertEqual(self.stored(), first, flag)
        self.assert_clean(self.run_real("--kit-plugin", "--no-cache"), 0)  # and one stored under a flag, with none
        self.assertEqual(len(self.calls()), 4)
        self.assert_clean(self.run_real(), 0)
        self.assertEqual(len(self.calls()), 4)

    def test_a_result_stored_without_mocks_is_not_reused_for_a_run_that_answers_from_them(self):  # previous behavior
        stored = {"settings": {"model": None, "judge_model": None, "runs": 1, "kit_mcp": False, "kit_plugin": False}}
        asked = {**stored["settings"], "mocks": True}
        self.assertEqual(runner.settings_differ(stored, asked), ["the case's mocks False, now True"])
        self.assertEqual(runner.settings_differ({"settings": asked}, {**asked, "mocks": False}), ["the case's mocks True, now False"])

    def test_under_a_server_flag_the_case_folder_the_command_line_and_the_stored_settings_are_the_ones_of_no_flag(self):
        def made(*flag):
            self.log.unlink(missing_ok=True)
            self.assert_clean(self.run_real(*flag, "--no-cache"), 0)
            calls = self.calls()
            for call in calls:
                self.assertEqual([name for name in call["files"] if "/mocks/" in name], [TOOLS_FILE, MOCK_FILE], flag)
                self.assertEqual(self.after(call["argv"], "--mocks"), "record")
                self.assertNotIn("--allow-real-servers", call["argv"])
                for required in native.REQUIRED_FLAGS:
                    self.assertIn(required, call["argv"])
            record = self.stored()
            return ([[arg.replace(self.after(call["argv"], "--output-dir"), "OUT") for arg in call["argv"]] for call in calls],
                    [(call["files"], call["sha256"], call["cases"], call["mcp"]) for call in calls],
                    {key: record[key] for key in ("settings", "mcp", "package", "without_arm")})

        plain = made()
        self.assertEqual(len(plain[0]), 2)
        self.assertEqual((plain[2]["settings"]["kit_mcp"], plain[2]["settings"]["kit_plugin"], plain[2]["settings"]["mocks"]),
                         (False, False, True))
        for flag in FLAGS:
            for part, ours, theirs in zip(("command line", "plugin and case folder", "stored result"), made(flag), plain):
                self.assertEqual(ours, theirs, f"{flag}: {part}")

    def test_the_report_names_the_declared_tools_that_had_no_mock_and_the_verdict_stays_as_computed(self):
        self.declare_other_tool()
        target = self.tmp / "report.json"
        res = self.run_real("--json", str(target))
        self.assert_clean(res, 0)
        # the shape a mocked result was stored in before: the report reads it as it is
        self.assertEqual(self.stored()["mcp"], {"declared": [TOOL, OTHER], "served": False, "mocks": True, "mocked": ["demo_tool"]})
        line = ("  tools with no mock: 1 declared tool(s) had no mock and were not available in 1 of 1 mocked case(s): "
                "other_tool; the verdict above does not take this into account")
        for shown in (res, self.report()):
            self.assert_clean(shown, 0)
            self.assertEqual([said for said in shown.stdout.splitlines() if said.startswith("  tools with no mock")], [line])
            self.assertIn("demo-skill: works", shown.stdout)
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertEqual(skill["summary"]["mcp_absent"], {"tools": ["other_tool"], "cases": 1})

    def test_a_mocked_result_that_does_not_say_which_tools_had_a_mock_reports_without_the_line(self):
        self.declare_other_tool()
        self.assert_clean(self.run_real(), 0)
        (path,) = (self.out / "store" / "demo-skill" / "smoke-basic").glob("*.json")
        record = json.loads(path.read_text())
        del record["mcp"]["mocked"]
        path.write_text(json.dumps(record))
        shown = self.report()
        self.assert_clean(shown, 0)
        self.assertIn("mocked tools: answered from the mock files of 1 case(s)", shown.stdout)
        self.assertNotIn("no mock", shown.stdout)

    def test_a_server_that_cannot_list_its_tools_leaves_the_skill_not_measured_and_starts_nothing(self):
        (self.kit / "03-tools" / "mcp" / "server.py").write_text("raise RuntimeError('the server is broken')\n")
        res = self.run_real()
        self.assert_clean(res, 1)
        self.assertIn("skill-eval: demo-skill: the tool list of the kit's MCP server cannot be read", res.stderr)
        self.assertIn("demo-skill: not measured", res.stdout)
        self.assertEqual(self.calls(), [])

    def test_a_ceiling_that_is_not_finite_is_refused_for_a_mocked_run_too(self):
        res = self.cli("run", "--skill", "demo-skill", *self.where(), "--tier", "smoke", "--max-cost-usd", "inf")
        self.assertEqual((res.returncode, res.stdout), (2, ""), res.stderr)
        self.assertIn("cannot be shared between the two invocations a run with mocked tools makes", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_mock_the_validator_refuses_stops_the_run_before_anything_starts(self):
        put(self.case, "metodo/no_such_tool.md")
        res = self.run_real()
        self.assertEqual((res.returncode, res.stdout), (2, ""), res.stderr)
        self.assertIn("'no_such_tool' is not in the kit's MCP catalog", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_without_mocks_the_plan_is_the_one_printed_before(self):  # previous plan text, byte for byte
        shutil.rmtree(self.case / "mocks")
        target = self.tmp / "plan.json"
        self.assertEqual(self.plan("--json", str(target)).stdout, self.plain_plan)
        self.assertEqual(self.plain_plan, (
            "demo-skill: 1 case(s), 1 to run, 0 cached; arms with, without; 2 native run(s); ceiling USD 0.50\n"
            "  demo-skill declares 1 MCP tool(s) of the kit's server, which this run does not start: the skill runs "
            "without its tools, so its verdict cannot be `works` (add --kit-mcp to start the server)\n"
            "  demo-skill/smoke-basic [smoke]: to run, 1 run(s) per arm\n"
            "skill-eval: plan only: nothing was run and nothing was spent; a real run has a ceiling of USD 0.50 "
            "(add --real to run it)\n"))
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertEqual(sorted(skill), ["arms", "cached", "cases", "ceiling_usd", "ceilings_usd", "has_skill", "kit_mcp",
                                         "kit_plugin", "mcp_tools", "native_invocations", "native_runs", "skill",
                                         "to_run", "without_arm"])
        kit_mcp = self.plan("--kit-mcp").stdout
        self.assertNotIn("mock", kit_mcp)
        self.assertIn("so the server and its tools stay in both arms: the tool is started twice with --ablation none", kit_mcp)

    def test_without_mocks_the_command_line_the_files_and_the_stored_result_are_the_ones_of_before(self):  # byte for byte
        shutil.rmtree(self.case / "mocks")
        target = self.tmp / "report.json"
        self.assert_clean(self.run_real("--max-cost-usd", "0.25", "--json", str(target)), 0)
        (call,) = self.calls()
        out = pathlib.Path(self.after(call["argv"], "--output-dir"))
        self.assertEqual(call["argv"], [
            "plugin", "eval", str(self.out / "work" / "demo-skill" / "plugin"), "--no-publish", "--trust-plugin",
            "--keep-temp", "--ablation", "with-without", "--threshold", "0", "--max-cost-usd", "0.25",
            "--output-dir", str(out), "--json", str(out / "result.json"), "--scaffold", "--tag", "smoke",
            "--allow-tools", "Edit"])
        self.assertEqual(call["files"], [
            ".claude-plugin/plugin.json", "MANIFEST.json", "evals/smoke-basic/case.yaml",
            "evals/smoke-basic/files/notes.txt", "evals/smoke-basic/files/src/app.py", "evals/smoke-basic/scaffold.sh",
            "skills/demo-skill/SKILL.md"])
        case = load(self.case, self.kit)
        written = (json.dumps(native.native_case(case), indent=2) + "\n").encode()
        self.assertEqual(call["sha256"]["evals/smoke-basic/case.yaml"], hashlib.sha256(written).hexdigest())
        record = self.stored()
        self.assertEqual(record["mcp"], {"declared": [TOOL], "served": False})
        self.assertEqual(sorted(record["settings"]), ["claude_version", "judge_model", "kit_mcp", "kit_plugin",
                                                     "max_cost_usd", "model", "runs"])
        self.assertEqual(sorted(record), ["arms", "case", "expected_skills", "hash", "mcp", "native", "package",
                                         "runner_version", "settings", "skill", "skill_tokens", "stored_at", "tier",
                                         "token_method", "without_arm"])
        (skill,) = json.loads(target.read_text())["skills"]
        self.assertNotIn("mcp_mocked", skill["summary"])
        self.assertNotIn("mcp_absent", skill["summary"])
        self.assertEqual(runner.RUNNER_VERSION, 5)  # no stored result changed its meaning


if __name__ == "__main__":
    unittest.main()
