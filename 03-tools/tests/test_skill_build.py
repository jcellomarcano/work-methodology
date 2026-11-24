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
        # The kit-level declaration: its owner is the author of every package.
        (self.root / "02-skills" / "BUILD.json").write_text(json.dumps({"schema_version": 1, "kit_plugin": KIT_DECL}),
                                                            encoding="utf-8")
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

    def test_a_package_without_the_owner_of_the_kit_level_declaration_fails_and_says_so(self):  # A5
        self.add_skill()
        kit_build = self.root / "02-skills" / "BUILD.json"
        only_owner = {"schema_version": 1, "kit_plugin": {"owner": "Someone Else"}}
        kit_build.write_text(json.dumps(only_owner), encoding="utf-8")  # the author needs nothing else of it
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "out")) as package:
            self.assertEqual(json.loads(package.read(".claude-plugin/plugin.json"))["author"], {"name": "Someone Else"})
        for text, said in ((None, "02-skills/BUILD.json cannot be read"),
                           ("{not json", "02-skills/BUILD.json is not valid JSON"),
                           (json.dumps({"schema_version": 1, "kit_plugin": {"owner": " "}}),
                            "02-skills/BUILD.json: kit_plugin.owner must be a non-empty string, got ' '")):
            with self.subTest(said):
                kit_build.unlink() if text is None else kit_build.write_text(text, encoding="utf-8")
                result = self.target("agent_skill")
                self.assertEqual(result["status"], "FAIL", result)
                self.assertIn(f"no author for the package: {said}", result["reason"])
                self.assertEqual(len(result["reason"].splitlines()), 1, result)
                with self.assertRaises(skill_build.BuildError) as raised:
                    skill_build.build_package(self.kit, "demo", self.tmp / "out")
                self.assertIn("no author for the package", str(raised.exception))
                kit_build.write_text(json.dumps(only_owner), encoding="utf-8")

    def test_a_stored_pass_does_not_outlive_a_change_of_the_owner(self):  # A5: the author is an input of the target
        self.add_skill()
        self.assertFalse(self.target("agent_skill", use_cache=True)["cached"])
        self.assertTrue(self.target("agent_skill", use_cache=True)["cached"])  # previous behavior of the cache
        (self.root / "02-skills" / "BUILD.json").write_text(
            json.dumps({"schema_version": 1, "kit_plugin": {**KIT_DECL, "owner": "Someone Else"}}), encoding="utf-8")
        self.assertFalse(self.target("agent_skill", use_cache=True)["cached"])

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
        self.assertEqual(plugin, {"name": "demo", "version": "1.2.0", "description": "Does a demo thing.",
                                  "author": {"name": KIT_DECL["owner"]}})  # A5: the author the kit plugin uses
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
                self.assertEqual(os.path.basename(argv[-1]), "tool.py")  # pyright is given the full path
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

    def test_pyright_checks_the_skills_own_files_from_a_project_file_kept_outside_the_skill(self):  # R3-pyright-project-root-in-scratch
        self.with_python()
        folder = self.root / "02-skills" / "demo"
        with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.stub(0, name="pyright"))}):
            result = self.target("py_type_test")
        self.assertEqual(result["status"], "PASS", result)
        argv = (self.tmp / "checker.log").read_text(encoding="utf-8").split()
        project = json.loads((self.tmp / "project.json").read_text(encoding="utf-8"))
        # pyright takes the folder of its project file as the project root, and that folder is a
        # scratch one: the files are named by their full path and the imports are sent to the skill
        self.assertEqual(argv[-1], str(folder / "tool.py"))
        self.assertTrue(Path(argv[-1]).is_file(), argv)
        self.assertEqual(project["extraPaths"], [str(folder)])
        self.assertEqual(project["typeCheckingMode"], "strict")
        self.assertNotIn(str(folder), argv[argv.index("--project") + 1])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["BUILD.json", "SKILL.md", "tool.py"])

    def silent_stub(self, on_version: str) -> Path:
        """A checker that accepts the sources and does `on_version` when asked for its version."""
        path = self.tmp / "bin" / "mypy"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then {on_version}; fi\n'
                        f'echo "$@" >> "{self.tmp}/checker.log"\nexit 0\n', encoding="utf-8")
        os.chmod(path, 0o755)
        return path

    def test_a_checker_that_cannot_say_its_version_still_runs_and_its_pass_is_never_stored(self):  # R3-checker-version-failure-untested
        self.with_python()
        log = self.tmp / "checker.log"
        for said, on_version in (("exits 3", "echo broken >&2; exit 3"), ("says nothing", "exit 0")):
            with self.subTest(version=said):
                log.unlink(missing_ok=True)
                with mock.patch.dict(os.environ, {skill_build.CHECKER_ENV: str(self.silent_stub(on_version))}):
                    first = self.target("py_type_test", use_cache=True)
                    second = self.target("py_type_test", use_cache=True)
                self.assertEqual([first["status"], second["status"]], ["PASS", "PASS"], [first, second])
                self.assertEqual([first["cached"], second["cached"]], [False, False])
                self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 2)  # it ran both times
                self.assertEqual(sorted(self.kit.cache.glob("*py_type_test*")) if self.kit.cache.is_dir() else [], [])
        with mock.patch.object(skill_build.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["mypy", "--version"], 60)):
            with self.assertRaises(OSError):  # the one error the executor reads as "store nothing"
                skill_build._checker_version("mypy")


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

    def test_a_folded_block_scalar_keeps_its_paragraphs(self):  # R3-folded-block-scalar-drops-paragraphs
        folder = self.add_skill(md=self.front_matter(
            ">\n  First paragraph,\n  still the first.\n\n  Second paragraph.\n\n\n  Third, after two blank lines.\n"
            "one: >-\n  one\n  two\nkept: |\n  a\n\n  b"))
        fields, problems = skill_build.read_front_matter(folder / "SKILL.md")
        # YAML folding: a line break inside a paragraph is a space, a blank line is a line break
        self.assertEqual(fields["description"],
                         "First paragraph, still the first.\nSecond paragraph.\n\nThird, after two blank lines.")
        self.assertEqual(fields["one"], "one two")  # previous behavior: one paragraph is one line
        self.assertEqual(fields["kept"], "a\n\nb")  # previous behavior: a literal block keeps its lines
        self.assertEqual(fields["version"], "1.2.0")
        self.assertEqual(problems, [])

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

    def test_a_build_file_nested_past_the_json_reader_is_one_problem_line(self):
        # closing pass, 2026-11-24: json.loads raises RecursionError, not ValueError, on such a file
        self.add_skill(build=False)
        self.write_build("demo", "[" * 200000)
        self.assertEqual(len(self.problems()), 1, self.problems())
        self.assertIn("is not valid JSON", self.problems()[0])


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


