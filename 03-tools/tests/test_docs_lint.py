import json
import os
import tempfile
import unittest
from pathlib import Path

from lib import docs_lint


class CheckTests(unittest.TestCase):
    def test_offender_missing_and_ok_are_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.md").write_text("\n".join(f"line {i}" for i in range(5)), encoding="utf-8")
            (root / "over.md").write_text("\n".join(f"line {i}" for i in range(10)), encoding="utf-8")
            caps = {"ok.md": 10, "over.md": 5, "ghost.md": 20}
            result = docs_lint.check(root, caps)
            self.assertEqual(result["missing"], ["ghost.md"])
            self.assertEqual(len(result["offenders"]), 1)
            self.assertEqual(result["offenders"][0]["path"], "over.md")
            self.assertGreater(result["offenders"][0]["actual"], result["offenders"][0]["limit"])
            self.assertEqual(len(result["ok"]), 1)
            self.assertEqual(result["ok"][0]["path"], "ok.md")

    def test_clean_config_has_no_offenders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "small.md").write_text("one line\n", encoding="utf-8")
            # negative control: within the limit -> must never appear as an offender
            result = docs_lint.check(root, {"small.md": 100})
            self.assertEqual(result["offenders"], [])

    def test_expands_tilde_in_docs_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            # negative control: if '~' were not expanded, it would look for a directory
            # literally named "~" and everything would come out "missing".
            fake_home_child = Path(tmp) / "docroot"
            fake_home_child.mkdir()
            (fake_home_child / "doc.md").write_text("x\n", encoding="utf-8")
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                result = docs_lint.check("~/docroot", {"doc.md": 10})
            finally:
                if old_home is not None:
                    os.environ["HOME"] = old_home
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["ok"][0]["path"], "doc.md")

    def test_path_in_report_is_relative_not_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text("x\nx\n", encoding="utf-8")
            result = docs_lint.check(root, {"doc.md": 1})
            # negative control: the report must not leak the reader's absolute path
            reported = result["offenders"][0]["path"]
            self.assertEqual(reported, "doc.md")
            self.assertNotIn(str(root), reported)

    def test_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "d.md").write_text("x\n" * 3, encoding="utf-8")
            caps = {"d.md": 1}
            first = docs_lint.check(root, caps)
            second = docs_lint.check(root, caps)
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class MainExitCodeTests(unittest.TestCase):
    def test_exits_1_when_offenders_present(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "over.md").write_text("x\n" * 5, encoding="utf-8")
            config_path = root / "docs-caps.json"
            config_path.write_text(
                json.dumps({"docs_root": str(root), "caps": {"over.md": 1}}), encoding="utf-8"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = docs_lint.main([str(config_path)])
            self.assertEqual(code, 1)

    def test_exits_0_when_all_missing_or_ok(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "docs-caps.json"
            config_path.write_text(
                json.dumps({"docs_root": str(root), "caps": {"ghost.md": 10}}), encoding="utf-8"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = docs_lint.main([str(config_path)])
            self.assertEqual(code, 0)



KIT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_ROOT = KIT_ROOT / "03-tools"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skill(description: str, body: str) -> str:
    return f"---\nname: s\ndescription: {description}\nversion: 1.0.0\n---\n{body}"


def _run_main(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = docs_lint.main(argv)
    return code, out.getvalue()


class TokenCountTests(unittest.TestCase):
    def test_tokens_are_ceil_of_chars_over_four(self):
        self.assertEqual(docs_lint.METHOD, "ceil(chars/4)")
        self.assertEqual(docs_lint.token_count(""), 0)
        self.assertEqual(docs_lint.token_count("abcd"), 1)
        # negative control: 5 chars is 2 tokens, not 1 (floor) and not 5 (chars)
        self.assertEqual(docs_lint.token_count("abcde"), 2)
        # characters, not bytes: 4 accented chars are 8 bytes but still 1 token
        self.assertEqual(docs_lint.token_count("áéíó"), 1)


class TokenCheckTests(unittest.TestCase):
    def test_whole_file_token_cap_pass_fail_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "small.md", "x" * 40)   # 10 tokens
            _write(root / "big.md", "x" * 41)     # 11 tokens
            config = {"method": "ceil(chars/4)", "token_caps": {"small.md": 10, "big.md": 10, "ghost.md": 5}}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual(result["method"], "ceil(chars/4)")
            self.assertEqual(result["missing"], ["ghost.md"])
            self.assertEqual(result["offenders"], [{"path": "big.md", "unit": "tokens", "actual": 11, "limit": 10}])
            self.assertEqual(result["ok"], [{"path": "small.md", "unit": "tokens", "actual": 10, "limit": 10}])

    def test_field_cap_on_skill_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "02-skills/short/SKILL.md", _skill("d" * 240, "body\n"))   # 60 tokens
            _write(root / "02-skills/long/SKILL.md", _skill("d" * 241, "body\n"))    # 61 tokens
            config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual([o["path"] for o in result["offenders"]], ["02-skills/long/SKILL.md"])
            self.assertEqual(result["offenders"][0]["field"], "description")
            self.assertEqual(result["offenders"][0]["actual"], 61)
            # negative control: the passing skill sits exactly on the cap
            self.assertEqual([(o["path"], o["actual"]) for o in result["ok"]], [("02-skills/short/SKILL.md", 60)])

    def test_body_cap_uses_the_render_agents_frontmatter_split(self):
        from lib import render_agents

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # a huge frontmatter must not count against the body cap
            fat_front = _write(root / "01-roles/agents/generic-fat.md",
                               "---\nname: fat\ndescription: " + "f" * 4000 + "\n---\n" + "b" * 36)
            long_body = _write(root / "01-roles/agents/generic-long.md",
                               "---\nname: long\ndescription: x\n---\n" + "b" * 37)
            config = {"field_caps": [{"glob": "01-roles/agents/generic-*.md", "part": "body", "cap": 9}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual([o["path"] for o in result["offenders"]], ["01-roles/agents/generic-long.md"])
            self.assertEqual(result["offenders"][0]["part"], "body")
            self.assertEqual(result["ok"][0]["path"], "01-roles/agents/generic-fat.md")
            for path in (fat_front, long_body):
                body = render_agents.split_frontmatter(path.read_text(encoding="utf-8"))[1]
                entry = next(e for e in result["ok"] + result["offenders"] if root / e["path"] == path)
                self.assertEqual(entry["actual"], docs_lint.token_count(body))

    def test_field_cap_override_raises_the_cap_for_one_named_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "01-roles/agents/generic-big.md", "---\nname: big\ndescription: x\n---\n" + "b" * 40)
            _write(root / "01-roles/agents/generic-other.md", "---\nname: other\ndescription: x\n---\n" + "b" * 40)
            config = {"field_caps": [{"glob": "01-roles/agents/generic-*.md", "part": "body", "cap": 9,
                                      "overrides": {"01-roles/agents/generic-big.md": 12}}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual([o["path"] for o in result["offenders"]], ["01-roles/agents/generic-other.md"])
            big = next(e for e in result["ok"] if e["path"] == "01-roles/agents/generic-big.md")
            self.assertEqual(big["limit"], 12)

    def test_an_override_for_a_file_the_glob_misses_is_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "01-roles/agents/generic-a.md", "---\nname: a\ndescription: x\n---\nb\n")
            config = {"field_caps": [{"glob": "01-roles/agents/generic-*.md", "part": "body", "cap": 9,
                                      "overrides": {"01-roles/agents/generic-gone.md": 12}}]}
            self.assertIn("01-roles/agents/generic-gone.md", docs_lint.check_tokens(root, config)["missing"])

    def test_field_cap_without_frontmatter_or_field_is_an_offender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "02-skills/bare/SKILL.md", "no frontmatter at all\n")
            _write(root / "02-skills/nodesc/SKILL.md", "---\nname: nodesc\n---\nbody\n")
            config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual(sorted(o["path"] for o in result["offenders"]),
                             ["02-skills/bare/SKILL.md", "02-skills/nodesc/SKILL.md"])
            self.assertTrue(all("error" in o for o in result["offenders"]))

    def test_glob_that_matches_nothing_is_missing_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
            result = docs_lint.check_tokens(Path(tmp), config)
            self.assertEqual(result["missing"], ["02-skills/*/SKILL.md"])
            self.assertEqual(result["offenders"], [])
            self.assertEqual(result["ok"], [])

    def test_token_report_is_sorted_relative_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("c", "a", "b"):
                _write(root / f"02-skills/{name}/SKILL.md", _skill("d" * 400, "body\n"))
            config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
            first = docs_lint.check_tokens(root, config)
            second = docs_lint.check_tokens(root, config)
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
            paths = [o["path"] for o in first["offenders"]]
            self.assertEqual(paths, sorted(paths))
            self.assertTrue(all(str(root) not in p for p in paths))


class MainTokensAndRootTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        _write(root / "doc.md", "aaaa\nbbbb\n")   # 2 lines, 3 tokens
        lines = _write(root / "docs-caps.json",
                       json.dumps({"docs_root": str(root / "nowhere"), "caps": {"doc.md": 5, "ghost.md": 3}}))
        tokens = _write(root / "token-caps.json", json.dumps({
            "method": "ceil(chars/4)",
            "token_caps": {"doc.md": 1},
            "field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}],
        }))
        return lines, tokens

    def test_legacy_output_is_byte_identical_without_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "ok.md", "x\n")
            _write(root / "over.md", "x\n" * 3)
            config = _write(root / "docs-caps.json",
                            json.dumps({"docs_root": str(root), "caps": {"over.md": 2, "ok.md": 2, "ghost.md": 1}}))
            code, out = _run_main([str(config)])
            expected = (
                '{\n'
                '  "missing": [\n    "ghost.md"\n  ],\n'
                '  "offenders": [\n    {\n      "actual": 3,\n      "limit": 2,\n      "path": "over.md"\n    }\n  ],\n'
                '  "ok": [\n    {\n      "actual": 1,\n      "limit": 2,\n      "path": "ok.md"\n    }\n  ]\n'
                '}\n'
            )
            self.assertEqual(code, 1)
            self.assertEqual(out, expected)

    def test_root_overrides_docs_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines, _ = self._fixture(root)
            # negative control: the config's docs_root has no doc.md
            _, out = _run_main([str(lines)])
            self.assertIn("doc.md", json.loads(out)["missing"])
            code, out = _run_main([str(lines), "--root", str(root)])
            report = json.loads(out)
            self.assertEqual(code, 0)
            self.assertEqual(report["missing"], ["ghost.md"])
            self.assertEqual(report["ok"], [{"actual": 2, "limit": 5, "path": "doc.md"}])

    def test_tokens_flag_merges_both_reports_and_fails_on_a_token_offender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines, tokens = self._fixture(root)
            code, out = _run_main([str(lines), "--tokens", str(tokens), "--root", str(root)])
            report = json.loads(out)
            self.assertEqual(code, 1)
            self.assertEqual(report["method"], "ceil(chars/4)")
            self.assertEqual(report["offenders"], [{"path": "doc.md", "unit": "tokens", "actual": 3, "limit": 1}])
            self.assertIn({"path": "doc.md", "unit": "lines", "actual": 2, "limit": 5}, report["ok"])
            self.assertEqual(report["missing"], ["02-skills/*/SKILL.md", "ghost.md"])

    def test_each_cap_kind_fails_the_exit_code(self):
        kinds = {
            "token_caps": {"token_caps": {"doc.md": 1}},
            "field": {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 1}]},
            "part": {"field_caps": [{"glob": "02-skills/*/SKILL.md", "part": "body", "cap": 1}]},
        }
        for kind, extra in kinds.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(root / "doc.md", "x" * 50)
                _write(root / "02-skills/a/SKILL.md", _skill("d" * 50, "b" * 50))
                lines = _write(root / "docs-caps.json", json.dumps({"docs_root": str(root), "caps": {"doc.md": 99}}))
                tokens = _write(root / "token-caps.json", json.dumps({"method": "ceil(chars/4)", **extra}))
                code, out = _run_main([str(lines), "--tokens", str(tokens)])
                self.assertEqual(code, 1, out)
                self.assertEqual(len(json.loads(out)["offenders"]), 1)
                # negative control: the line caps alone pass
                self.assertEqual(_run_main([str(lines)])[0], 0)

    def test_tokens_config_with_a_foreign_method_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines, _ = self._fixture(root)
            bad = _write(root / "bad.json", json.dumps({"method": "tiktoken", "token_caps": {}}))
            with self.assertRaises(SystemExit):
                _run_main([str(lines), "--tokens", str(bad), "--root", str(root)])


