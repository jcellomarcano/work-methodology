import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import domain_invariants as di


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fixture_repo(root: Path) -> None:
    _write(root / "settings.gradle", """
include ':app'
include ':payment:gateway'
include ':domain'
""")

    _write(root / "payment/gateway/src/main/kotlin/com/acme/payment/gateway/Client.kt", """
package com.acme.payment.gateway

import android.util.Log

class Client {
    private val lock = Mutex()

    fun post() {
        headers["Idempotency-Key"] = "abandon:$id"
        Log.d("tag", "posting")
    }
}
""")

    # Outside money paths: a Mutex( and a Log.d here must NOT count
    # as a "money"-scoped signal.
    _write(root / "app/src/main/kotlin/com/acme/app/ui/CardScreen.kt", """
package com.acme.app.ui

import android.util.Log

class CardScreen {
    private val lock = Mutex()
    fun render() { Log.d("tag", "render") }
}
""")

    # Outside money paths: an "all"-scoped signal SHOULD count
    # (it is not restricted to money_paths).
    _write(root / "app/src/main/kotlin/com/acme/app/usecases/RetryUseCase.kt", """
package com.acme.app.usecases

fun run(id: String) = IdempotencyKey("late-approval:$id")
""")

    _write(root / "domain/src/main/kotlin/com/acme/domain/Foo.kt", """
package com.acme.domain

fun noop() {}
""")


def _fixture_invariants_config() -> dict:
    return {
        "invariants": {
            "INV-01": {
                "epistemic": "Medido",
                "note": "idempotency across the whole repo, guards only on money paths",
                "signals": [
                    {"kind": "IdempotencyKey(", "regex": r"IdempotencyKey\(", "scope": "all", "match": "line"},
                    {"kind": "Mutex(", "regex": r"\bMutex\(", "scope": "money", "match": "line"},
                ],
            },
            "INV-02": {"epistemic": "Desconocido", "note": "no script check yet", "signals": []},
            "INV-04": {
                "epistemic": "Medido",
                "note": "ficheros *Journal*.kt, esperado NONE hoy",
                "signals": [
                    {"kind": "journal-file", "regex": "Journal", "scope": "all", "match": "filename"},
                ],
            },
            "INV-10": {
                "epistemic": "Medido",
                "note": "logging inside money paths",
                "signals": [
                    {"kind": "Log.call", "regex": r"Log\.[dweiv]\(", "scope": "money", "match": "line"},
                ],
            },
        }
    }


MONEY_PATHS = ["payment/"]


class StripCommentsTests(unittest.TestCase):
    def test_line_comment_is_blanked_but_code_before_it_survives(self):
        src = "val a = 1 // marker\nval b = 2\n"
        result = di.strip_comments(src)
        self.assertNotIn("marker", result)
        self.assertIn("val a = 1", result)
        self.assertIn("val b = 2", result)

    def test_line_count_is_preserved(self):
        src = "a\n// b marker\nc\n/* d\ne */\nf\n"
        result = di.strip_comments(src)
        self.assertEqual(result.count("\n"), src.count("\n"))
        self.assertEqual(len(result.splitlines()), len(src.splitlines()))

    def test_multiline_block_comment_is_blanked_non_greedily(self):
        src = "before()\n/* comment one */ code() /* comment two */\nafter()\n"
        result = di.strip_comments(src)
        self.assertIn("before()", result)
        self.assertIn("code()", result)
        self.assertIn("after()", result)
        self.assertNotIn("comment one", result)
        self.assertNotIn("comment two", result)

    def test_kdoc_line_is_blanked(self):
        src = (
            "/**\n"
            " * a mention inside a doc comment, on purpose\n"
            " */\n"
            "private fun realCode() {}\n"
        )
        result = di.strip_comments(src)
        lines = result.splitlines()
        self.assertNotIn("mention", lines[1])
        self.assertIn("realCode", lines[3])


class AllMainFilesTests(unittest.TestCase):
    def test_finds_files_across_declared_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_fixture_repo(root)
            files = di.all_main_files(root)
            self.assertIn("payment/gateway/src/main/kotlin/com/acme/payment/gateway/Client.kt", files)
            self.assertIn("domain/src/main/kotlin/com/acme/domain/Foo.kt", files)


