"""lib/skill_build.py: the BUILD declaration per skill, its five targets, the cache of what
passed, the deterministic package and the command. Every kit here is a throwaway folder under
the system temp dir with its own two-tool MCP catalog; the type checker is a stub named by an
environment variable. No network, no model call, no `claude`, `pi` or `agy` process."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from lib import skill_build

TOOLS_ROOT = Path(__file__).resolve().parent.parent
KIT_ROOT = TOOLS_ROOT.parent
WRAPPER = TOOLS_ROOT / "bin" / "skill-build.sh"
CASE_VALIDATOR = KIT_ROOT / "08-benchmark" / "lib" / "skill_eval.py"
DEMO_TOOL = "mcp__metodo__demo_tool"
LINE_RE = re.compile(r"^(PASS|FAIL|SKIP) [a-z0-9-]+:[A-Za-z_]+ \S.*$")


def all_targets(**agent_skill) -> dict:
    """Every target declared; the skill is one SKILL.md that needs one catalog tool."""
    return {"agent_skill": {"srcs": ["SKILL.md"], "deps": [DEMO_TOOL], **agent_skill},
            "validate_skill_test": {}, "py_type_test": {}, "py_test": {}, "eval_suite": {}}


def skill_md(name="demo", description="Does a demo thing.", version="1.2.0", tools=("Read", DEMO_TOOL), body="Body.\n") -> str:
    lines = ["---", f"name: {name}", f"description: {description}"]
    if version:
        lines.append(f"version: {version}")
    return "\n".join(lines + [f"allowed-tools: [{', '.join(tools)}]", "---", "", body])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class KitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="skill-build-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "kit"
        catalog = self.root / "03-tools" / "mcp"
        catalog.mkdir(parents=True)
        (catalog / "__init__.py").write_text("", encoding="utf-8")
        (catalog / "catalog.py").write_text('BY_NAME = {"demo_tool": None, "other_tool": None}\n', encoding="utf-8")
        (self.root / "02-skills").mkdir()
        self.kit = skill_build.Kit(self.root)

    def add_skill(self, name="demo", build=None, md=None, files=None) -> Path:
        """A skill folder; `build` is the BUILD.json object without its version, False for none."""
        folder = self.root / "02-skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(skill_md(name) if md is None else md, encoding="utf-8")
        for relative, text in (files or {}).items():
            (folder / relative).parent.mkdir(parents=True, exist_ok=True)
            (folder / relative).write_text(text, encoding="utf-8")
        if build is not False:
            self.write_build(name, {"schema_version": 1, **(all_targets() if build is None else build)})
        return folder

    def write_build(self, name: str, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / "02-skills" / name / "BUILD.json").write_text(text, encoding="utf-8")

    def problems(self, name="demo") -> list[str]:
        return skill_build.load_build(self.kit, name)[1]

    def target(self, target: str, name="demo", use_cache=False) -> dict:
        results = skill_build.run_skill(self.kit, name, use_cache=use_cache)
        found = [r for r in results if r["target"] == target]
        self.assertEqual(len(found), 1, results)
        return found[0]

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = skill_build.main(list(argv), kit_root=self.root)
        return code, out.getvalue(), err.getvalue()

    def add_counting_tests(self) -> dict:
        """A `py_test` declaration whose one test appends to <kit>/runs.log and fails on <kit>/fail.flag."""
        tests = self.root / "pkg" / "tests"
        tests.mkdir(parents=True)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_count.py").write_text(
            "import pathlib\nimport unittest\n\n\n"
            "class CountTests(unittest.TestCase):\n"
            "    def test_it(self):\n"
            "        kit = pathlib.Path(__file__).resolve().parents[2]\n"
            "        with open(kit / 'runs.log', 'a', encoding='utf-8') as log:\n"
            "            log.write('x')\n"
            "        self.assertFalse((kit / 'fail.flag').exists())\n", encoding="utf-8")
        return {"cwd": "pkg", "modules": ["tests.test_count"], "inputs": ["pkg/tests/test_count.py"]}

    def runs(self) -> int:
        log = self.root / "runs.log"
        return len(log.read_text(encoding="utf-8")) if log.exists() else 0


class DeclarationTests(KitCase):
    def test_the_example_of_the_docstring_is_a_valid_declaration(self):
        example = re.search(r"Example[^\n]*:\n\n(.*?)\n\n", skill_build.__doc__, re.DOTALL).group(1)
        data = json.loads(example)
        self.assertEqual(set(data) - {"schema_version"}, set(skill_build.TARGETS))
        self.add_skill(build=False)
        self.write_build("demo", data)
        build, problems = skill_build.load_build(self.kit, "demo")
        self.assertEqual(problems, [])
        self.assertEqual(build["agent_skill"]["srcs"], data["agent_skill"]["srcs"])

    def test_an_unknown_key_is_one_problem_line(self):
        self.add_skill(build={**all_targets(), "lint_test": {}, "py_test": {"module": ["x"]}})
        problems = self.problems()
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("unknown key 'lint_test'" in p for p in problems), problems)
        self.assertTrue(any("py_test" in p and "unknown key 'module'" in p for p in problems), problems)
        self.assertTrue(all("\n" not in p for p in problems))

    def test_a_wrong_type_is_one_problem_line(self):
        self.add_skill(build=False)
        cases = {
            "schema_version": {"schema_version": "1", **all_targets()},
            "validate_skill_test": {"schema_version": 1, "validate_skill_test": []},
            "srcs": {"schema_version": 1, "agent_skill": {"srcs": "SKILL.md"}},
            "deps": {"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md"], "deps": [3]}},
            "modules": {"schema_version": 1, "py_test": {"cwd": "pkg", "modules": ["not a module"]}},
        }
        for key, data in cases.items():
            with self.subTest(key=key):
                self.write_build("demo", data)
                problems = self.problems()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(key, problems[0])
        self.write_build("demo", "{not json")
        self.assertEqual(len(self.problems()), 1)
        self.write_build("demo", {"agent_skill": {"srcs": ["SKILL.md"]}})
        self.assertIn("schema_version", self.problems()[0])

    def test_a_path_that_leaves_the_kit_is_one_problem_line(self):
        self.add_skill(build=False)
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("x", encoding="utf-8")
        os.symlink(outside / "secret.md", self.root / "02-skills" / "demo" / "linked.md")
        os.symlink(outside, self.root / "escape")
        cases = {
            "srcs: '../other/SKILL.md'": {"agent_skill": {"srcs": ["SKILL.md", "../other/SKILL.md"]}},
            "srcs: 'linked.md'": {"agent_skill": {"srcs": ["SKILL.md", "linked.md"]}},
            "deps: '../outside'": {"agent_skill": {"srcs": ["SKILL.md"], "deps": ["../outside"]}},
            "deps: 'escape/secret.md'": {"agent_skill": {"srcs": ["SKILL.md"], "deps": ["escape/secret.md"]}},
            "py_test.cwd: '/tmp'": {"py_test": {"cwd": "/tmp", "modules": ["tests.test_x"]}},
            "py_test.inputs: '../../etc'": {"py_test": {"cwd": "pkg", "modules": ["tests.test_x"], "inputs": ["../../etc"]}},
        }
        for label, targets in cases.items():
            with self.subTest(path=label):
                self.write_build("demo", {"schema_version": 1, **targets})
                problems = self.problems()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(label.split(":")[0], problems[0])
                self.assertIn("leaves", problems[0])
        # negative control: a path inside the kit is no problem, whether or not it exists yet
        self.write_build("demo", {"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md"], "deps": ["03-tools/lib"]}})
        self.assertEqual(self.problems(), [])

    def test_srcs_never_name_the_build_file_or_a_cache_folder_and_always_the_skill_md(self):
        self.add_skill(build=False)
        for src in ("BUILD.json", "__pycache__/x.pyc", ".DS_Store"):
            with self.subTest(src=src):
                self.write_build("demo", {"schema_version": 1, "agent_skill": {"srcs": ["SKILL.md", src]}})
                self.assertEqual(len(self.problems()), 1, self.problems())
                self.assertIn(src, self.problems()[0])
        self.write_build("demo", {"schema_version": 1, "agent_skill": {"srcs": ["notes.md"]}})
        self.assertIn("SKILL.md", self.problems()[0])


class AgentSkillTests(KitCase):
    def test_it_passes_and_says_what_the_skill_needs(self):
        self.add_skill()
        result = self.target("agent_skill")
        self.assertEqual(result["status"], "PASS", result)
        self.assertIn("1 file", result["reason"])
        self.assertIn("metodo", result["reason"])

    def test_a_declared_tool_that_is_not_in_the_catalog_fails(self):
        gone = "mcp__metodo__gone_tool"
        self.add_skill(build=all_targets(deps=[gone]), md=skill_md(tools=("Read", gone)))
        result = self.target("agent_skill")
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn(f"{gone} is not in the MCP catalog", result["reason"])

    def test_deps_and_allowed_tools_that_disagree_fail_in_both_directions(self):
        other = "mcp__metodo__other_tool"
        self.add_skill("undeclared", build=all_targets(deps=[]), md=skill_md("undeclared"))
        self.add_skill("unused", build=all_targets(deps=[DEMO_TOOL, other]), md=skill_md("unused"))
        undeclared = self.target("agent_skill", "undeclared")
        self.assertEqual(undeclared["status"], "FAIL", undeclared)
        self.assertIn(f"allowed-tools names {DEMO_TOOL}", undeclared["reason"])
        unused = self.target("agent_skill", "unused")
        self.assertEqual(unused["status"], "FAIL", unused)
        self.assertIn(f"deps names {other}", unused["reason"])

    def test_a_src_or_a_kit_path_that_does_not_exist_fails(self):
        self.add_skill("nofile", build=all_targets(srcs=["SKILL.md", "report.py"]), md=skill_md("nofile"))
        self.add_skill("nodep", build=all_targets(deps=[DEMO_TOOL, "03-tools/lib/gone.py"]), md=skill_md("nodep"))
        self.assertIn("report.py does not exist", self.target("agent_skill", "nofile")["reason"])
        self.assertEqual(self.target("agent_skill", "nofile")["status"], "FAIL")
        self.assertIn("03-tools/lib/gone.py does not exist", self.target("agent_skill", "nodep")["reason"])

    def test_the_zip_holds_the_plugin_manifest_the_srcs_and_what_the_package_requires(self):
        self.add_skill(build=all_targets(srcs=["SKILL.md", "guide.md", "tool.py"]),
                       files={"guide.md": "guide\n", "tool.py": "X = 1\n"})
        self.add_skill("alone", build=all_targets(deps=[]), md=skill_md("alone", tools=("Read",)))
        path = skill_build.build_package(self.kit, "demo", self.tmp / "out")
        self.assertEqual(path, self.tmp / "out" / "demo" / "demo-1.2.0.zip")
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            plugin = json.loads(package.read(".claude-plugin/plugin.json"))
            manifest = json.loads(package.read("MANIFEST.json"))
            skill_text = package.read("skills/demo/SKILL.md")
        self.assertEqual(names, sorted([".claude-plugin/plugin.json", "MANIFEST.json", "skills/demo/SKILL.md",
                                        "skills/demo/guide.md", "skills/demo/tool.py"]))
        self.assertEqual(plugin, {"name": "demo", "version": "1.2.0", "description": "Does a demo thing."})
        self.assertEqual(skill_text, (self.root / "02-skills" / "demo" / "SKILL.md").read_bytes())
        self.assertEqual(manifest["files"], ["SKILL.md", "guide.md", "tool.py"])
        self.assertEqual(manifest["requires"]["mcp_server"], "metodo")
        self.assertEqual(manifest["requires"]["mcp_tools"], [DEMO_TOOL])
        self.assertIs(manifest["standalone"], False)
        with zipfile.ZipFile(skill_build.build_package(self.kit, "alone", self.tmp / "out")) as package:
            alone = json.loads(package.read("MANIFEST.json"))
        self.assertIs(alone["standalone"], True)
        self.assertEqual(alone["requires"], {"mcp_server": None, "mcp_tools": [], "kit_paths": [], "tools_root_token": []})

    def test_the_zip_is_byte_identical_for_identical_inputs(self):
        folder = self.add_skill(build=all_targets(srcs=["SKILL.md", "tool.py"]), files={"tool.py": "X = 1\n"})
        first = skill_build.build_package(self.kit, "demo", self.tmp / "one")
        os.utime(folder / "SKILL.md", (1_000_000_000, 1_000_000_000))
        os.chmod(folder / "tool.py", 0o600)
        second = skill_build.build_package(self.kit, "demo", self.tmp / "two")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as package:
            infos = package.infolist()
        self.assertEqual({info.date_time for info in infos}, {(1980, 1, 1, 0, 0, 0)})
        self.assertEqual({info.external_attr >> 16 for info in infos}, {0o100644})
        # negative control: one changed byte of a src changes the package
        (folder / "tool.py").write_text("X = 2\n", encoding="utf-8")
        self.assertNotEqual(sha256(skill_build.build_package(self.kit, "demo", self.tmp / "three")), sha256(first))

    def test_the_zip_never_holds_the_build_file_a_cache_folder_or_a_file_outside_srcs(self):
        self.add_skill(files={"draft.md": "not declared\n", "__pycache__/tool.cpython-311.pyc": "x", ".DS_Store": "x"})
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "out")) as package:
            names = package.namelist()
        self.assertEqual(names, [".claude-plugin/plugin.json", "MANIFEST.json", "skills/demo/SKILL.md"])

    def test_a_file_carrying_the_tools_default_token_is_packed_verbatim_and_declared(self):
        body = 'Run `POST="${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/post.py"`.\n'
        self.add_skill(build=all_targets(deps=[DEMO_TOOL, "03-tools"]), md=skill_md(body=body))
        self.add_skill("silent", md=skill_md("silent", body=body))
        self.assertEqual(self.target("agent_skill")["status"], "PASS", self.target("agent_skill"))
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "out")) as package:
            manifest = json.loads(package.read("MANIFEST.json"))
            self.assertIn(b"${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/post.py", package.read("skills/demo/SKILL.md"))
        self.assertEqual(manifest["requires"]["tools_root_token"], ["SKILL.md"])
        self.assertEqual(manifest["requires"]["kit_paths"], ["03-tools"])
        self.assertIs(manifest["standalone"], False)
        silent = self.target("agent_skill", "silent")
        self.assertEqual(silent["status"], "FAIL", silent)
        self.assertIn("__TOOLS_DEFAULT__", silent["reason"])
        self.assertIn("03-tools", silent["reason"])
        # laid out for this checkout, the token becomes its tools root, as the installers render it
        skill_build.layout_plugin(self.kit, "demo", self.tmp / "local", local_mcp=True)
        local = (self.tmp / "local" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"${{METODO_TOOLS:-{self.root / '03-tools'}}}/lib/post.py", local)
        self.assertNotIn("__TOOLS_DEFAULT__", local)

    def test_the_plugin_folder_is_the_zip_and_the_local_mcp_file_is_never_packed(self):
        self.add_skill(build=all_targets(srcs=["SKILL.md", "tool.py"]), files={"tool.py": "X = 1\n"})
        plain = skill_build.layout_plugin(self.kit, "demo", self.tmp / "plain")
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "out")) as package:
            packed = {name: package.read(name) for name in package.namelist()}

        def tree(folder: Path) -> dict:
            return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

        self.assertEqual(tree(self.tmp / "plain"), packed)
        self.assertEqual(plain["plugin_dir"], str(self.tmp / "plain"))
        self.assertEqual(plain["invoke"], "demo:demo")
        self.assertIs(plain["local_mcp"], False)
        skill_build.layout_plugin(self.kit, "demo", self.tmp / "local", local_mcp=True)
        local = tree(self.tmp / "local")
        self.assertEqual(set(local) - set(packed), {".mcp.json"})
        server = json.loads(local[".mcp.json"])["mcpServers"]["metodo"]
        self.assertEqual(server["args"], [str(self.root / "03-tools" / "mcp" / "server.py")])
        self.assertNotIn(".mcp.json", packed)
        # a folder that already holds something is refused: a stale file would be evaluated
        with self.assertRaises(skill_build.BuildError):
            skill_build.layout_plugin(self.kit, "demo", self.tmp / "local")


class ValidateSkillTests(KitCase):
    def test_a_well_formed_front_matter_passes(self):
        self.add_skill(md=skill_md(description='"Writes a comment: one paragraph."'))
        result = self.target("validate_skill_test")
        self.assertEqual(result["status"], "PASS", result)

    def test_a_name_that_is_not_the_folder_fails(self):
        self.add_skill(md=skill_md("other"))
        result = self.target("validate_skill_test")
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("'other'", result["reason"])
        self.assertIn("'demo'", result["reason"])

    def test_an_empty_or_missing_description_fails(self):
        self.add_skill("empty", md=skill_md("empty", description='""'))
        self.add_skill("missing", md="---\nname: missing\nversion: 1.0.0\n---\nBody.\n")
        self.add_skill("bare", md="No front matter here.\n")
        for name in ("empty", "missing"):
            with self.subTest(skill=name):
                result = self.target("validate_skill_test", name)
                self.assertEqual(result["status"], "FAIL", result)
                self.assertIn("description", result["reason"])
        self.assertIn("front matter", self.target("validate_skill_test", "bare")["reason"])

    def test_a_plain_scalar_holding_a_colon_space_or_a_space_hash_fails(self):
        self.add_skill("colon", md=skill_md("colon", description="Writes a comment: one paragraph."))
        self.add_skill("hash", md=skill_md("hash", description="Counts issue #12 and others."))
        self.add_skill("item", md="---\nname: item\ndescription: Fine.\ntriggers:\n  - say: this\n---\nBody.\n")
        for name, breaker in (("colon", "': '"), ("hash", "' #'"), ("item", "': '")):
            with self.subTest(skill=name):
                result = self.target("validate_skill_test", name)
                self.assertEqual(result["status"], "FAIL", result)
                self.assertIn(breaker, result["reason"])


class PyTypeTests(KitCase):
    def stub(self, exit_code=0, name="mypy") -> Path:
        """A stand-in checker under the name of one of the table: it answers `--version` from
        <tmp>/checker.version, keeps a copy of a `--project` file, logs its arguments and exits
        with `exit_code`."""
        path = self.tmp / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "--version" ]; then cat "{self.tmp}/checker.version" 2>/dev/null || echo "stub 1.0"; exit 0; fi\n'
            'prev=""\n'
            f'for arg in "$@"; do if [ "$prev" = "--project" ]; then cp "$arg" "{self.tmp}/project.json"; fi; prev="$arg"; done\n'
            f'echo "$@" >> "{self.tmp}/checker.log"\necho "stub: checked"\nexit {exit_code}\n', encoding="utf-8")
        os.chmod(path, 0o755)
        return path

    def with_python(self):
        self.add_skill(build=all_targets(srcs=["SKILL.md", "tool.py"]), files={"tool.py": "X: int = 1\n"})

    def test_a_skill_without_python_is_a_skip(self):
        self.add_skill()
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub())}):
            result = self.target("py_type_test")
        self.assertEqual((result["status"], result["reason"]), ("SKIP", "no Python in this skill"))
        self.assertFalse((self.tmp / "checker.log").exists())

    def test_a_missing_checker_is_a_skip_that_names_it(self):
        self.with_python()
        empty = self.tmp / "empty-bin"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            os.environ.pop(skill_build.CHECKER_ENV, None)
            none = self.target("py_type_test")
            os.environ[skill_build.CHECKER_ENV] = "absent-checker"
            named = self.target("py_type_test")
        self.assertEqual(none["status"], "SKIP", none)
        for checker in skill_build.CHECKERS:
            self.assertIn(checker, none["reason"])
        self.assertEqual(named["status"], "SKIP", named)
        self.assertIn("absent-checker", named["reason"])
        self.assertIn("not installed", named["reason"])

    def test_the_checker_runs_over_the_python_sources_and_its_exit_code_decides(self):
        self.with_python()
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(0))}):
            passed = self.target("py_type_test")
        self.assertEqual(passed["status"], "PASS", passed)
        self.assertEqual((self.tmp / "checker.log").read_text(encoding="utf-8").split(), ["--strict", "tool.py"])
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(1))}):
            failed = self.target("py_type_test")
        self.assertEqual(failed["status"], "FAIL", failed)
        self.assertIn("stub: checked", failed["reason"])

    def test_a_named_checker_the_table_does_not_know_is_a_skip_never_a_pass(self):  # R2-named-checker-not-strict
        self.with_python()
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(0, name="lenient-checker"))}):
            result = self.target("py_type_test")
        self.assertEqual(result["status"], "SKIP", result)
        self.assertIn("lenient-checker", result["reason"])
        self.assertIn("strict", result["reason"])
        self.assertFalse((self.tmp / "checker.log").exists(), "a checker with no strict argv must not run")

    def test_every_checker_of_the_table_runs_strict_and_its_pass_says_the_argv_is_unverified(self):  # R2-named-checker-not-strict
        self.with_python()
        log = self.tmp / "checker.log"
        for name in skill_build.CHECKERS:
            with self.subTest(checker=name):
                log.unlink(missing_ok=True)
                with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(0, name=name))}):
                    result = self.target("py_type_test")
                self.assertEqual(result["status"], "PASS", result)
                self.assertIn("unverified", result["reason"])
                argv = log.read_text(encoding="utf-8").split()
                self.assertEqual(argv[-1], "tool.py")
                if name == "mypy":
                    self.assertIn("--strict", argv)
                elif name == "pytype":
                    self.assertGreater(len(argv), 1)
                    self.assertTrue(all(flag.startswith("--strict-") for flag in argv[:-1]), argv)
                else:
                    self.assertIn("--project", argv)
                    project = json.loads((self.tmp / "project.json").read_text(encoding="utf-8"))
                    self.assertEqual(project["typeCheckingMode"], "strict")

    def test_a_new_version_of_the_checker_runs_the_target_again(self):  # R3-type-checker-cache-key-version
        self.with_python()
        (self.tmp / "checker.version").write_text("stub 1.0\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(0))}):
            first = self.target("py_type_test", use_cache=True)
            second = self.target("py_type_test", use_cache=True)
            (self.tmp / "checker.version").write_text("stub 2.0\n", encoding="utf-8")
            third = self.target("py_type_test", use_cache=True)
        self.assertEqual([first["cached"], second["cached"], third["cached"]], [False, True, False])


class PyTestTests(KitCase):
    def test_no_declared_module_is_a_skip(self):
        self.add_skill()
        result = self.target("py_test")
        self.assertEqual((result["status"], result["reason"]), ("SKIP", "no unittest module declared"))

    def test_the_declared_modules_run_and_their_exit_code_decides(self):
        self.add_skill(build={**all_targets(), "py_test": self.add_counting_tests()})
        passed = self.target("py_test")
        self.assertEqual(passed["status"], "PASS", passed)
        self.assertIn("1 test", passed["reason"])
        self.assertEqual(self.runs(), 1)
        (self.root / "fail.flag").write_text("", encoding="utf-8")
        failed = self.target("py_test")
        self.assertEqual(failed["status"], "FAIL", failed)
        self.assertIn("FAILED", failed["reason"])
        self.assertEqual(list(self.root.rglob("__pycache__")), [])


class EvalSuiteTests(KitCase):
    def add_case(self, name: str, case: dict, prompt="Do the demo.\n") -> Path:
        folder = self.root / "08-benchmark" / "evals" / "demo" / name
        folder.mkdir(parents=True)
        (folder / "case.json").write_text(json.dumps(case), encoding="utf-8")
        (folder / "prompt.md").write_text(prompt, encoding="utf-8")
        return folder

    def test_a_skill_with_no_case_is_a_skip(self):
        self.add_skill()
        result = self.target("eval_suite")
        self.assertEqual((result["status"], result["reason"]), ("SKIP", "no eval case yet"))

    @unittest.skipUnless(CASE_VALIDATOR.is_file(), "kit only: the instance does not carry 08-benchmark/")
    def test_every_case_is_validated_and_a_named_file_that_is_missing_fails(self):
        self.add_skill()
        good = {"schema_version": 1, "skill": "demo", "tier": "smoke", "expected_skills": ["demo"]}
        self.add_case("smoke-basic", good)
        passed = self.target("eval_suite")
        self.assertEqual(passed["status"], "PASS", passed)
        self.assertIn("1 case", passed["reason"])
        self.add_case("smoke-broken", {**good, "validators": ["validators/check.py"], "colour": "red"})
        failed = self.target("eval_suite")
        self.assertEqual(failed["status"], "FAIL", failed)
        self.assertIn("2 problems", failed["reason"])
        self.assertIn("smoke-broken", failed["reason"])


class CacheTests(KitCase):
    def setUp(self):
        super().setUp()
        self.add_skill(build={**all_targets(), "py_test": self.add_counting_tests()})

    def stored(self) -> list[str]:
        return sorted(p.name for p in self.kit.cache.rglob("*") if p.is_file())

    def test_the_cache_lives_under_the_tools_out_folder(self):
        self.assertTrue(str(self.kit.cache).startswith(str(self.root / "03-tools" / "out") + os.sep))

    def test_a_pass_is_stored_and_not_run_again(self):
        first = self.target("py_test", use_cache=True)
        second = self.target("py_test", use_cache=True)
        self.assertEqual((first["status"], first["cached"]), ("PASS", False))
        self.assertEqual((second["status"], second["cached"]), ("PASS", True))
        self.assertEqual(self.runs(), 1)

    def test_a_changed_input_runs_the_target_again(self):
        self.target("py_test", use_cache=True)
        with open(self.root / "pkg" / "tests" / "test_count.py", "a", encoding="utf-8") as source:
            source.write("# changed\n")
        self.assertIs(self.target("py_test", use_cache=True)["cached"], False)
        self.assertEqual(self.runs(), 2)
        with open(self.root / "02-skills" / "demo" / "SKILL.md", "a", encoding="utf-8") as source:
            source.write("One more line.\n")
        self.assertIs(self.target("py_test", use_cache=True)["cached"], False)
        self.assertEqual(self.runs(), 3)
        self.assertIs(self.target("py_test", use_cache=True)["cached"], True)
        self.assertEqual(self.runs(), 3)

    def test_the_runner_version_is_part_of_the_hash(self):
        self.target("py_test", use_cache=True)
        with mock.patch.object(skill_build, "RUNNER_VERSION", skill_build.RUNNER_VERSION + 1):
            self.assertIs(self.target("py_test", use_cache=True)["cached"], False)
        self.assertEqual(self.runs(), 2)

    def test_a_skip_and_a_fail_never_enter_the_cache(self):
        (self.root / "fail.flag").write_text("", encoding="utf-8")
        for _ in range(2):
            results = {r["target"]: r for r in skill_build.run_skill(self.kit, "demo", use_cache=True)}
            self.assertEqual(results["py_test"]["status"], "FAIL")
            self.assertEqual(results["py_type_test"]["status"], "SKIP")
            self.assertEqual(results["eval_suite"]["status"], "SKIP")
            self.assertIs(results["py_type_test"]["cached"], False)
        self.assertEqual(self.runs(), 2)
        self.assertEqual(self.stored(), ["demo.agent_skill.json", "demo.validate_skill_test.json"])

    def test_no_cache_runs_everything_and_stores_nothing(self):
        self.assertEqual(self.cli("test", "demo", "--no-cache")[0], 0)
        self.assertEqual(self.stored(), [])
        self.cli("test", "demo")
        code, out, _err = self.cli("test", "demo")
        self.assertEqual(code, 0)
        self.assertIn("PASS demo:py_test cached", out)
        self.assertEqual(self.runs(), 2)
        code, out, _err = self.cli("test", "demo", "--no-cache")
        self.assertNotIn("cached", out)
        self.assertEqual(self.runs(), 3)


class CommandTests(KitCase):
    def test_test_prints_one_line_per_target_and_exits_0_without_a_fail(self):
        self.add_skill()
        code, out, _err = self.cli("test", "demo", "--no-cache")
        lines = out.splitlines()
        self.assertEqual(code, 0, out)
        self.assertEqual([line.split()[1] for line in lines], [f"demo:{target}" for target in skill_build.TARGETS])
        for line in lines:
            self.assertRegex(line, LINE_RE)
        self.assertEqual([line.split()[0] for line in lines], ["PASS", "PASS", "SKIP", "SKIP", "SKIP"])
        self.assertIn("SKIP demo:py_type_test no Python in this skill", lines)

    def test_any_fail_exits_1_and_a_bad_declaration_is_fail_lines(self):
        self.add_skill("wrong", md=skill_md("other-name"))
        self.add_skill("broken", build={**all_targets(), "lint_test": {}})
        code, out, _err = self.cli("test", "wrong", "--no-cache")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL wrong:validate_skill_test", out)
        code, out, _err = self.cli("test", "broken", "--no-cache")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.splitlines(), ["FAIL broken:BUILD unknown key 'lint_test'"])

    def test_a_skill_with_no_build_file_is_one_skip_line(self):
        self.add_skill(build=False)
        for command in ("test", "build"):
            with self.subTest(command=command):
                code, out, _err = self.cli(command, "demo")
                self.assertEqual((code, out.splitlines()), (0, ["SKIP demo:BUILD no BUILD.json"]))

    def test_all_covers_every_skill_folder_in_order(self):
        self.add_skill("beta", md=skill_md("beta"))
        self.add_skill("alpha", build=False, md=skill_md("alpha"))
        (self.root / "02-skills" / "not-a-skill").mkdir()
        code, out, _err = self.cli("test", "--all", "--no-cache")
        self.assertEqual(code, 0, out)
        self.assertEqual([line.split()[1].split(":")[0] for line in out.splitlines()], ["alpha"] + ["beta"] * 5)

    def test_json_reports_every_result_and_a_skip_is_not_a_pass(self):
        self.add_skill()
        report = self.tmp / "report.json"
        code, out, err = self.cli("test", "demo", "--no-cache", "--json", str(report))
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(data["counts"], {"PASS": 2, "FAIL": 0, "SKIP": 3})
        self.assertEqual([(r["skill"], r["target"], r["status"]) for r in data["results"]],
                         [("demo", line.split()[1].split(":")[1], line.split()[0]) for line in out.splitlines()])
        self.assertEqual(set(data["results"][0]), {"skill", "target", "status", "reason", "cached"})
        self.assertIn("2 PASS", err)
        self.assertIn("3 SKIP", err)

    def test_build_writes_the_zip_under_the_out_folder_and_prints_its_hash(self):
        self.add_skill()
        self.add_skill("notarget", build={"validate_skill_test": {}}, md=skill_md("notarget"))
        self.add_skill("bad", build=all_targets(deps=[]), md=skill_md("bad"))
        out_dir = self.tmp / "dist"
        code, out, _err = self.cli("build", "demo", "notarget", "--out", str(out_dir))
        package = out_dir / "demo" / "demo-1.2.0.zip"
        self.assertEqual(code, 0, out)
        self.assertTrue(zipfile.is_zipfile(package))
        self.assertEqual(out.splitlines(), [f"PASS demo:agent_skill {package} sha256:{sha256(package)}",
                                            "SKIP notarget:agent_skill not declared"])
        code, out, _err = self.cli("build", "bad", "--out", str(out_dir))
        self.assertEqual(code, 1, out)
        self.assertTrue(out.startswith("FAIL bad:agent_skill "), out)
        self.assertFalse((out_dir / "bad").exists())

    def test_a_usage_error_is_exit_2_with_one_line_and_no_traceback(self):
        self.add_skill()
        blocked = self.tmp / "blocked"
        blocked.write_text("a file, not a folder", encoding="utf-8")
        for argv in ([], ["test"], ["test", "nope"], ["test", "demo", "--all"], ["test", "demo", "--fast"],
                     ["run", "demo"], ["test", "../demo"], ["build", "demo", "--no-cache"],
                     ["test", "demo", "--no-cache", "--json", str(blocked / "report.json")],
                     ["build", "demo", "--out", str(blocked)]):
            with self.subTest(argv=argv):
                code, out, err = self.cli(*argv)
                self.assertEqual(code, 2, (out, err))
                self.assertEqual(len(err.splitlines()), 1, err)
                self.assertTrue(err.startswith("skill-build: "), err)
                self.assertNotIn("Traceback", err)


class NestedSrcTests(KitCase):
    def test_a_src_in_a_subfolder_is_a_problem_that_names_the_installers(self):
        self.add_skill(build=all_targets(srcs=["SKILL.md", "refs/guide.md"]), files={"refs/guide.md": "guide\n"})
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("'refs/guide.md'", problems[0])
        self.assertIn("the installers copy only the top-level files of a skill", problems[0])
        code, out, _err = self.cli("test", "demo")
        self.assertEqual(code, 1)
        self.assertIn("FAIL demo:BUILD ", out)

    def test_a_top_level_src_is_still_a_valid_declaration(self):  # previous behavior of srcs
        self.add_skill(build=all_targets(srcs=["SKILL.md", "guide.md"]), files={"guide.md": "guide\n"})
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.target("agent_skill")["status"], "PASS")


class ReviewFindingTests(KitCase):
    """The findings the native review of this module left (feature skill-evals, L10)."""

    def add_case(self, name="smoke-basic") -> None:
        folder = self.root / "08-benchmark" / "evals" / "demo" / name
        folder.mkdir(parents=True)
        case = {"schema_version": 1, "skill": "demo", "tier": "smoke", "expected_skills": ["demo"]}
        (folder / "case.json").write_text(json.dumps(case), encoding="utf-8")
        (folder / "prompt.md").write_text("Do the demo.\n", encoding="utf-8")

    def plant_validator(self, source: str) -> None:
        """The kit's own case validator, which the executor prefers over the one beside this file."""
        lib = self.root / "08-benchmark" / "lib"
        shutil.rmtree(lib, ignore_errors=True)
        lib.mkdir(parents=True)
        (lib / "skill_eval.py").write_text(source, encoding="utf-8")

    def test_a_case_validator_that_raises_is_a_fail_line_not_a_traceback(self):  # R3-eval-validator-exception-traceback
        self.add_skill()
        self.add_case()
        for source, said in (("def validate_case(case_dir):\n    raise RuntimeError('boom in the validator')\n", "boom in the validator"),
                             ("def validate_case(:\n", "cannot be imported")):
            with self.subTest(said=said):
                self.plant_validator(source)
                result = self.target("eval_suite")
                self.assertEqual(result["status"], "FAIL", result)
                self.assertIn(said, result["reason"])
        code, out, err = self.cli("test", "demo", "--no-cache")
        self.assertEqual(code, 1, out + err)
        self.assertNotIn("Traceback", out + err)

    def test_a_case_validator_that_answers_still_decides(self):  # previous behavior of eval_suite
        self.add_skill()
        self.add_case()
        self.plant_validator("def validate_case(case_dir):\n    return []\n")
        self.assertEqual(self.target("eval_suite")["reason"], "1 case valid")
        self.plant_validator("def validate_case(case_dir):\n    return ['prompt.md is missing']\n")
        failed = self.target("eval_suite")
        self.assertEqual(failed["status"], "FAIL", failed)
        self.assertIn("prompt.md is missing", failed["reason"])

    def test_a_py_test_that_declares_no_input_is_never_taken_from_the_cache(self):  # R3-py-test-cache-ignores-undeclared-inputs
        declared = self.add_counting_tests()
        declared.pop("inputs")
        self.add_skill(build={**all_targets(), "py_test": declared})
        first = self.target("py_test", use_cache=True)
        second = self.target("py_test", use_cache=True)
        self.assertEqual((first["status"], second["status"], second["cached"]), ("PASS", "PASS", False))
        self.assertEqual(self.runs(), 2)
        self.assertIn("not cached", second["reason"])

    def test_the_declared_test_modules_are_always_part_of_the_hash(self):  # R3-py-test-cache-ignores-undeclared-inputs
        declared = self.add_counting_tests()
        (self.root / "pkg" / "notes.txt").write_text("read by the tests\n", encoding="utf-8")
        declared["inputs"] = ["pkg/notes.txt"]  # the test file itself is not listed
        self.add_skill(build={**all_targets(), "py_test": declared})
        self.target("py_test", use_cache=True)
        with open(self.root / "pkg" / "tests" / "test_count.py", "a", encoding="utf-8") as source:
            source.write("# changed\n")
        self.assertIs(self.target("py_test", use_cache=True)["cached"], False)
        self.assertEqual(self.runs(), 2)
        self.assertIs(self.target("py_test", use_cache=True)["cached"], True)  # previous behavior of the cache
        self.assertEqual(self.runs(), 2)

    def front_matter(self, description: str) -> str:
        return (f"---\nname: demo\ndescription: {description}\nversion: 1.2.0\n"
                f"allowed-tools: [Read, {DEMO_TOOL}]\n---\n\nBody.\n")

    def test_a_block_scalar_is_read_as_its_text(self):  # R3-front-matter-block-scalar-literal
        folder = self.add_skill(md=self.front_matter("|\n  Does a demo thing: twice.\n  Second line.\nfolded: >-\n  one\n  two"))
        fields, problems = skill_build.read_front_matter(folder / "SKILL.md")
        self.assertEqual(fields["description"], "Does a demo thing: twice.\nSecond line.")
        self.assertEqual(fields["folded"], "one two")
        self.assertEqual(fields["version"], "1.2.0")
        self.assertEqual(problems, [])
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "out")) as package:
            plugin = json.loads(package.read(".claude-plugin/plugin.json"))
        self.assertEqual(plugin["description"], "Does a demo thing: twice.\nSecond line.")

    def test_a_block_scalar_indicator_with_no_text_is_an_empty_value(self):  # R2-block-scalar-indicator-as-value
        self.add_skill(md=self.front_matter(">"))
        result = self.target("validate_skill_test")
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("description is empty or missing", result["reason"])
        self.assertEqual(self.target("agent_skill")["status"], "FAIL")

    def test_one_function_names_the_package_file(self):  # R2-build-skill-duplicates-package-path
        self.add_skill()
        expected = skill_build.package_path(self.tmp / "out", "demo", "1.2.0")
        self.assertEqual(expected, self.tmp / "out" / "demo" / "demo-1.2.0.zip")
        self.assertEqual(skill_build.build_package(self.kit, "demo", self.tmp / "out"), expected)
        result = skill_build.build_skill(self.kit, "demo", self.tmp / "out")[0]
        self.assertTrue(result["reason"].startswith(f"{expected} sha256:"), result)

    def test_the_two_package_steps_have_names_that_cannot_be_swapped(self):  # R2-plan-package-vs-package-plan
        self.assertFalse(hasattr(skill_build, "_plan_package") or hasattr(skill_build, "_package_plan"))
        self.add_skill(build=False)
        with self.assertRaises(skill_build.BuildError) as caught:
            skill_build._require_package(self.kit, "demo")
        self.assertEqual(str(caught.exception), "demo: no BUILD.json")
        self.write_build("demo", {"schema_version": 1, **all_targets()})
        declared = skill_build.load_build(self.kit, "demo")[0]["agent_skill"]
        plan, problems = skill_build._inspect_package(self.kit, "demo", declared)
        self.assertEqual((plan["name"], problems), ("demo", []))
        self.assertEqual(skill_build._require_package(self.kit, "demo")["entries"], plan["entries"])

    def test_a_build_file_that_cannot_be_read_is_not_called_invalid_json(self):  # R2-load-build-misleading-error
        folder = self.add_skill(build=False)
        (folder / "BUILD.json").mkdir()
        self.assertEqual(len(self.problems()), 1, self.problems())
        self.assertIn("cannot be read", self.problems()[0])
        self.assertNotIn("not valid JSON", self.problems()[0])
        (folder / "BUILD.json").rmdir()
        (folder / "BUILD.json").write_bytes(b"\xff\xfe{")
        self.assertIn("is not UTF-8 text", self.problems()[0])
        self.write_build("demo", "{not json")
        self.assertIn("is not valid JSON", self.problems()[0])  # previous behavior


