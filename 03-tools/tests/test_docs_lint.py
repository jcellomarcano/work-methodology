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


if __name__ == "__main__":
    unittest.main()
