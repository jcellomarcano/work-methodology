import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import baseline, clean_pass

TOOLS_ROOT = Path(__file__).resolve().parent.parent
FAKE_SHA = "0clean000000000000000000000000000test00"


def _file_metrics(path: str, loc: int, var_count: int = 0, lateinit_count: int = 0,
                   hist: dict | None = None) -> dict:
    histogram = {"1-20": 0, "21-50": 0, "51-100": 0, "101+": 0}
    histogram.update(hist or {})
    return {
        "path": path, "module": "app", "loc": loc, "non_blank_loc": loc,
        "fun_count": 1, "fun_length_histogram": histogram, "var_count": var_count,
        "bang_bang_count": 0, "lateinit_count": lateinit_count, "global_scope_count": 0,
        "run_blocking_count": 0, "android_util_log_count": 0, "log_call_count": 0,
        "println_count": 0, "print_stack_trace_count": 0, "else_arrow_count": 0,
    }


FAKE_METRICS = {
    "files": [
        _file_metrics("app/Big.kt", 600),
        _file_metrics("app/Small.kt", 50),
        _file_metrics("app/LongFun.kt", 200, hist={"51-100": 1}),
        _file_metrics("app/VeryLongFun.kt", 300, hist={"101+": 2}),
        _file_metrics("app/Vary.kt", 50, var_count=9),
        _file_metrics("app/Vary2.kt", 50, var_count=4),
        _file_metrics("app/Lat.kt", 50, lateinit_count=3),
    ],
}
FAKE_DUPLICATION = {
    "clusters": [
        {"tokens": 80, "lines": 20, "occurrences": [
            {"file": "app/A.kt", "start_line": 1, "end_line": 20},
            {"file": "app/B.kt", "start_line": 5, "end_line": 24},
        ]},
    ],
}
FAKE_DEPS = {
    "violations": [
        {"file": "domain/Bad.kt", "line": 3, "import": "android.os.Bundle",
         "from_node": "domain", "to_node": "android.os.Bundle", "rule": "domain-purity"},
    ],
}


class FilesOverLocTests(unittest.TestCase):
    def test_flags_only_files_over_threshold(self):
        result = clean_pass._files_over_loc(FAKE_METRICS, 500)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file"], "app/Big.kt")
        self.assertEqual(result[0]["rule"], "files-over-500")

    def test_file_exactly_at_threshold_is_not_flagged(self):
        metrics = {"files": [_file_metrics("app/Exact.kt", 500)]}
        # negative control: loc == umbral no debe marcarse (es "over", estricto)
        self.assertEqual(clean_pass._files_over_loc(metrics, 500), [])


class LongFunctionsByFileTests(unittest.TestCase):
    def test_flags_files_with_over_length_buckets(self):
        result = clean_pass._long_functions_by_file(FAKE_METRICS)
        files = {item["file"] for item in result}
        self.assertEqual(files, {"app/LongFun.kt", "app/VeryLongFun.kt"})

    def test_clean_file_not_flagged(self):
        # negative control: a file without long functions does not show up.
        result = clean_pass._long_functions_by_file(FAKE_METRICS)
        self.assertFalse(any(item["file"] == "app/Small.kt" for item in result))


class HotspotTopNTests(unittest.TestCase):
    def test_orders_by_field_desc(self):
        result = clean_pass._hotspot_top_n(FAKE_METRICS, "var_count", "var-hotspot-top20", 20)
        self.assertEqual([r["file"] for r in result], ["app/Vary.kt", "app/Vary2.kt"])

    def test_zero_value_files_are_excluded(self):
        result = clean_pass._hotspot_top_n(FAKE_METRICS, "lateinit_count", "lateinit-hotspot-top20", 20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file"], "app/Lat.kt")

    def test_respects_top_n_limit(self):
        result = clean_pass._hotspot_top_n(FAKE_METRICS, "var_count", "var-hotspot-top20", 1)
        self.assertEqual(len(result), 1)


class DuplicationItemsTests(unittest.TestCase):
    def test_one_item_per_cluster(self):
        result = clean_pass._duplication_items(FAKE_DUPLICATION)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule"], "duplication-cluster")
        self.assertIn("app/A.kt", result[0]["detail"])
        self.assertIn("app/B.kt", result[0]["detail"])


class DepViolationItemsTests(unittest.TestCase):
    def test_one_item_per_violation_with_rule_suffix(self):
        result = clean_pass._dep_violation_items(FAKE_DEPS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule"], "dep-violation:domain-purity")
        self.assertEqual(result[0]["file"], "domain/Bad.kt")


class BuildCleanPassTests(unittest.TestCase):
    def test_union_of_all_sources(self):
        payload = clean_pass.build_clean_pass(FAKE_METRICS, FAKE_DUPLICATION, FAKE_DEPS)
        rules = {item["rule"] for item in payload["flagged_items"]}
        self.assertEqual(rules, {
            "files-over-500", "functions-over-50-file-level", "var-hotspot-top20",
            "lateinit-hotspot-top20", "duplication-cluster", "dep-violation:domain-purity",
        })
        self.assertEqual(payload["totals"]["flagged_items"], len(payload["flagged_items"]))

    def test_no_proposal_fields_present(self):
        # negative control: clean-pass proposes nothing, it only flags.
        payload = clean_pass.build_clean_pass(FAKE_METRICS, FAKE_DUPLICATION, FAKE_DEPS)
        for item in payload["flagged_items"]:
            self.assertEqual(set(item), {"rule", "file", "detail"})

    def test_determinism(self):
        first = clean_pass.build_clean_pass(FAKE_METRICS, FAKE_DUPLICATION, FAKE_DEPS)
        second = clean_pass.build_clean_pass(FAKE_METRICS, FAKE_DUPLICATION, FAKE_DEPS)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class RenderMarkdownTests(unittest.TestCase):
    def test_contains_rule_table_and_rows(self):
        content = clean_pass.build_clean_pass(FAKE_METRICS, FAKE_DUPLICATION, FAKE_DEPS)
        content["repo_sha"] = "abc123"
        text = clean_pass.render_markdown(content)
        self.assertIn("files-over-500", text)
        self.assertIn("app/Big.kt", text)


class MainCliTests(unittest.TestCase):
    def setUp(self):
        self.out_dir = TOOLS_ROOT / "out" / FAKE_SHA
        baseline.write_json(self.out_dir / "metrics.json", FAKE_METRICS)
        baseline.write_json(self.out_dir / "duplication.json", FAKE_DUPLICATION)
        baseline.write_json(self.out_dir / "deps.json", FAKE_DEPS)

        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)
        (self.repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo, check=True)

    def tearDown(self):
        self.tmp.cleanup()
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_writes_json_and_md_using_fake_sha_dir(self):
        import unittest.mock as mock

        with mock.patch.object(baseline, "git_head_sha", return_value=FAKE_SHA):
            code = clean_pass.main([str(self.repo)])
        self.assertEqual(code, 0)
        payload = json.loads((self.out_dir / "clean-pass.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["repo_sha"], FAKE_SHA)
        self.assertGreater(payload["totals"]["flagged_items"], 0)
        self.assertTrue((self.out_dir / "clean-pass.md").exists())


if __name__ == "__main__":
    unittest.main()