KIT_DECL = {"name": "demo-kit", "version": "0.3.0", "description": "The demo kit as one plugin.",
            "marketplace": "demo-market", "owner": "Demo Owner"}
KIT_TOOL = "mcp__plugin_demo-kit_metodo__demo_tool"


class KitPluginCase(KitCase):
    """A kit with one declared skill, one skill without a BUILD file, the kit-level declaration
    (02-skills/BUILD.json) and a tools folder shaped like 03-tools, with its benchmark beside it."""

    def setUp(self):
        super().setUp()
        self.add_skill(md=skill_md(body=f"Call `{DEMO_TOOL}` first.\n"))
        self.add_skill("plain", build=False)
        self.declare()
        self.tool("mcp/server.py", "print('server')\n")
        self.tool("lib/helper.py", "VALUE = 1\n")
        self.tool("bin/run.sh", "#!/usr/bin/env bash\necho run\n", mode=0o755)
        self.tool("schemas/a.schema.json", "{}\n")
        self.tool("hooks/guard.py", "GUARD = 1\n")
        self.tool("config/project.json", "{}\n")
        self.write("08-benchmark/lib/bench.py", "BENCH = 1\n")

    def declare(self, **changes) -> None:
        data = {"schema_version": 1, "kit_plugin": {**KIT_DECL, **changes}}
        (self.root / "02-skills" / "BUILD.json").write_text(json.dumps(data), encoding="utf-8")

    def write(self, relative: str, text: str, mode=None) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode is not None:
            path.chmod(mode)
        return path

    def tool(self, relative: str, text: str, mode=None) -> Path:
        return self.write(f"03-tools/{relative}", text, mode)

    def plan(self) -> dict:
        plan, problems = skill_build.inspect_kit_plugin(self.kit)
        self.assertEqual(problems, [])
        return plan

    def problems(self) -> list[str]:  # of the kit plugin, not of one skill
        plan, problems = skill_build.inspect_kit_plugin(self.kit)
        self.assertIsNone(plan)
        return problems

    def held(self) -> dict:
        return dict(self.plan()["entries"])

    def build(self, out="dist") -> dict:
        return skill_build.build_kit_plugin(self.kit, self.tmp / out)


