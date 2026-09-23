"""derive() is pure: one row per decision-table case, with a negative
control where the change card tries to lower the lane and the path wins."""
import json
import unittest

from lib import rdd_risk

CONFIG = {
    "shared_build_files": ["settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle"],
    "money_paths": ["payment/", "framework/payment/"],
    "rdd": {
        "exempt_globs": ["**/*.md", "docs/**"],
        "tests_globs": ["**/src/test/**"],
        "low_max_changed_lines": 120,
        "lens_paths": {
            "flujo-critico": ["**/*Repository*.kt"],
            "jamas-peor-que-antes": ["**/di/**"],
            "tests-anti-flake": ["**/src/test/**"],
        },
    },
}


def _inputs(paths, routing="sonnet", what_it_risks="UX", added=10, removed=2, has_card=True):
    return {"touched_paths": paths, "routing": routing, "what_it_risks": what_it_risks,
            "added": added, "removed": removed, "has_change_card": has_card}


class DecisionTableTests(unittest.TestCase):
    def test_no_paths_is_exempt(self):
        result = rdd_risk.derive(_inputs([]), CONFIG)
        self.assertEqual(result["tier"], "exempt")
        self.assertEqual(result["lenses"], [])

    def test_shared_build_file_is_high_with_owner_gate(self):
        result = rdd_risk.derive(_inputs(["app/build.gradle"], what_it_risks="none"), CONFIG)
        self.assertEqual(result["tier"], "high")
        self.assertTrue(result["owner_gate"])
        self.assertEqual(result["consent"], "pending")

    def test_money_path_is_high_even_with_cosmetic_card(self):
        # negative control: the change card says UX/none, the path wins
        result = rdd_risk.derive(_inputs(["payment/api/Foo.kt"], what_it_risks="none"), CONFIG)
        self.assertEqual(result["tier"], "high")
        self.assertEqual(result["lenses"], list(rdd_risk.LENS_ORDER))
        self.assertIsNone(result["lens_focus"])

    def test_opus_routing_is_high(self):
        result = rdd_risk.derive(_inputs(["domain/Foo.kt"], routing="opus"), CONFIG)
        self.assertEqual(result["tier"], "high")

    def test_docs_only_is_exempt_including_root_readme(self):
        result = rdd_risk.derive(_inputs(["README.md", "docs/x.md"]), CONFIG)
        self.assertEqual(result["tier"], "exempt")

    def test_tests_only_is_low(self):
        result = rdd_risk.derive(_inputs(["domain/src/test/FooTest.kt", "README.md"]), CONFIG)
        self.assertEqual(result["tier"], "low")
        self.assertEqual(result["consent"], "n/a")

    def test_no_card_is_medium(self):
        result = rdd_risk.derive(_inputs(["domain/Foo.kt"], has_card=False), CONFIG)
        self.assertEqual(result["tier"], "medium")

    def test_no_risk_small_diff_is_low(self):
        result = rdd_risk.derive(_inputs(["domain/Foo.kt"], what_it_risks="none", added=50, removed=20), CONFIG)
        self.assertEqual(result["tier"], "low")

    def test_no_risk_but_big_diff_is_medium(self):
        # negative control: same as above, but 121 lines
        result = rdd_risk.derive(_inputs(["domain/Foo.kt"], what_it_risks="none", added=100, removed=21), CONFIG)
        self.assertEqual(result["tier"], "medium")

    def test_default_is_medium_with_one_lens(self):
        result = rdd_risk.derive(_inputs(["domain/Foo.kt"]), CONFIG)
        self.assertEqual(result["tier"], "medium")
        self.assertEqual(result["lenses"], ["simplicidad"])
        self.assertEqual(result["lens_focus"], "simplicidad")


class LensTests(unittest.TestCase):
    def test_flujo_critico_wins_over_the_rest(self):
        result = rdd_risk.derive(_inputs(["domain/FooRepository.kt", "app/di/Module.kt"]), CONFIG)
        self.assertEqual(result["lens_focus"], "flujo-critico")

    def test_di_path_picks_jamas_peor_que_antes(self):
        result = rdd_risk.derive(_inputs(["app/di/Module.kt", "domain/Foo.kt"]), CONFIG)
        self.assertEqual(result["lens_focus"], "jamas-peor-que-antes")


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_json(self):
        inputs = _inputs(["b.kt", "a.kt"])
        first = json.dumps(rdd_risk.derive(inputs, CONFIG), sort_keys=True)
        second = json.dumps(rdd_risk.derive(dict(inputs), CONFIG), sort_keys=True)
        self.assertEqual(first, second)
        self.assertEqual(rdd_risk.derive(inputs, CONFIG)["inputs"]["touched_paths"], ["a.kt", "b.kt"])

    def test_reasons_are_never_empty(self):
        for paths in ([], ["README.md"], ["domain/Foo.kt"], ["payment/x.kt"]):
            self.assertTrue(rdd_risk.derive(_inputs(paths), CONFIG)["reasons"])


class GlobMatchTests(unittest.TestCase):
    def test_double_star_prefix_matches_root_file(self):
        self.assertTrue(rdd_risk.glob_match("README.md", "**/*.md"))
        self.assertTrue(rdd_risk.glob_match("a/b/README.md", "**/*.md"))

    def test_kotlin_file_does_not_match_md_glob(self):
        # negative control
        self.assertFalse(rdd_risk.glob_match("a/Foo.kt", "**/*.md"))