class LayoutForARunTests(KitCase):
    """What the eval runner asks of the layout: the server's tools under the names a plugin gives them."""

    def test_the_local_layout_names_the_mcp_tools_as_the_plugin_exposes_them(self):
        self.add_skill(md=skill_md(body=f"Call `{DEMO_TOOL}` first.\n"))
        exposed = "mcp__plugin_demo_metodo__demo_tool"
        self.assertEqual(skill_build.plugin_tool_name("demo", DEMO_TOOL), exposed)
        laid = skill_build.layout_plugin(self.kit, "demo", self.tmp / "local", local_mcp=True)
        text = (self.tmp / "local" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(laid["mcp_tools"], [exposed])
        self.assertEqual(text.count(exposed), 2)  # the allowed-tools line and the body
        self.assertNotIn(DEMO_TOOL, text)
        plain = skill_build.layout_plugin(self.kit, "demo", self.tmp / "plain")  # previous behavior: the package's bytes
        self.assertEqual(plain["mcp_tools"], [])
        self.assertIn(DEMO_TOOL, (self.tmp / "plain" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8"))

    def test_the_tools_root_can_be_rendered_without_starting_a_server(self):
        body = 'Run `POST="${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/post.py"`.\n'
        self.add_skill(build=all_targets(deps=[DEMO_TOOL, "03-tools"]), md=skill_md(body=body))
        laid = skill_build.layout_plugin(self.kit, "demo", self.tmp / "rendered", render_tools=True)
        text = (self.tmp / "rendered" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"${{METODO_TOOLS:-{self.root / '03-tools'}}}/lib/post.py", text)
        self.assertNotIn(".mcp.json", laid["files"])
        self.assertIn(DEMO_TOOL, text)
        self.assertEqual((laid["rendered_tools"], laid["local_mcp"]), (True, False))


@unittest.skipUnless((KIT_ROOT / "02-skills").is_dir(), "kit only: the instance does not carry 02-skills/")
class RealKitTests(unittest.TestCase):
    """The declarations the kit ships, and the wrapper, on this checkout; nothing is written to it."""

    def test_the_catalog_of_the_kit_is_read(self):
        names, error = skill_build.Kit(KIT_ROOT).catalog()
        self.assertIsNone(error)
        self.assertIn("change_card_validate", names)

    def test_every_shipped_build_file_is_a_valid_declaration(self):
        kit = skill_build.Kit(KIT_ROOT)
        shipped = sorted(p.parent.name for p in (KIT_ROOT / "02-skills").glob("*/BUILD.json"))
        self.assertIn("change-card", shipped)
        self.assertIn("harness-benchmark", shipped)
        for skill in shipped:
            with self.subTest(skill=skill):
                self.assertEqual(skill_build.load_build(kit, skill)[1], [])

    def test_every_skill_of_the_kit_declares_the_same_five_targets(self):  # S12: a BUILD per skill
        kit = skill_build.Kit(KIT_ROOT)
        skills = sorted(p.parent.name for p in (KIT_ROOT / "02-skills").glob("*/SKILL.md"))
        self.assertGreaterEqual(len(skills), 17)
        for skill in skills:
            with self.subTest(skill=skill):
                build, problems = skill_build.load_build(kit, skill)
                self.assertEqual(problems, [])
                self.assertEqual(tuple(build), skill_build.TARGETS)

    def test_the_wrapper_tests_a_shipped_skill_under_an_isolated_python(self):
        proc = subprocess.run(["bash", str(WRAPPER), "test", "change-card", "--no-cache"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), len(skill_build.TARGETS), proc.stdout)
        self.assertIn("PASS change-card:agent_skill", proc.stdout)
        self.assertNotIn("FAIL", proc.stdout)
        self.assertIn("python3 -I", WRAPPER.read_text(encoding="utf-8"))

    def test_the_wrapper_reports_a_usage_error_in_one_line(self):
        proc = subprocess.run(["bash", str(WRAPPER), "test", "no-such-skill"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
        self.assertTrue(proc.stderr.startswith("skill-build: "), proc.stderr)


if __name__ == "__main__":
    unittest.main()