def _main_err(argv: list[str]) -> tuple[int, str, str]:
    """Runs main and returns (exit code, stdout, stderr); an argparse exit is a code, not a raise."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = docs_lint.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TokenConfigValidationTests(unittest.TestCase):
    """A malformed token config is refused with exit 2 and a message, never a crash or a pass."""

    BAD = {
        "token cap zero": {"token_caps": {"doc.md": 0}},
        "token cap negative": {"token_caps": {"doc.md": -3}},
        "token cap string": {"token_caps": {"doc.md": "600"}},
        "token cap float": {"token_caps": {"doc.md": 1.5}},
        "token cap bool": {"token_caps": {"doc.md": True}},
        "token_caps not a dict": {"token_caps": ["doc.md"]},
        "token cap absolute path": {"token_caps": {"/etc/passwd": 10}},
        "token cap with ..": {"token_caps": {"../outside.md": 10}},
        "field_caps not a list": {"field_caps": {"glob": "*.md", "part": "body", "cap": 1}},
        "field cap not a dict": {"field_caps": ["*.md"]},
        "field and part": {"field_caps": [{"glob": "*.md", "field": "description", "part": "body", "cap": 1}]},
        "neither field nor part": {"field_caps": [{"glob": "*.md", "cap": 1}]},
        "unknown part": {"field_caps": [{"glob": "*.md", "part": "head", "cap": 1}]},
        "no cap": {"field_caps": [{"glob": "*.md", "part": "body"}]},
        "field cap zero": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 0}]},
        "field cap string": {"field_caps": [{"glob": "*.md", "part": "body", "cap": "9"}]},
        "no glob": {"field_caps": [{"part": "body", "cap": 9}]},
        "absolute glob": {"field_caps": [{"glob": "/tmp/*.md", "part": "body", "cap": 9}]},
        "glob with ..": {"field_caps": [{"glob": "../*/x.md", "part": "body", "cap": 9}]},
        "overrides not a dict": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 9,
                                                  "overrides": ["a.md"]}]},
        "override cap zero": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 9,
                                               "overrides": {"a.md": 0}}]},
        "override cap string": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 9,
                                                 "overrides": {"a.md": "12"}}]},
        "override path with ..": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 9,
                                                   "overrides": {"../a.md": 12}}]},
        "override absolute path": {"field_caps": [{"glob": "*.md", "part": "body", "cap": 9,
                                                    "overrides": {"/a.md": 12}}]},
    }

    def test_check_tokens_raises_value_error_for_each_malformed_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, config in self.BAD.items():
                with self.subTest(case=name):
                    with self.assertRaises(ValueError):
                        docs_lint.check_tokens(Path(tmp), {"method": "ceil(chars/4)", **config})

    def test_cli_exits_2_with_a_message_and_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "doc.md", "x\n")
            lines = _write(root / "docs-caps.json", json.dumps({"docs_root": str(root), "caps": {"doc.md": 9}}))
            for name, config in self.BAD.items():
                with self.subTest(case=name):
                    tokens = _write(root / "token-caps.json", json.dumps({"method": "ceil(chars/4)", **config}))
                    code, out, err = _main_err([str(lines), "--tokens", str(tokens), "--root", str(root)])
                    self.assertEqual(code, 2, err)
                    self.assertIn("token-caps.json", err)
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(out, "")

    def test_cli_exits_2_on_unreadable_token_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = _write(root / "docs-caps.json", json.dumps({"docs_root": str(root), "caps": {}}))
            broken = _write(root / "broken.json", "{not json")
            for path in (broken, root / "absent.json"):
                with self.subTest(path=path.name):
                    code, _, err = _main_err([str(lines), "--tokens", str(path), "--root", str(root)])
                    self.assertEqual(code, 2, err)
                    self.assertNotIn("Traceback", err)

    def test_a_valid_config_with_comment_and_override_is_accepted(self):
        # negative control: the shipped shape (with `_comment` and an override) is not refused
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "01-roles/agents/generic-a.md", "---\nname: a\ndescription: x\n---\nb\n")
            config = {"method": "ceil(chars/4)", "token_caps": {},
                      "field_caps": [{"_comment": "why", "glob": "01-roles/agents/generic-*.md", "part": "body",
                                      "cap": 9, "overrides": {"01-roles/agents/generic-a.md": 12}}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual(result["offenders"], [])
            self.assertEqual(result["ok"][0]["limit"], 12)


class TokenMissingFailsTests(unittest.TestCase):
    """Under --tokens a missing entry is a failure: a cap that measures nothing guards nothing."""

    def _run(self, root: Path, token_config: dict) -> tuple[int, dict, str]:
        _write(root / "doc.md", "x\n")
        lines = _write(root / "docs-caps.json", json.dumps({"docs_root": str(root), "caps": {"doc.md": 9}}))
        tokens = _write(root / "token-caps.json", json.dumps({"method": "ceil(chars/4)", **token_config}))
        code, out, err = _main_err([str(lines), "--tokens", str(tokens), "--root", str(root)])
        return code, json.loads(out), err

    def test_glob_matching_nothing_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, err = self._run(Path(tmp), {"field_caps": [{"glob": "02-skills/*/SKILL.md",
                                                                         "field": "description", "cap": 60}]})
            self.assertEqual(report["offenders"], [])
            self.assertEqual(report["missing"], ["02-skills/*/SKILL.md"])
            self.assertEqual(code, 1)
            self.assertIn("MISSING: 02-skills/*/SKILL.md", err)

    def test_stale_override_path_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "01-roles/agents/generic-a.md", "---\nname: a\ndescription: x\n---\nb\n")
            code, report, _ = self._run(root, {"field_caps": [{
                "glob": "01-roles/agents/generic-*.md", "part": "body", "cap": 9,
                "overrides": {"01-roles/agents/generic-gone.md": 12}}]})
            self.assertEqual(report["missing"], ["01-roles/agents/generic-gone.md"])
            self.assertEqual(code, 1)

    def test_absent_token_capped_file_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, _ = self._run(Path(tmp), {"token_caps": {"AGENTS.md": 600}})
            self.assertEqual(report["missing"], ["AGENTS.md"])
            self.assertEqual(code, 1)

    def test_nothing_missing_and_nothing_over_exits_0(self):
        # negative control: the same fixture with every capped file present passes
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "AGENTS.md", "short\n")
            code, report, _ = self._run(root, {"token_caps": {"AGENTS.md": 600}})
            self.assertEqual(report["missing"], [])
            self.assertEqual(code, 0)

    def test_without_tokens_a_missing_doc_still_exits_0(self):
        # the legacy line-cap contract is unchanged: a doc not written yet is not a failure
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = _write(root / "docs-caps.json", json.dumps({"docs_root": str(root), "caps": {"ghost.md": 9}}))
            code, out, err = _main_err([str(lines)])
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self.assertEqual(json.loads(out)["missing"], ["ghost.md"])


class BlockScalarDescriptionTests(unittest.TestCase):
    def test_folded_or_literal_description_is_an_offender_with_an_error(self):
        for marker in (">", "|", ">-", "|+"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(root / "02-skills/folded/SKILL.md",
                       f"---\nname: s\ndescription: {marker}\n  " + "d " * 400 + "\nversion: 1.0.0\n---\nbody\n")
                config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
                result = docs_lint.check_tokens(root, config)
                self.assertEqual(result["ok"], [])
                self.assertEqual([o["path"] for o in result["offenders"]], ["02-skills/folded/SKILL.md"])
                self.assertIn("block", result["offenders"][0]["error"])

    def test_a_one_line_description_starting_with_other_text_is_measured(self):
        # negative control: only a bare block indicator is refused
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "02-skills/plain/SKILL.md", _skill("> quoted but on one line", "body\n"))
            config = {"field_caps": [{"glob": "02-skills/*/SKILL.md", "field": "description", "cap": 60}]}
            result = docs_lint.check_tokens(root, config)
            self.assertEqual(result["offenders"], [])
            self.assertNotIn("error", result["ok"][0])


class McpDocsLintToolTests(unittest.TestCase):
    """The MCP `docs_lint` tool adds the token caps when the tools root ships them."""

    def _argv(self, tools_root: Path) -> list[str]:
        from mcp import catalog, registry

        spec = next(t for t in catalog.TOOLS if t.name == "docs_lint")
        return spec.argv({}, registry.Ctx(tools_root=tools_root, repo=None))

    @unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only")
    def test_kit_tools_root_passes_tokens_and_the_kit_root(self):
        argv = self._argv(TOOLS_ROOT)
        self.assertIn("--tokens", argv)
        self.assertEqual(argv[argv.index("--tokens") + 1], str(TOOLS_ROOT / "config" / "token-caps.json"))
        self.assertEqual(argv[argv.index("--root") + 1], str(KIT_ROOT))
        self.assertEqual(argv[2], str(TOOLS_ROOT / "config" / "docs-caps.json"))

    def test_instance_without_token_config_keeps_the_line_only_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "instance"
            _write(tools / "config" / "docs-caps.json", "{}")
            argv = self._argv(tools)
            self.assertNotIn("--tokens", argv)
            self.assertNotIn("--root", argv)
            self.assertEqual(argv[-1], str(tools / "config" / "docs-caps.json"))

    def test_instance_with_a_synced_token_config_but_no_kit_tree_keeps_the_line_only_call(self):
        # sync-instance.sh adds missing config files: the token globs name kit paths an instance lacks
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "instance"
            _write(tools / "config" / "docs-caps.json", "{}")
            _write(tools / "config" / "token-caps.json", "{}")
            self.assertNotIn("--tokens", self._argv(tools))


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only: an instance has no skills tree")
class KitTokenCapsTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((TOOLS_ROOT / "config" / "token-caps.json").read_text(encoding="utf-8"))

    def test_config_holds_the_budget_values(self):
        self.assertEqual(self.config["method"], "ceil(chars/4)")
        caps = self.config["token_caps"]
        self.assertEqual(caps["AGENTS.md"], 600)
        self.assertEqual(caps["CLAUDE.md"], 60)
        self.assertEqual(caps["04-templates/brief.md"], 300)
        self.assertEqual(caps["CONTEXT-PACK.md"], 1800)
        fields = {(f["glob"], f.get("field") or f.get("part")): f["cap"] for f in self.config["field_caps"]}
        self.assertEqual(fields[("02-skills/*/SKILL.md", "description")], 60)
        self.assertEqual(fields[("02-skills/*/SKILL.md", "body")], 1000)
        self.assertLessEqual(fields[("01-roles/agents/generic-*.md", "body")], 900)

    def test_every_skill_description_fits_its_cap(self):
        config = {"field_caps": [f for f in self.config["field_caps"] if f.get("field") == "description"]}
        result = docs_lint.check_tokens(KIT_ROOT, config)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["offenders"], [])
        self.assertGreaterEqual(len(result["ok"]), 16)

    def test_the_shipped_token_caps_hold_on_the_kit(self):
        # every shipped cap, not only the descriptions: a body or file over its cap fails the suite
        result = docs_lint.check_tokens(KIT_ROOT, self.config)
        self.assertEqual(result["offenders"], [])
        self.assertEqual(result["missing"], [])
        self.assertGreaterEqual(len(result["ok"]), 4 + 11 + 16 + 16)


if __name__ == "__main__":
    unittest.main()
