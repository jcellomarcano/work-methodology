"""Tests for lib/skill_eval.py: the eval case format, its validator, staging and content hash.

No test starts a model or a `claude` process. Every rule is asserted on the function that owns it
and through the command line, which runs under `python3 -I` like the other runners of this folder.
"""
import contextlib
import io
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

LIB = ROOT / "lib" / "skill_eval.py"
FIXTURES = ROOT / "tests" / "fixtures" / "skill-evals"
GOOD = FIXTURES / "good"
BROKEN = FIXTURES / "broken"
GOOD_CASE = GOOD / "demo-skill" / "smoke-basic"
CASE_ID = "demo-skill/smoke-basic"


def cli(*args):
    return subprocess.run([sys.executable, "-I", str(LIB), *args], capture_output=True, text=True)


class CaseTest(unittest.TestCase):
    """A private copy of the good fixture case under <tmp>/evals/demo-skill/smoke-basic."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(os.path.realpath(tmp.name))
        self.root = self.tmp / "evals"
        self.case = self.root / "demo-skill" / "smoke-basic"
        shutil.copytree(GOOD_CASE, self.case)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("OUTSIDE SECRET\n")

    def edit(self, drop=(), **changes):
        """Rewrite case.json from the pristine fixture with `changes` applied and `drop` removed."""
        raw = json.loads((GOOD_CASE / "case.json").read_text())
        raw.update(changes)
        for key in drop:
            raw.pop(key)
        (self.case / "case.json").write_text(json.dumps(raw))

    def set_files(self, *entries):
        self.edit(setup={"files": [{"from": src, "to": dst} for src, dst in entries]})

    def assert_problem(self, problem):
        """The function reports exactly this problem and the command prints it and exits 1."""
        self.assertIn(problem, skill_eval.validate_case(self.case))
        res = cli("validate", str(self.root))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(f"{CASE_ID}: {problem}", res.stdout.splitlines())
        self.assertNotIn("Traceback", res.stderr)

    def files_under(self, folder):
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if not p.is_dir())


class ValidateRules(CaseTest):
    def test_good_case_has_no_problem(self):
        self.assertEqual(skill_eval.validate_case(self.case), [])
        res = cli("validate", str(self.root))
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        self.assertEqual(res.stdout, "skill-eval: 1 cases, 1 valid, 0 with problems, 0 problems\n")

    def test_unknown_key_is_rejected(self):
        self.edit(retries=3)
        self.assert_problem("unknown key 'retries'")
        self.edit(setup={"files": [], "dirs": []})
        self.assert_problem("setup: unknown key 'dirs'")
        self.edit(setup={"files": [{"from": "setup/notes.txt", "to": "notes.txt", "mode": "0644"}]})
        self.assert_problem("setup.files[0]: unknown key 'mode'")

    def test_missing_required_key_is_rejected(self):
        for key in ("schema_version", "skill", "tier"):
            with self.subTest(key=key):
                self.edit(drop=[key])
                self.assert_problem(f"missing required key '{key}'")

    def test_wrong_type_is_rejected(self):
        for changes, problem in (
            ({"max_turns": "8"}, "'max_turns' must be a positive integer, got '8'"),
            ({"runs": True}, "'runs' must be a positive integer, got True"),
            ({"timeout_seconds": 0}, "'timeout_seconds' must be a positive integer, got 0"),
            ({"expected_skills": "demo-skill"},
             "'expected_skills' must be a list of non-empty strings, got 'demo-skill'"),
            ({"expectations": ["ok", ""]}, "'expectations' must be a list of non-empty strings, got ['ok', '']"),
            ({"allowed_tools": "Read,Edit"}, "'allowed_tools' must be a list of non-empty strings, got 'Read,Edit'"),
            ({"skill": 7}, "'skill' must be a non-empty string, got 7"),
            ({"setup": ["setup/notes.txt"]},
             "'setup' must be an object with a 'files' list, got ['setup/notes.txt']"),
            ({"setup": {"files": ["setup/notes.txt"]}},
             "setup.files[0] must be an object with string 'from' and 'to', got 'setup/notes.txt'"),
            ({"validators": "validators/check_output.py"},
             "'validators' must be a list of script paths, got 'validators/check_output.py'"),
            ({"forbidden_paths": "secrets/**"}, "'forbidden_paths' must be a list of relative globs, got 'secrets/**'"),
        ):
            with self.subTest(problem=problem):
                self.edit(**changes)
                self.assert_problem(problem)

    def test_unsupported_schema_version_is_rejected(self):
        self.edit(schema_version=2)
        self.assert_problem("'schema_version' must be 1, got 2")

    def test_tier_outside_smoke_core_deep_is_rejected(self):
        self.edit(tier="fast")
        self.assert_problem("'tier' must be one of smoke, core, deep, got 'fast'")

    def test_skill_must_name_the_folder_the_case_sits_in(self):
        self.edit(skill="other-skill")
        self.assert_problem("'skill' is 'other-skill' but the case sits in the folder 'demo-skill'")

    def test_missing_prompt_is_rejected(self):
        (self.case / "prompt.md").unlink()
        self.assert_problem("prompt.md is missing")

    def test_empty_prompt_is_rejected(self):
        (self.case / "prompt.md").write_text(" \n\n")
        self.assert_problem("prompt.md is empty")

    def test_absolute_path_is_rejected(self):
        self.set_files(("/etc/hosts", "hosts"))
        self.assert_problem("setup.files[0].from: '/etc/hosts' must be a relative path inside the case folder")
        self.set_files(("setup/notes.txt", "/tmp/notes.txt"))
        self.assert_problem("setup.files[0].to: '/tmp/notes.txt' must be a relative path inside the working directory")
        self.edit(validators=["/bin/sh"])
        self.assert_problem("validators[0]: '/bin/sh' must be a relative path inside the case folder")

    def test_path_that_leaves_the_case_folder_is_rejected(self):
        (self.case.parent / "shared.txt").write_text("shared\n")
        self.set_files(("../shared.txt", "shared.txt"))
        self.assert_problem("setup.files[0].from: '../shared.txt' must be a relative path inside the case folder")
        self.set_files(("setup/notes.txt", "../notes.txt"))
        self.assert_problem("setup.files[0].to: '../notes.txt' must be a relative path inside the working directory")
        self.edit(validators=["validators/../../shared.txt"])
        self.assert_problem("validators[0]: 'validators/../../shared.txt' must be a relative path inside the case folder")

    def test_path_that_leaves_the_case_folder_through_a_symlink_is_rejected(self):
        os.symlink(self.outside / "secret.txt", self.case / "setup" / "link.txt")
        self.set_files(("setup/link.txt", "link.txt"))
        self.assert_problem("setup.files[0].from: 'setup/link.txt' leaves the case folder through a symlink")
        # The same link met while walking a staged folder, not named by the entry itself.
        self.set_files(("setup", "."))
        self.assert_problem("setup.files[0].from: 'setup/link.txt' leaves the case folder through a symlink")
        os.symlink(self.outside / "secret.txt", self.case / "validators" / "link.py")
        self.edit(validators=["validators/link.py"])
        self.assert_problem("validators[0]: 'validators/link.py' leaves the case folder through a symlink")

    def test_setup_file_under_testdata_is_rejected(self):
        said = "stages testdata/, the answer key, which is never staged"
        self.set_files(("testdata/expected.txt", "expected.txt"))
        self.assert_problem(f"setup.files[0].from: 'testdata/expected.txt' {said}")
        self.set_files(("testdata", "answers"))
        self.assert_problem(f"setup.files[0].from: 'testdata' {said}")
        self.set_files((".", "."))  # the whole case folder holds testdata/
        self.assert_problem(f"setup.files[0].from: '.' {said}")
        os.symlink("../testdata/expected.txt", self.case / "setup" / "answer.txt")
        self.set_files(("setup/answer.txt", "answer.txt"))
        self.assert_problem(f"setup.files[0].from: 'setup/answer.txt' {said}")

    def test_setup_file_that_does_not_exist_is_rejected(self):
        self.set_files(("setup/nope.txt", "nope.txt"))
        self.assert_problem("setup.files[0].from: 'setup/nope.txt' does not exist")

    def test_validator_script_that_does_not_exist_is_rejected(self):
        self.edit(validators=["validators/check_output.py", "validators/nope.py"])
        self.assert_problem("validators[1]: 'validators/nope.py' does not exist")
        self.edit(validators=["validators"])
        self.assert_problem("validators[0]: 'validators' is not a file")

    def test_forbidden_and_exempt_paths_must_be_relative_globs(self):
        for key in ("forbidden_paths", "ablation_exempt_paths"):
            for index, bad in enumerate(("/etc/**", "../outside/*", "~/notes", "", 5)):
                with self.subTest(key=key, bad=bad):
                    self.edit(**{key: ["ok/**"] * index + [bad]})
                    self.assert_problem(f"{key}[{index}]: {bad!r} must be a relative glob")

    def test_case_with_no_scorer_is_rejected(self):
        said = "no scorer: needs at least one of expected_skills, validators, expectations"
        self.edit(drop=["expected_skills", "validators", "expectations"])
        self.assert_problem(said)
        self.edit(expected_skills=[], validators=[], expectations=[])
        self.assert_problem(said)

    def test_one_scorer_of_any_kind_is_enough(self):
        for keep in ("expected_skills", "validators", "expectations"):
            with self.subTest(keep=keep):
                self.edit(drop=[k for k in ("expected_skills", "validators", "expectations") if k != keep])
                self.assertEqual(skill_eval.validate_case(self.case), [])

    def test_unreadable_case_json_is_a_problem_line_not_a_crash(self):
        (self.case / "case.json").write_text("{not json")
        problems = skill_eval.validate_case(self.case)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("case.json is not valid JSON: "), problems)
        (self.case / "case.json").write_text("[]")
        self.assert_problem("case.json must be a JSON object, got list")
        (self.case / "case.json").unlink()
        self.assert_problem("case.json is missing")


class ValidateCommand(unittest.TestCase):
    def test_good_fixture_exits_0_with_a_summary(self):
        res = cli("validate", str(GOOD))
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        self.assertEqual(res.stdout, "skill-eval: 3 cases, 3 valid, 0 with problems, 0 problems\n")

    def test_broken_fixture_prints_sorted_problem_lines_then_a_summary_and_exits_1(self):
        res = cli("validate", str(BROKEN))
        self.assertEqual((res.returncode, res.stderr), (1, ""))
        self.assertEqual(res.stdout.splitlines(), [
            "demo-skill/a-unknown-key: 'tier' must be one of smoke, core, deep, got 'fast'",
            "demo-skill/a-unknown-key: unknown key 'retries'",
            "demo-skill/b-stages-testdata: setup.files[0].from: 'testdata/expected.txt' stages testdata/, "
            "the answer key, which is never staged",
            "other-skill/no-scorer: no scorer: needs at least one of expected_skills, validators, expectations",
            "other-skill/no-scorer: prompt.md is missing",
            "skill-eval: 3 cases, 0 valid, 3 with problems, 5 problems",
        ])

    def test_main_returns_the_same_codes_in_process(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(skill_eval.main(["validate", str(GOOD)]), 0)
            self.assertEqual(skill_eval.main(["validate", str(BROKEN)]), 1)
        self.assertEqual(out.getvalue().count("skill-eval: 3 cases"), 2)

    def assert_one_line_exit_2(self, res, said):
        self.assertEqual((res.returncode, res.stdout), (2, ""))
        self.assertEqual(len(res.stderr.splitlines()), 1, res.stderr)
        self.assertTrue(res.stderr.startswith("skill-eval: "), res.stderr)
        self.assertIn(said, res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_usage_error_is_one_line_and_exits_2(self):
        self.assert_one_line_exit_2(cli(), "COMMAND")
        self.assert_one_line_exit_2(cli("frobnicate"), "frobnicate")
        self.assert_one_line_exit_2(cli("validate", str(GOOD), "--no-such-flag"), "--no-such-flag")

    def test_unreadable_path_is_one_line_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_one_line_exit_2(cli("validate", os.path.join(tmp, "missing")), "cannot read")
            self.assert_one_line_exit_2(cli("validate", str(GOOD_CASE / "case.json")), "cannot read")
            # A root that holds no case would pass for the wrong reason, so it is refused.
            self.assert_one_line_exit_2(cli("validate", tmp), "no case found")


class Loading(CaseTest):
    def test_load_case_returns_the_validated_case_with_absolute_paths(self):
        case = skill_eval.load_case(self.case)
        self.assertEqual((case["skill"], case["name"], case["id"], case["tier"]),
                         ("demo-skill", "smoke-basic", CASE_ID, "smoke"))
        self.assertEqual(case["prompt"], (self.case / "prompt.md").read_text())
        self.assertEqual(case["setup"]["files"], [{"from": "setup/notes.txt", "to": "notes.txt"},
                                                  {"from": "setup/src", "to": "src"}])
        self.assertEqual(case["validators"], ["validators/check_output.py"])
        self.assertEqual(case["paths"], {
            "case_dir": str(self.case),
            "prompt": str(self.case / "prompt.md"),
            "testdata": str(self.case / "testdata"),
            "setup_files": [str(self.case / "setup" / "notes.txt"), str(self.case / "setup" / "src")],
            "validators": [str(self.case / "validators" / "check_output.py")],
        })

    def test_load_case_fills_the_optional_keys(self):
        case = skill_eval.load_case(GOOD / "demo-skill" / "core-trigger")
        self.assertEqual(case["setup"], {"files": []})
        for key in ("validators", "expectations", "forbidden_paths", "ablation_exempt_paths", "allowed_tools"):
            self.assertEqual(case[key], [], key)
        for key in ("max_turns", "timeout_seconds", "runs"):
            self.assertIsNone(case[key], key)
        self.assertIsNone(case["paths"]["testdata"])

    def test_load_case_refuses_an_invalid_case_naming_every_problem(self):
        self.edit(tier="fast", retries=3)
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.load_case(self.case)
        message = str(caught.exception)
        self.assertTrue(message.startswith(f"{CASE_ID}: "), message)
        self.assertIn("unknown key 'retries'", message)
        self.assertIn("'tier' must be one of smoke, core, deep, got 'fast'", message)

    def test_testdata_is_always_a_forbidden_path_when_the_folder_exists(self):
        self.assertEqual(skill_eval.load_case(self.case)["forbidden_paths"], ["secrets/**", "testdata/**"])
        self.edit(forbidden_paths=["testdata/**"])  # already listed by the author: not added twice
        self.assertEqual(skill_eval.load_case(self.case)["forbidden_paths"], ["testdata/**"])
        self.edit(drop=["forbidden_paths"])
        self.assertEqual(skill_eval.load_case(self.case)["forbidden_paths"], ["testdata/**"])
        shutil.rmtree(self.case / "testdata")
        self.assertEqual(skill_eval.load_case(self.case)["forbidden_paths"], [])

    def test_iter_cases_is_sorted_and_filters_by_skill_and_tier(self):
        ids = lambda **kw: [c["id"] for c in skill_eval.iter_cases(GOOD, **kw)]  # noqa: E731
        self.assertEqual(ids(), ["demo-skill/core-trigger", "demo-skill/smoke-basic", "other-skill/smoke-judge"])
        self.assertEqual(ids(skill="demo-skill"), ["demo-skill/core-trigger", "demo-skill/smoke-basic"])
        self.assertEqual(ids(tier="smoke"), ["demo-skill/smoke-basic", "other-skill/smoke-judge"])
        self.assertEqual(ids(skill="other-skill", tier="core"), [])
        self.assertEqual(ids(skill="no-such-skill"), [])

    def test_iter_cases_refuses_an_invalid_case_and_an_unreadable_root(self):
        with self.assertRaises(skill_eval.CaseError) as caught:
            list(skill_eval.iter_cases(BROKEN))
        self.assertIn("demo-skill/a-unknown-key: ", str(caught.exception))
        with self.assertRaises(skill_eval.CaseError) as caught:
            list(skill_eval.iter_cases(self.tmp / "missing"))
        self.assertIn("cannot read", str(caught.exception))


class Staging(CaseTest):
    def setUp(self):
        super().setUp()
        self.dest = self.tmp / "work"

    def test_stage_copies_setup_files_and_returns_the_relative_paths_written(self):
        written = skill_eval.stage(skill_eval.load_case(self.case), self.dest)
        self.assertEqual(written, ["notes.txt", "src/app.py"])
        self.assertEqual(self.files_under(self.dest), ["notes.txt", "src/app.py"])
        self.assertEqual((self.dest / "notes.txt").read_bytes(), (self.case / "setup" / "notes.txt").read_bytes())
        self.assertEqual((self.dest / "src" / "app.py").read_bytes(),
                         (self.case / "setup" / "src" / "app.py").read_bytes())

    def test_stage_puts_a_folder_at_the_root_and_a_file_under_a_new_name(self):
        self.set_files(("setup", "."), ("setup/notes.txt", "docs/readme.txt"))
        written = skill_eval.stage(skill_eval.load_case(self.case), self.dest)
        self.assertEqual(written, ["docs/readme.txt", "notes.txt", "src/app.py"])
        self.assertEqual(self.files_under(self.dest), written)

    def test_stage_copies_a_link_that_stays_in_the_case_as_a_regular_file(self):
        os.symlink("notes.txt", self.case / "setup" / "alias.txt")
        self.set_files(("setup/alias.txt", "alias.txt"))
        self.assertEqual(skill_eval.stage(skill_eval.load_case(self.case), self.dest), ["alias.txt"])
        self.assertFalse((self.dest / "alias.txt").is_symlink())
        self.assertEqual((self.dest / "alias.txt").read_text(), "The greeting must read: Hello, world.\n")

    def assert_stage_refused(self, case, said):
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.stage(case, self.dest)
        self.assertIn(said, str(caught.exception))

    def test_testdata_is_never_staged(self):
        case = skill_eval.load_case(self.case)
        skill_eval.stage(case, self.dest)
        answer = (self.case / "testdata" / "expected.txt").read_bytes()
        self.assertEqual([p for p in self.dest.rglob("*") if p.is_file() and p.read_bytes() == answer], [])
        # A link into testdata/ planted after the case was loaded is still refused, and nothing is written.
        shutil.rmtree(self.dest)
        (self.case / "setup" / "notes.txt").unlink()
        os.symlink("../testdata/expected.txt", self.case / "setup" / "notes.txt")
        self.assert_stage_refused(case, "setup.files[0].from: 'setup/notes.txt' stages testdata/")
        self.assertEqual(self.files_under(self.dest) if self.dest.exists() else [], [])

    def test_stage_never_follows_a_symlink_out_of_the_case(self):
        case = skill_eval.load_case(self.case)
        os.symlink(self.outside / "secret.txt", self.case / "setup" / "src" / "leak.txt")
        self.assert_stage_refused(
            case, "setup.files[1].from: 'setup/src/leak.txt' leaves the case folder through a symlink")
        self.assertEqual(self.files_under(self.dest) if self.dest.exists() else [], [])
        # A linked folder is refused too, even one that stays inside the case (it could loop).
        (self.case / "setup" / "src" / "leak.txt").unlink()
        os.symlink(self.case / "setup", self.case / "setup" / "src" / "loop")
        self.assert_stage_refused(case, "setup.files[1].from: 'setup/src/loop' is a symlink to a folder")

    def test_stage_never_writes_outside_dest(self):
        case = skill_eval.load_case(self.case)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.dest.mkdir()
        os.symlink(elsewhere, self.dest / "src")  # dest/src/app.py would land in elsewhere/
        self.assert_stage_refused(
            case, "setup.files[1].to: 'src/app.py' would be written outside the working directory")
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(os.listdir(self.dest), ["src"])  # only the planted link: notes.txt was not written


class ContentHash(CaseTest):
    def setUp(self):
        super().setUp()
        self.skill = self.tmp / "skills" / "demo-skill"
        self.skill.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: demo-skill\n---\nDo the demo.\n")
        (self.skill / "scripts").mkdir()
        (self.skill / "scripts" / "run.py").write_text("print('demo')\n")

    def digest(self):
        return skill_eval.case_hash(skill_eval.load_case(self.case), self.skill)

    def test_case_hash_is_stable_across_locations_and_mtimes(self):
        before = self.digest()
        self.assertRegex(before, r"^[0-9a-f]{64}$")
        self.assertEqual(self.digest(), before)
        moved = self.tmp / "moved" / "deeper"
        shutil.copytree(self.root, moved / "evals")
        shutil.copytree(self.skill, moved / "skill-copy")
        for path in (moved / "evals").rglob("*"):
            os.utime(path, (1, 1))
        other = skill_eval.load_case(moved / "evals" / "demo-skill" / "smoke-basic")
        self.assertEqual(skill_eval.case_hash(other, moved / "skill-copy"), before)

    def test_case_hash_changes_with_any_byte_or_path_of_the_case_or_the_skill(self):
        seen = {self.digest()}
        changes = (
            lambda: (self.case / "prompt.md").write_text("Another prompt.\n"),
            lambda: (self.case / "testdata" / "expected.txt").write_text("Hello, world!\n"),
            lambda: (self.case / "setup" / "src" / "app.py").rename(self.case / "setup" / "src" / "main.py"),
            lambda: (self.skill / "SKILL.md").write_text("---\nname: demo-skill\n---\nDo the demo well.\n"),
            lambda: (self.skill / "scripts" / "run.py").rename(self.skill / "scripts" / "go.py"),
            lambda: (self.skill / "extra.md").write_text(""),
        )
        for number, change in enumerate(changes):
            change()
            if number == 2:  # keep case.json pointing at a folder that still exists
                self.assertEqual(skill_eval.validate_case(self.case), [])
            digest = self.digest()
            self.assertNotIn(digest, seen, f"change {number} left the hash unchanged")
            seen.add(digest)

    def test_case_hash_ignores_caches_the_tools_leave_behind(self):
        before = self.digest()
        (self.case / "validators" / "__pycache__").mkdir()
        (self.case / "validators" / "__pycache__" / "check_output.cpython-311.pyc").write_bytes(b"\x00")
        (self.skill / ".DS_Store").write_bytes(b"\x01")
        self.assertEqual(self.digest(), before)

    def test_case_hash_refuses_a_skill_folder_that_does_not_exist(self):
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.case_hash(skill_eval.load_case(self.case), self.tmp / "no-such-skill")
        self.assertIn("skill folder", str(caught.exception))


@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads what mode 000 hides")
class ReviewFindings(CaseTest):
    """The seven findings of the native review of T1 (feature document, L8), one test each."""

    def lock(self, path):
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o755)

    def test_another_spelling_of_testdata_is_never_staged(self):  # R1-testdata-case-fold
        # On a case-insensitive file system "TESTDATA/expected.txt" opens the answer key.
        self.set_files(("TESTDATA/expected.txt", "answer.txt"))
        self.assert_problem("setup.files[0].from: 'TESTDATA/expected.txt' stages testdata/, "
                            "the answer key, which is never staged")

    def test_answer_key_folder_under_another_spelling_is_a_problem(self):  # R1-testdata-case-fold
        os.rename(self.case / "testdata", self.case / "answer-key")
        os.rename(self.case / "answer-key", self.case / "TestData")
        self.assert_problem("the answer key folder must be spelled 'testdata', found 'TestData'")

    def test_unreadable_setup_folder_is_a_problem_line_not_a_traceback(self):  # R3-validate-listdir-traceback
        self.lock(self.case / "setup" / "src")
        problems = skill_eval.validate_case(self.case)
        self.assertEqual([p for p in problems if "cannot be read" in p][:1],
                         [p for p in problems if p.startswith("setup.files[1].from: 'setup/src' cannot be read")])
        self.assertTrue(any("cannot be read" in p for p in problems), problems)
        res = cli("validate", str(self.root))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_stage_writes_nothing_when_a_later_file_cannot_be_copied(self):  # R3-stage-partial-write
        self.set_files(("setup/notes.txt", "a.txt"), ("setup/src/app.py", "b.py"))
        case = skill_eval.load_case(self.case)
        self.lock(self.case / "setup" / "src" / "app.py")
        dest = self.tmp / "work"
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.stage(case, dest)
        self.assertIn(f"{CASE_ID}: ", str(caught.exception))
        self.assertEqual(self.files_under(dest) if dest.exists() else [], [])

    def test_failed_staging_puts_back_the_file_it_replaced(self):  # R3-stage-rollback-overwrites (L12)
        self.set_files(("setup/notes.txt", "a.txt"), ("setup/src/app.py", "blocked/b.py"))
        case = skill_eval.load_case(self.case)
        dest = self.tmp / "work"
        dest.mkdir()
        (dest / "a.txt").write_text("the file that was there\n")
        (dest / "blocked").write_text("a file where the staging needs a folder\n")
        with self.assertRaises(skill_eval.CaseError):
            skill_eval.stage(case, dest)
        self.assertEqual((dest / "a.txt").read_text(), "the file that was there\n")
        self.assertEqual(self.files_under(dest), ["a.txt", "blocked"])

    def test_staging_still_replaces_a_file_when_every_file_lands(self):  # previous behavior of stage
        self.set_files(("setup/notes.txt", "a.txt"))
        dest = self.tmp / "work"
        dest.mkdir()
        (dest / "a.txt").write_text("the file that was there\n")
        skill_eval.stage(skill_eval.load_case(self.case), dest)
        self.assertEqual((dest / "a.txt").read_bytes(), (self.case / "setup" / "notes.txt").read_bytes())
        self.assertEqual(self.files_under(dest), ["a.txt"])

    def test_two_setup_files_with_one_destination_are_a_problem(self):  # open since L7
        self.set_files(("setup/notes.txt", "a.txt"), ("setup/src/app.py", "a.txt"))
        self.assert_problem("setup.files[1].to: 'a.txt' is also the destination of setup.files[0]: "
                            "two files cannot land on one path")
        self.set_files(("setup/src", "code"), ("setup/notes.txt", "code/app.py"))
        self.assert_problem("setup.files[1].to: 'code/app.py' is also the destination of setup.files[0]: "
                            "two files cannot land on one path")

    def test_two_spellings_of_one_destination_are_a_problem(self):  # R3-duplicate-destination-check-gaps
        # a file system that ignores case, or the form of an accent, opens both as one file
        self.set_files(("setup/notes.txt", "out/Notes.txt"), ("setup/src/app.py", "out/notes.txt"))
        self.assert_problem("setup.files[1].to: 'out/notes.txt' is the destination 'out/Notes.txt' of setup.files[0] "
                            "under another spelling: two files cannot land on one path")
        composed, decomposed = "caf\u00e9.txt", "cafe\u0301.txt"
        self.set_files(("setup/notes.txt", composed), ("setup/src/app.py", decomposed))
        self.assert_problem(f"setup.files[1].to: {decomposed!r} is the destination {composed!r} of setup.files[0] "
                            f"under another spelling: two files cannot land on one path")
        self.set_files(("setup/src", "Code"), ("setup/notes.txt", "code/APP.py"))
        self.assert_problem("setup.files[1].to: 'code/APP.py' is the destination 'Code/app.py' of setup.files[0] "
                            "under another spelling: two files cannot land on one path")

    def test_a_file_cannot_land_where_another_entry_needs_a_folder(self):  # R3-duplicate-destination-check-gaps
        self.set_files(("setup/notes.txt", "code"), ("setup/src/app.py", "code/app.py"))
        self.assert_problem("setup.files[1].to: 'code/app.py' needs 'code' to be a folder, and setup.files[0] stages a file there")
        self.set_files(("setup/src", "code/deep"), ("setup/notes.txt", "Code"))
        self.assert_problem("setup.files[1].to: 'Code' is a file where setup.files[0] stages 'code/deep/app.py': "
                            "one path cannot be a file and a folder")

    def test_spellings_the_path_type_folds_were_already_one_destination(self):  # previous behavior of the check
        for first, second in (("a.txt", "./a.txt"), ("deep/a.txt", "deep//a.txt"), ("deep/a.txt", "deep/./a.txt")):
            with self.subTest(second=second):
                self.set_files(("setup/notes.txt", first), ("setup/src/app.py", second))
                self.assert_problem(f"setup.files[1].to: {first!r} is also the destination of setup.files[0]: "
                                    f"two files cannot land on one path")

    def test_destinations_that_only_share_a_folder_are_no_problem(self):  # previous behavior of the check
        self.set_files(("setup/notes.txt", "code/notes.txt"), ("setup/src", "code"), ("setup/src/app.py", "code2"))
        self.assertEqual(skill_eval.validate_case(self.case), [])

    def test_stage_still_copies_every_file_when_all_can_be(self):  # previous behavior of stage
        self.set_files(("setup/notes.txt", "a.txt"), ("setup/src/app.py", "deep/b.py"))
        dest = self.tmp / "work"
        self.assertEqual(skill_eval.stage(skill_eval.load_case(self.case), dest), ["a.txt", "deep/b.py"])
        self.assertEqual(self.files_under(dest), ["a.txt", "deep/b.py"])
        self.assertEqual((dest / "deep" / "b.py").read_bytes(), (self.case / "setup" / "src" / "app.py").read_bytes())

    def test_case_hash_refuses_a_folder_it_cannot_walk(self):  # R3-hash-silent-walk-errors
        skill = self.tmp / "skills" / "demo-skill"
        (skill / "hidden").mkdir(parents=True)
        (skill / "SKILL.md").write_text("demo\n")
        (skill / "hidden" / "part.md").write_text("part\n")
        case = skill_eval.load_case(self.case)
        before = skill_eval.case_hash(case, skill)
        self.lock(skill / "hidden")
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.case_hash(case, skill)
        self.assertIn("cannot hash", str(caught.exception))
        os.chmod(skill / "hidden", 0o755)
        self.assertEqual(skill_eval.case_hash(case, skill), before)  # previous behavior: same bytes, same hash

    def test_case_reached_through_a_link_keeps_the_name_it_was_given(self):  # R2-case-identity-from-realpath
        store = self.tmp / "store" / "elsewhere" / "real-case"
        store.parent.mkdir(parents=True)
        shutil.move(str(self.case), str(store))
        os.symlink(store, self.root / "demo-skill" / "linked")
        linked = self.root / "demo-skill" / "linked"
        self.assertEqual(skill_eval.validate_case(linked), [])
        case = skill_eval.load_case(linked)
        self.assertEqual((case["id"], case["name"]), ("demo-skill/linked", "linked"))
        self.assertEqual(case["paths"]["case_dir"], str(store))  # the files are still read where they are

    def test_case_json_that_is_a_link_out_of_the_case_is_rejected(self):  # R3-case-json-symlink
        outside = self.outside / "case.json"
        shutil.copy(self.case / "case.json", outside)
        os.remove(self.case / "case.json")
        os.symlink(outside, self.case / "case.json")
        self.assert_problem("case.json leaves the case folder through a symlink")

    def test_every_refusal_of_a_case_is_worded_by_one_helper(self):  # R2-duplicated-error-join
        self.assertEqual(str(skill_eval._case_error("a/b", ["first", "second"])), "a/b: first; second")
        self.assertIsInstance(skill_eval._case_error("a/b", ["x"]), skill_eval.CaseError)
        # Previous behavior at the three places that raise it: the case id, then the problems.
        self.edit(tier="nightly", max_turns=0)
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.load_case(self.case)
        self.assertTrue(str(caught.exception).startswith(f"{CASE_ID}: "), caught.exception)
        self.assertIn("; ", str(caught.exception))
        self.edit()
        case = skill_eval.load_case(self.case)
        os.symlink(self.outside, self.case / "setup" / "src" / "escape")
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.stage(case, self.tmp / "work")
        self.assertTrue(str(caught.exception).startswith(f"{CASE_ID}: setup.files[1].from"), caught.exception)
        os.remove(self.case / "setup" / "src" / "escape")
        dest = self.tmp / "linked-dest"
        dest.mkdir()
        os.symlink(self.outside, dest / "src")
        with self.assertRaises(skill_eval.CaseError) as caught:
            skill_eval.stage(case, dest)
        self.assertTrue(str(caught.exception).startswith(f"{CASE_ID}: setup.files[1].to"), caught.exception)


if __name__ == "__main__":
    unittest.main()