class MoneyScopedTests(unittest.TestCase):
    def test_filters_by_prefix(self):
        files = ["payment/a.kt", "app/b.kt", "payment/gateway/c.kt"]
        self.assertEqual(di.money_scoped(files, ["payment/"]), ["payment/a.kt", "payment/gateway/c.kt"])

    def test_empty_money_paths_returns_empty(self):
        # negative control: with no money_paths configured, nothing is "money".
        self.assertEqual(di.money_scoped(["payment/a.kt"], []), [])


class BuildDomainInvariantsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _build_fixture_repo(self.root)
        self.config = _fixture_invariants_config()
        self.payload = di.build_domain_invariants(self.root, self.config, MONEY_PATHS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_scoped_signal_found_outside_money_paths(self):
        evidence = self.payload["by_invariant"]["INV-01"]["evidence"]
        kinds = {(h["file"], h["kind"]) for h in evidence}
        self.assertIn(
            ("app/src/main/kotlin/com/acme/app/usecases/RetryUseCase.kt", "IdempotencyKey("), kinds
        )

    def test_money_scoped_signal_excludes_files_outside_money_paths(self):
        evidence = self.payload["by_invariant"]["INV-01"]["evidence"]
        files_with_mutex = {h["file"] for h in evidence if h["kind"] == "Mutex("}
        self.assertIn("payment/gateway/src/main/kotlin/com/acme/payment/gateway/Client.kt", files_with_mutex)
        # negative control: the Mutex( in app/ui/CardScreen.kt is outside money paths.
        self.assertNotIn("app/src/main/kotlin/com/acme/app/ui/CardScreen.kt", files_with_mutex)

    def test_log_signal_is_scoped_to_money_paths(self):
        evidence = self.payload["by_invariant"]["INV-10"]["evidence"]
        files = {h["file"] for h in evidence}
        self.assertIn("payment/gateway/src/main/kotlin/com/acme/payment/gateway/Client.kt", files)
        # negative control: the Log.d in app/ui/CardScreen.kt must not appear.
        self.assertNotIn("app/src/main/kotlin/com/acme/app/ui/CardScreen.kt", files)

    def test_filename_match_signal_reports_no_line(self):
        # positive negative control: with no *Journal*.kt in the fixture, honestly empty evidence.
        self.assertEqual(self.payload["by_invariant"]["INV-04"]["evidence"], [])

    def test_filename_match_signal_detects_when_present(self):
        _write(self.root / "app/src/main/kotlin/com/acme/app/framework/RefundJournal.kt", "package com.acme.app.framework\n")
        payload = di.build_domain_invariants(self.root, self.config, MONEY_PATHS)
        evidence = payload["by_invariant"]["INV-04"]["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0]["file"].endswith("RefundJournal.kt"))
        self.assertNotIn("line", evidence[0])

    def test_unchecked_invariant_is_desconocido_with_empty_evidence(self):
        entry = self.payload["by_invariant"]["INV-02"]
        self.assertEqual(entry["epistemic"], "Desconocido")
        self.assertEqual(entry["evidence"], [])

    def test_by_invariant_only_covers_configured_ids(self):
        # unlike the original script (which enumerated a fixed range of
        # payment invariant ids), the generic engine only reports the
        # ids the config declares.
        self.assertEqual(set(self.payload["by_invariant"]), {"INV-01", "INV-02", "INV-04", "INV-10"})

    def test_determinism(self):
        first = di.build_domain_invariants(self.root, self.config, MONEY_PATHS)
        second = di.build_domain_invariants(self.root, self.config, MONEY_PATHS)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class MainCliTests(unittest.TestCase):
    def test_main_writes_json_and_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_fixture_repo(root)

            config_path = root / "invariants-checks.json"
            config_path.write_text(json.dumps(_fixture_invariants_config()), encoding="utf-8")
            project_config_path = root / "project.json"
            project_config_path.write_text(json.dumps({"money_paths": MONEY_PATHS}), encoding="utf-8")

            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
            repo_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()

            code = di.main([str(root), "--config", str(config_path), "--project-config", str(project_config_path)])
            self.assertEqual(code, 0)

            out_dir = di.TOOLS_ROOT / "out" / repo_sha
            self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
            payload = json.loads((out_dir / "domain-invariants.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["repo_sha"], repo_sha)
            self.assertIn("by_invariant", payload)
            self.assertTrue((out_dir / "domain-invariants.md").exists())


if __name__ == "__main__":
    unittest.main()
