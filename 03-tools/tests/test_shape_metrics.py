import json
import tempfile
import unittest
from pathlib import Path

from lib import shape_metrics

DIRTY_KT = """package pkg

import android.util.Log

class Dirty {
    var counter = 0
    lateinit var name: String

    fun risky(x: String?) {
        val len = x!!.length
        GlobalScope.launch {
            runBlocking {
                Log.d("tag", "msg")
                println("debug")
            }
        }
        try {
        } catch (e: Exception) {
            e.printStackTrace()
        }
        when (len) {
            1 -> {}
            else -> {}
        }
    }
}
"""

CLEAN_KT = """package pkg

class Clean {
    private val counter: Int = 0

    fun greet(name: String): String {
        return "hello $name"
    }
}
"""

STYLE_MAP = {
    "LOG-001": ["android_util_log_count", "log_call_count", "println_count", "print_stack_trace_count"],
    "ARCH-004": ["files_over_500"],
    "CONC-001": ["global_scope_count"],
    "KS-001": [],
}


class AnalyzeFileTests(unittest.TestCase):
    def test_detects_every_tracked_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dirty.kt"
            path.write_text(DIRTY_KT, encoding="utf-8")
            metrics = shape_metrics.analyze_file(path)
            self.assertEqual(metrics["var_count"], 2)  # "var counter" + "lateinit var name"
            self.assertEqual(metrics["bang_bang_count"], 1)
            self.assertEqual(metrics["lateinit_count"], 1)
            self.assertEqual(metrics["global_scope_count"], 1)
            self.assertEqual(metrics["run_blocking_count"], 1)
            self.assertEqual(metrics["android_util_log_count"], 1)
            self.assertEqual(metrics["log_call_count"], 1)
            self.assertEqual(metrics["println_count"], 1)
            self.assertEqual(metrics["print_stack_trace_count"], 1)
            self.assertEqual(metrics["else_arrow_count"], 1)
            self.assertEqual(metrics["fun_count"], 1)

    def test_clean_file_has_zero_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Clean.kt"
            path.write_text(CLEAN_KT, encoding="utf-8")
            metrics = shape_metrics.analyze_file(path)
            for field in (
                "var_count", "bang_bang_count", "lateinit_count", "global_scope_count",
                "run_blocking_count", "android_util_log_count", "log_call_count",
                "println_count", "print_stack_trace_count", "else_arrow_count",
            ):
                self.assertEqual(metrics[field], 0, field)
            self.assertEqual(metrics["fun_count"], 1)

    def test_word_boundary_excludes_vararg_and_variance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "V.kt"
            path.write_text("fun f(vararg xs: Int) { val variance = 1 }\n", encoding="utf-8")
            metrics = shape_metrics.analyze_file(path)
            # negative control: 'vararg'/'variance' contain "var" as a substring
            # but \bvar\b must not count them
            self.assertEqual(metrics["var_count"], 0)

    def test_fun_length_histogram_buckets_short_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "S.kt"
            path.write_text("fun f() {\n    return 1\n}\n", encoding="utf-8")
            metrics = shape_metrics.analyze_file(path)
            self.assertEqual(metrics["fun_length_histogram"]["1-20"], 1)
            self.assertEqual(metrics["fun_length_histogram"]["21-50"], 0)

    def test_fun_length_histogram_buckets_long_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L.kt"
            body = "\n".join(f"    val v{i} = {i}" for i in range(60))
            path.write_text(f"fun f() {{\n{body}\n}}\n", encoding="utf-8")
            metrics = shape_metrics.analyze_file(path)
            self.assertEqual(sum(metrics["fun_length_histogram"].values()), 1)
            self.assertEqual(metrics["fun_length_histogram"]["51-100"], 1)


class BuildMetricsTests(unittest.TestCase):
    def _make_repo(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
        (root / "app/src/main/java/pkg/Dirty.kt").parent.mkdir(parents=True, exist_ok=True)
        (root / "app/src/main/java/pkg/Dirty.kt").write_text(DIRTY_KT, encoding="utf-8")
        (root / "app/src/main/java/pkg/Clean.kt").write_text(CLEAN_KT, encoding="utf-8")
        big = "\n".join(f"// line {i}" for i in range(600))
        (root / "app/src/main/java/pkg/Big.kt").write_text(big, encoding="utf-8")
        (root / "app/src/test/java/pkg/DirtyTest.kt").parent.mkdir(parents=True, exist_ok=True)
        (root / "app/src/test/java/pkg/DirtyTest.kt").write_text(
            "class DirtyTest {\n    @Test\n    fun a() {}\n    @Test\n    fun b() {}\n}\n",
            encoding="utf-8",
        )
        (root / "app/lint-baseline.xml").write_text(
            '<issues>\n    <issue id="X"/>\n    <issue id="Y"/>\n</issues>\n', encoding="utf-8"
        )
        return root

    def test_totals_and_rule_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(tmp)
            content = shape_metrics.build_metrics(root, ["app"], STYLE_MAP)
            self.assertEqual(content["totals"]["files_count"], 3)
            self.assertEqual(content["totals"]["files_over_500"], 1)
            self.assertEqual(content["test_counts_by_module"], {"app": 2})
            self.assertEqual(content["lint_baseline_issue_count"], 2)
            self.assertEqual(
                content["rule_signals"]["LOG-001"],
                1 + 1 + 1 + 1,  # android_util_log + log_call + println + printStackTrace
            )
            self.assertEqual(content["rule_signals"]["ARCH-004"], 1)
            self.assertEqual(content["rule_signals"]["CONC-001"], 1)
            self.assertIsNone(content["rule_signals"]["KS-001"])

    def test_determinism_json_serialization_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(tmp)
            first = shape_metrics.build_metrics(root, ["app"], STYLE_MAP)
            second = shape_metrics.build_metrics(root, ["app"], STYLE_MAP)
            self.assertEqual(
                json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
            )

    def test_markdown_render_is_deterministic_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(tmp)
            content = shape_metrics.build_metrics(root, ["app"], STYLE_MAP)
            payload = {"repo_sha": "deadbeef", **content}
            first = shape_metrics.render_markdown(payload)
            second = shape_metrics.render_markdown(payload)
            self.assertEqual(first, second)
            self.assertIn("ARCH-004", first)


if __name__ == "__main__":
    unittest.main()