class KitPluginTests(KitPluginCase):
    def test_the_kit_declaration_names_the_plugin_and_a_bad_one_is_one_problem_line_each(self):
        declared, problems = skill_build.load_kit_build(self.kit)
        self.assertEqual((declared, problems), (KIT_DECL, []))
        self.declare(name="Demo Kit", surprise=1)
        declared, problems = skill_build.load_kit_build(self.kit)
        self.assertIsNone(declared)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("'surprise'" in line for line in problems), problems)
        self.assertTrue(any("kebab-case" in line and "'Demo Kit'" in line for line in problems), problems)
        self.declare(name="demo")  # the name of a skill: `demo:demo` would read as that skill's own package
        self.assertTrue(any("is the name of a skill" in line for line in skill_build.load_kit_build(self.kit)[1]))
        (self.root / "02-skills" / "BUILD.json").unlink()
        declared, problems = skill_build.load_kit_build(self.kit)
        self.assertIsNone(declared)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("02-skills/BUILD.json", problems[0])

    def test_it_holds_the_plugin_manifest_every_declared_skill_the_server_and_a_manifest_of_what_it_holds(self):
        plan = self.plan()
        held = dict(plan["entries"])
        for name in (".claude-plugin/plugin.json", ".mcp.json", "MANIFEST.json", "skills/demo/SKILL.md",
                     "tools/mcp/server.py", "tools/mcp/catalog.py", "tools/lib/helper.py"):
            self.assertIn(name, held)
        self.assertFalse([name for name in held if name.startswith("skills/plain/")])  # it has no BUILD file
        plugin = json.loads(held[".claude-plugin/plugin.json"])
        self.assertEqual(plugin, {"name": "demo-kit", "version": "0.3.0", "description": KIT_DECL["description"],
                                  "author": {"name": "Demo Owner"}})
        manifest = json.loads(held["MANIFEST.json"])
        self.assertEqual((manifest["kind"], manifest["name"], manifest["version"]), ("kit_plugin", "demo-kit", "0.3.0"))
        self.assertEqual(manifest["files"], sorted(name for name in held if name != "MANIFEST.json"))
        self.assertEqual(manifest["skills"], [{"name": "demo", "version": "1.2.0", "invoke": "demo-kit:demo",
                                               "files": ["SKILL.md"], "mcp_tools": [KIT_TOOL]}])
        self.assertEqual(manifest["skills_left_out"], [{"name": "plain", "why": "no BUILD.json"}])
        self.assertEqual(manifest["mcp_server"]["name"], "metodo")
        self.assertEqual(manifest["mcp_server"]["tool_prefix"], "mcp__plugin_demo-kit_metodo__")
        self.assertEqual(manifest["mcp_server"]["tools_root"], "tools")

    def test_the_skills_name_the_tools_as_this_plugin_exposes_them_in_the_text_and_in_allowed_tools(self):
        text = self.held()["skills/demo/SKILL.md"].decode("utf-8")
        self.assertIn(f"allowed-tools: [Read, {KIT_TOOL}]", text)
        self.assertIn(f"Call `{KIT_TOOL}` first.", text)
        self.assertNotIn("mcp__metodo__", text)
        # previous behavior: the package of the skill alone keeps the names as they are written
        with zipfile.ZipFile(skill_build.build_package(self.kit, "demo", self.tmp / "alone")) as package:
            self.assertIn(DEMO_TOOL, package.read("skills/demo/SKILL.md").decode("utf-8"))

    def test_the_server_config_uses_the_two_plugin_variables_and_no_absolute_path(self):
        raw = self.held()[".mcp.json"].decode("utf-8")
        server = json.loads(raw)["mcpServers"]["metodo"]
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["${CLAUDE_PLUGIN_ROOT}/tools/mcp/server.py"])
        self.assertEqual(server["env"]["METODO_TOOLS"], "${CLAUDE_PLUGIN_ROOT}/tools")
        self.assertEqual(server["env"]["METODO_REPO"], "${CLAUDE_PROJECT_DIR}")
        self.assertNotIn(str(self.root), raw)
        for value in [server["command"], *server["args"], *server["env"].values()]:
            self.assertFalse(value.startswith("/"), value)

    def test_the_tools_folder_is_taken_by_the_rule_of_sync_instance(self):
        self.tool("lib/nested/deep.py", "DEEP = 1\n")
        self.tool("README.md", "# not synced: only the listed folders are\n")
        self.write("08-benchmark/protocols/ab.md", "protocol\n")
        self.write("08-benchmark/evals/demo/case.json", "{}\n")  # the benchmark's lib, bin and protocols only
        tools = sorted(name for name in self.held() if name.startswith("tools/"))
        self.assertEqual(tools, [
            "tools/bench/lib/bench.py", "tools/bench/protocols/ab.md", "tools/bin/run.sh",
            "tools/config/project.json", "tools/hooks/guard.py", "tools/lib/helper.py", "tools/lib/nested/deep.py",
            "tools/mcp/__init__.py", "tools/mcp/catalog.py", "tools/mcp/server.py", "tools/schemas/a.schema.json"])
        self.assertEqual(self.plan()["modes"]["tools/bin/run.sh"] & 0o777, 0o755)  # a script stays runnable
        self.assertEqual(self.plan()["modes"]["tools/lib/helper.py"] & 0o777, 0o644)

    def test_it_never_holds_a_personal_asset_and_never_opens_one(self):
        secret = [self.tool("config/output-lint.personal.json", "{}\n"),
                  self.tool("lib/personal/notes.py", "NOTES = 1\n"),
                  self.write("08-benchmark/lib/calls.personal.py", "CALLS = 1\n")]
        for path in secret:
            path.chmod(0)  # a build that opened one would stop on it
            self.addCleanup(path.chmod, 0o600)
        names = list(self.held())
        self.assertFalse([name for name in names if ".personal." in name or "/personal/" in name], names)
        self.assertIn("tools/lib/helper.py", names)
        # a skill that lists one is refused by its path, before any of its files is read
        (self.root / "02-skills" / "demo" / "voice.personal.md").write_text("mine\n", encoding="utf-8")
        self.write_build("demo", {"schema_version": 1, **all_targets(srcs=["SKILL.md", "voice.personal.md"])})
        self.assertTrue(any("voice.personal.md" in line and "personal" in line for line in self.problems()))

    def test_it_never_holds_a_test(self):
        self.tool("tests/test_helper.py", "import unittest\n")
        self.tool("tests/fixtures/data.json", "{}\n")
        self.tool("lib/test_helper.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    pass\n")
        self.tool("lib/test_sectors.py", "SECTORS = 1  # a tool whose name starts with test_\n")
        self.write("08-benchmark/tests/test_bench.py", "import unittest\n")
        names = list(self.held())
        self.assertFalse([name for name in names if "/tests/" in name or name.endswith("test_helper.py")], names)
        self.assertIn("tools/lib/test_sectors.py", names)
        (self.root / "02-skills" / "demo" / "test_demo.py").write_text("import unittest\n", encoding="utf-8")
        self.write_build("demo", {"schema_version": 1, **all_targets(srcs=["SKILL.md", "test_demo.py"])})
        self.assertTrue(any("test_demo.py is a test" in line for line in self.problems()))

    def test_it_never_holds_a_build_file_a_cache_an_out_or_a_vendor_folder(self):
        for relative in ("lib/BUILD.json", "lib/__pycache__/helper.cpython-312.pyc", "lib/stale.pyc", "lib/.DS_Store",
                         "out/runs/runs.jsonl", "vendor/pmd/pmd.jar", "baselines/latest.json", "lib/out/kept.json",
                         "hooks/vendor/x.py"):
            self.tool(relative, "x\n")
        names = list(self.held())
        for part in ("BUILD.json", "__pycache__", ".pyc", ".DS_Store", "/out/", "/vendor/", "/baselines/"):
            self.assertFalse([name for name in names if part in name], (part, names))
        self.assertNotIn("skills/BUILD.json", names)
        self.assertNotIn("skills/demo/BUILD.json", names)

    def test_a_text_file_holding_the_home_path_of_this_machine_fails_the_target(self):
        home = os.path.expanduser("~")
        self.assertFalse(any(home.encode() in data for data in self.held().values()))
        self.tool("config/where.json", json.dumps({"instance": f"{home}/my-tools"}) + "\n")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("tools/config/where.json", problems[0])
        self.assertIn("home path", problems[0])
        self.assertNotIn(home, problems[0])  # the report does not repeat it

    def test_a_longer_path_or_a_word_that_only_contains_the_home_path_is_not_the_home_path(self):  # R3-home-path-substring-false-positive
        home = os.path.expanduser("~")
        self.tool("config/where.json", json.dumps({"sibling": f"{home}-backup/my-tools", "word": f"{home}2",
                                                   "longer": f"/mnt/snapshots{home}/my-tools"}) + "\n")
        self.assertIn("tools/config/where.json", self.held())  # packed: none of the three is this machine's home
        for text in (home, f"{home}/my-tools", f'"{home}"', f"file://{home}/x", f"see {home}.", f"A={home}:{home}/bin"):
            with self.subTest(text=text.replace(home, "HOME")):  # previous behavior: the home path itself still fails
                self.tool("config/where.json", text + "\n")
                problems = self.problems()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("home path", problems[0])

    def test_the_zip_is_byte_identical_for_identical_inputs(self):
        first, second = self.build("one"), self.build("two")
        self.assertEqual(first["zip"].name, "demo-kit-0.3.0.zip")
        self.assertEqual(first["zip"].parent, self.tmp / "one" / "demo-kit")
        self.assertEqual(sha256(first["zip"]), sha256(second["zip"]))
        self.assertEqual(first["sha256"], sha256(first["zip"]))
        os.utime(self.root / "03-tools" / "lib" / "helper.py", (1, 1))  # a date is not an input
        self.assertEqual(sha256(self.build("three")["zip"]), first["sha256"])
        with zipfile.ZipFile(first["zip"]) as package:
            self.assertEqual(package.namelist(), sorted(package.namelist()))
            self.assertEqual({info.date_time for info in package.infolist()}, {(1980, 1, 1, 0, 0, 0)})
            self.assertEqual(sorted(package.namelist()), sorted(self.held()))
        self.tool("lib/helper.py", "VALUE = 2\n")
        self.assertNotEqual(sha256(self.build("four")["zip"]), first["sha256"])

    def test_a_skill_that_names_a_tool_the_catalog_lacks_fails_the_target(self):
        ghost = "mcp__metodo__ghost_tool"
        self.add_skill("declares", build=all_targets(deps=[ghost]), md=skill_md("declares", tools=("Read", ghost)))
        self.assertTrue(any(line.startswith("declares: ") and f"{ghost} is not in the MCP catalog" in line
                            for line in self.problems()))
        shutil.rmtree(self.root / "02-skills" / "declares")
        self.add_skill("mentions", md=skill_md("mentions", body=f"Then call `{ghost}`.\n"))  # only in its text
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("mentions: SKILL.md names mcp__metodo__ghost_tool, which is not in the MCP catalog", problems[0])
        self.assertEqual(self.cli("build", "--kit-plugin", "--out", str(self.tmp / "dist"))[0], 1)

    def test_an_empty_catalog_lacks_every_tool_a_skill_mentions(self):
        (self.root / "03-tools" / "mcp" / "catalog.py").write_text("BY_NAME = {}\n", encoding="utf-8")
        self.kit = skill_build.Kit(self.root)  # a Kit reads its catalog once
        self.write_build("demo", {"schema_version": 1, **all_targets(deps=[])})
        (self.root / "02-skills" / "demo" / "SKILL.md").write_text(
            skill_md(tools=("Read",), body=f"Call `{DEMO_TOOL}` first.\n"), encoding="utf-8")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("demo: SKILL.md names mcp__metodo__demo_tool, which is not in the MCP catalog", problems[0])

    def test_a_marketplace_folder_that_is_a_link_is_never_written_through(self):
        elsewhere = self.tmp / "elsewhere"
        (elsewhere / ".claude-plugin").mkdir(parents=True)
        (elsewhere / ".claude-plugin" / "marketplace.json").write_text("{}\n", encoding="utf-8")
        link = self.tmp / "linked" / "demo-kit" / "marketplace"
        link.parent.mkdir(parents=True)
        link.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(skill_build.BuildError):
            self.build("linked")
        self.assertEqual((elsewhere / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"), "{}\n")
        self.assertFalse((elsewhere / "plugins").exists())

    def test_a_packed_skill_that_still_says_the_bare_server_prefix_fails_the_target(self):
        self.assertEqual(skill_build.expose_tools(f"x {DEMO_TOOL} y".encode(), "demo-kit"), f"x {KIT_TOOL} y".encode())
        with mock.patch.object(skill_build, "expose_tools", lambda data, plugin: data):  # a rewrite that missed one
            problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("demo: SKILL.md still says mcp__metodo__", problems[0])

    def test_the_tools_root_a_skill_names_is_the_tools_folder_of_the_plugin(self):
        body = 'Run `POST="${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/post.py"`.\n'
        self.add_skill("poster", build=all_targets(deps=[DEMO_TOOL, "03-tools"]), md=skill_md("poster", body=body))
        text = self.held()["skills/poster/SKILL.md"].decode("utf-8")
        self.assertIn('${METODO_TOOLS:-${CLAUDE_PLUGIN_ROOT}/tools}/lib/post.py', text)
        self.assertNotIn("__TOOLS_DEFAULT__", text)

    def test_the_manifest_says_where_the_server_writes_and_that_no_setting_moves_it(self):
        manifest = json.loads(self.held()["MANIFEST.json"])
        writes = manifest["mcp_server"]["writes"]
        self.assertEqual(writes["folder"], "tools/out")
        self.assertIsNone(writes["setting"])
        self.assertFalse(writes["survives_a_plugin_update"])
        self.assertEqual(writes["settings_of_a_part"], ["METODO_HOOKS_DIR", "METODO_RDD_DIR", "METODO_RUNS_DIR"])
        self.assertTrue(any("tools/out" in limit for limit in manifest["limits"]), manifest["limits"])
        self.assertTrue(any("hooks" in limit and "role" in limit for limit in manifest["limits"]), manifest["limits"])

    def test_a_marketplace_folder_listing_this_one_plugin_is_written_beside_the_zip(self):
        built = self.build()
        self.assertEqual(built["marketplace"], built["zip"].parent / "marketplace")
        listing = json.loads((built["marketplace"] / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual((listing["name"], listing["owner"]), ("demo-market", {"name": "Demo Owner"}))
        self.assertEqual(listing["description"], KIT_DECL["description"])  # without one, a strict validation warns
        self.assertEqual(listing["plugins"], [{"name": "demo-kit", "source": "./plugins/demo-kit", "version": "0.3.0",
                                               "description": KIT_DECL["description"]}])
        folder = built["marketplace"] / "plugins" / "demo-kit"
        self.assertEqual(built["plugin_dir"], folder)
        on_disk = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
        with zipfile.ZipFile(built["zip"]) as package:
            self.assertEqual(on_disk, {name: package.read(name) for name in package.namelist()})
        self.assertTrue(os.access(folder / "tools" / "bin" / "run.sh", os.X_OK))
        self.tool("lib/helper.py", "VALUE = 2\n")
        (self.root / "03-tools" / "hooks" / "guard.py").unlink()
        again = self.build()  # a second build replaces the folder: nothing of the first one is left behind
        self.assertFalse((again["plugin_dir"] / "tools" / "hooks" / "guard.py").exists())
        self.assertEqual((again["plugin_dir"] / "tools" / "lib" / "helper.py").read_text(encoding="utf-8"), "VALUE = 2\n")
        stranger = self.tmp / "taken" / "demo-kit" / "marketplace"
        stranger.mkdir(parents=True)
        (stranger / "mine.txt").write_text("not a marketplace this command wrote\n", encoding="utf-8")
        with self.assertRaises(skill_build.BuildError):
            self.build("taken")
        self.assertTrue((stranger / "mine.txt").exists())

    def test_the_layout_for_a_run_is_the_plugin_folder_and_says_how_each_skill_is_invoked(self):
        laid = skill_build.layout_kit_plugin(self.kit, self.tmp / "laid")
        self.assertEqual((laid["name"], laid["version"], laid["plugin_dir"]), ("demo-kit", "0.3.0", str(self.tmp / "laid")))
        self.assertEqual(laid["tool_prefix"], "mcp__plugin_demo-kit_metodo__")
        self.assertEqual(laid["skills"], {"demo": {"invoke": "demo-kit:demo", "mcp_tools": [KIT_TOOL]}})
        self.assertEqual(sorted(laid["files"]), sorted(self.held()))
        self.assertTrue((self.tmp / "laid" / ".mcp.json").is_file())
        with self.assertRaises(skill_build.BuildError):
            skill_build.layout_kit_plugin(self.kit, self.tmp / "laid")  # a folder of its own, as for a skill


class KitPluginCommandTests(KitPluginCase):
    def test_build_takes_one_more_option_and_prints_the_zip_and_its_hash(self):
        out = self.tmp / "dist"
        code, stdout, stderr = self.cli("build", "--kit-plugin", "--out", str(out))
        self.assertEqual(code, 0, stdout + stderr)
        lines = stdout.splitlines()
        self.assertEqual(len(lines), 1, stdout)
        self.assertRegex(lines[0], LINE_RE)
        package = out / "demo-kit" / "demo-kit-0.3.0.zip"
        self.assertEqual(lines[0], f"PASS demo-kit:kit_plugin {package} sha256:{sha256(package)}")
        self.assertIn("1 PASS", stderr)
        code, stdout, _stderr = self.cli("build", "demo", "--kit-plugin", "--out", str(out))  # with a skill: both
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[1] for line in stdout.splitlines()], ["demo:agent_skill", "demo-kit:kit_plugin"])

    def test_test_checks_the_kit_plugin_and_writes_nothing(self):
        code, stdout, stderr = self.cli("test", "--kit-plugin")
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(len(stdout.splitlines()), 1, stdout)
        self.assertRegex(stdout.splitlines()[0], LINE_RE)
        self.assertIn("PASS demo-kit:kit_plugin packs 1 skill", stdout)
        self.assertIn("1 left out", stdout)
        self.assertFalse((self.root / "03-tools" / "out").exists())

    def test_a_kit_plugin_that_cannot_be_packed_is_fail_lines_and_exit_1(self):
        self.tool("lib/where.py", f"HOME = '{os.path.expanduser('~')}'\n")
        code, stdout, stderr = self.cli("build", "--kit-plugin", "--out", str(self.tmp / "dist"))
        self.assertEqual(code, 1, stdout + stderr)
        self.assertRegex(stdout.splitlines()[0], LINE_RE)
        self.assertTrue(stdout.startswith("FAIL demo-kit:kit_plugin tools/lib/where.py"), stdout)
        self.assertFalse((self.tmp / "dist").exists())
        (self.root / "02-skills" / "BUILD.json").unlink()
        code, stdout, _stderr = self.cli("test", "--kit-plugin")
        self.assertEqual(code, 1)
        self.assertTrue(stdout.startswith("FAIL kit:kit_plugin 02-skills/BUILD.json"), stdout)

    def test_a_marketplace_folder_the_build_cannot_replace_is_a_fail_line_and_exit_1(self):  # R3-kit-plugin-builderror-escapes-cli
        out = self.tmp / "dist"
        market = out / "demo-kit" / "marketplace"
        market.mkdir(parents=True)
        (market / "mine.txt").write_text("not written by the build\n", encoding="utf-8")
        code, stdout, stderr = self.cli("build", "demo", "--kit-plugin", "--out", str(out))
        self.assertEqual(code, 1, stdout + stderr)
        lines = stdout.splitlines()
        # the skill packed before it keeps its line: the kit plugin's error is one more result, not the end of the command
        self.assertEqual([line.split()[:2] for line in lines], [["PASS", "demo:agent_skill"], ["FAIL", "demo-kit:kit_plugin"]])
        for line in lines:
            self.assertRegex(line, LINE_RE)
        self.assertIn("holds something this command did not write", lines[1])
        self.assertIn("1 PASS", stderr)
        self.assertIn("1 FAIL", stderr)
        self.assertNotIn("Traceback", stdout + stderr)
        self.assertEqual((market / "mine.txt").read_text(encoding="utf-8"), "not written by the build\n")
        self.assertFalse((out / "demo-kit" / "demo-kit-0.3.0.zip").exists())

    def test_without_the_option_the_command_is_what_it_was(self):  # previous behavior of build and test
        out = self.tmp / "dist"
        code, stdout, _stderr = self.cli("build", "--all", "--out", str(out))
        self.assertEqual(code, 0)
        self.assertNotIn("kit_plugin", stdout)
        self.assertTrue((out / "demo" / "demo-1.2.0.zip").is_file())
        self.assertFalse((out / "demo-kit").exists())
        code, stdout, _stderr = self.cli("test", "--all", "--no-cache")
        self.assertNotIn("kit_plugin", stdout)
        self.assertIn("SKIP plain:BUILD no BUILD.json", stdout)
        self.assertEqual(self.cli("build")[0], 2)  # nothing named is still a usage error
        self.assertEqual(skill_build.load_build(self.kit, "demo")[1], [])  # the kit's file is not a skill's


@unittest.skipUnless((KIT_ROOT / "02-skills").is_dir(), "kit only: the instance does not carry 02-skills/")
class RealKitPluginTests(unittest.TestCase):
    """The plugin of this checkout, built once into a temp folder; nothing is written to the kit."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="kit-plugin-")))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.kit = skill_build.Kit(KIT_ROOT)
        cls.built = skill_build.build_kit_plugin(cls.kit, cls.tmp / "dist")
        cls.folder = cls.built["plugin_dir"]
        cls.files = sorted(p.relative_to(cls.folder).as_posix() for p in cls.folder.rglob("*") if p.is_file())

    def test_it_holds_every_skill_of_the_kit_under_the_names_the_plugin_gives_its_tools(self):
        manifest = json.loads((self.folder / "MANIFEST.json").read_text(encoding="utf-8"))
        shipped = sorted(p.parent.name for p in (KIT_ROOT / "02-skills").glob("*/BUILD.json"))
        self.assertEqual([skill["name"] for skill in manifest["skills"]], shipped)
        self.assertGreaterEqual(len(shipped), 17)
        self.assertEqual(manifest["skills_left_out"], [])
        prefix = manifest["mcp_server"]["tool_prefix"]
        for skill in shipped:
            text = (self.folder / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertNotIn("mcp__metodo__", text, skill)
            self.assertNotIn("__TOOLS_DEFAULT__", text, skill)
        card = (self.folder / "skills" / "change-card" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"allowed-tools: [Read, {prefix}change_card_validate, {prefix}change_card_extract]", card)

    def test_it_holds_nothing_personal_no_test_no_build_file_no_cache_and_no_home_path(self):
        home = os.path.expanduser("~").encode()
        for name in self.files:
            parts = name.split("/")
            self.assertFalse(".personal." in name or "personal" in parts, name)
            self.assertFalse({"tests", "out", "vendor", "baselines", "__pycache__"} & set(parts), name)
            self.assertFalse(name.endswith((".pyc", "BUILD.json")), name)
            data = (self.folder / name).read_bytes()
            self.assertNotIn(home, data, name)
            if name.endswith(".py"):
                self.assertIsNone(re.search(rb"^(import unittest|from unittest)", data, re.M), name)

    def test_the_tools_folder_is_what_sync_instance_copies_minus_the_tests(self):
        instance = self.tmp / "instance"
        instance.mkdir()
        proc = subprocess.run(["bash", str(TOOLS_ROOT / "bin" / "sync-instance.sh"), str(instance)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        synced = {p.relative_to(instance).as_posix() for p in instance.rglob("*") if p.is_file()}
        tests = {name for name in synced if skill_build.is_test(name, (instance / name).read_bytes())}
        noise = {name for name in synced if set(name.split("/")) & set(skill_build.CACHE_PARTS)}  # a .DS_Store, never a rule
        packed = {name[len("tools/"):] for name in self.files if name.startswith("tools/")}
        self.assertEqual(packed, synced - tests - noise)
        self.assertTrue(any(name.startswith("tests/") for name in tests))
        self.assertIn("lib/test_test_sectors.py", tests)  # a test that sits in lib/ is still a test
        self.assertIn("lib/test_sectors.py", packed)

    def test_the_packed_server_answers_from_the_plugin_folder_alone(self):
        tools = self.folder / "tools"
        env = {"PATH": os.environ.get("PATH", ""), "METODO_TOOLS": str(tools), "METODO_REPO": "${CLAUDE_PROJECT_DIR}",
               "PYTHONDONTWRITEBYTECODE": "1", "METODO_MEMORY": "off"}
        card = (KIT_ROOT / "08-benchmark" / "evals" / "change-card" / "smoke-missing-field" / "setup" / "card.md")
        calls = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "change_card_validate", "arguments": {"card_text": card.read_text(encoding="utf-8")}}}]
        proc = subprocess.run([shutil.which("python3") or "python3", "-I", str(tools / "mcp" / "server.py")],
                              input="".join(json.dumps(call) + "\n" for call in calls), capture_output=True, text=True,
                              env=env, cwd=self.tmp, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        answers = [json.loads(line) for line in proc.stdout.splitlines()]
        names, _error = self.kit.catalog()
        self.assertEqual({tool["name"] for tool in answers[1]["result"]["tools"]}, set(names))
        verdict = answers[2]["result"]
        self.assertFalse(verdict["isError"], verdict)
        self.assertEqual(verdict["structuredContent"]["verdict"], "FAIL")  # the seed card lacks two fields
        self.assertIn(f"tools_root={tools}", proc.stderr)  # its tools root is the plugin's folder, not this checkout
        self.assertNotIn(str(TOOLS_ROOT), proc.stderr)

    def test_the_marketplace_folder_lists_the_one_plugin(self):
        listing = json.loads((self.built["marketplace"] / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual([plugin["source"] for plugin in listing["plugins"]], [f"./plugins/{self.built['name']}"])

    @unittest.skipUnless(shutil.which("claude"), "claude is not installed: the plugin folder was not validated by it")
    def test_claude_validates_the_built_plugin_strictly(self):
        for target in (self.folder, self.built["marketplace"]):
            proc = subprocess.run(["claude", "plugin", "validate", str(target), "--strict", "--json"],
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
