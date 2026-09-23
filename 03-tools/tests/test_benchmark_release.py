import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import baseline, benchmark_release as br

TOOLS_ROOT = Path(__file__).resolve().parent.parent

STYLE_GUIDE_MAP = {
    "ARCH-004": ["files_over_500"],
    "ARCH-006": [],
    "LOG-001": ["android_util_log_count"],
}
PROPERTY_HIERARCHY = {
    "schema_version": "1.0",
    "status": "v1 unreviewed (Asumido)",
    "property_order": ["Auditability", "Security"],
    "rules": {
        "ARCH-004": {"property": "Auditability", "epistemic": "Asumido", "why": "x"},
        "LOG-001": {"property": "Security", "epistemic": "Asumido", "why": "x"},
        "ARCH-006": {"property": "Integrity", "epistemic": "Asumido", "why": "x"},
    },
}


def _metrics(files_over_500: int, android_log: int, loc: int, tests: int) -> dict:
    return {
        "totals": {
            "loc": loc, "non_blank_loc": loc, "fun_count": 10, "var_count": 1,
            "bang_bang_count": 0, "lateinit_count": 0, "global_scope_count": 0,
            "run_blocking_count": 0, "android_util_log_count": android_log,
            "log_call_count": android_log, "println_count": 0, "print_stack_trace_count": 0,
            "else_arrow_count": 0, "files_count": 5, "files_over_500": files_over_500,
        },
        "rule_signals": {
            "ARCH-004": files_over_500, "ARCH-006": None, "LOG-001": android_log,
        },
        "test_counts_by_module": {"app": tests, "domain": 1},
    }


def _duplication(cluster_tokens: list) -> dict:
    return {"clusters": [{"tokens": t, "lines": 10, "occurrences": []} for t in cluster_tokens], "pairwise": {}}


def _deps(n_violations: int) -> dict:
    return {"violations": [{"file": f"f{i}.kt", "line": 1, "import": "x", "from_node": "a",
                             "to_node": "b", "rule": "r"} for i in range(n_violations)],
            "cycle_candidates": {}, "adapter_law_candidates": []}


def _domain_invariants(**counts) -> dict:
    return {"by_invariant": {
        name: {"epistemic": "Inferido", "note": "", "evidence": [{"file": f"f{i}.kt", "line": i} for i in range(n)]}
        for name, n in counts.items()
    }}


def _write_sha_payloads(sha: str, metrics: dict, duplication: dict, deps: dict, domain_invariants: dict) -> None:
    out_dir = TOOLS_ROOT / "out" / sha
    baseline.write_json(out_dir / "metrics.json", metrics)
    baseline.write_json(out_dir / "duplication.json", duplication)
    baseline.write_json(out_dir / "deps.json", deps)
    baseline.write_json(out_dir / "domain-invariants.json", domain_invariants)


class DuplicationSummaryTests(unittest.TestCase):
    def test_counts_clusters_and_sums_tokens(self):
        result = br.duplication_summary(_duplication([50, 75]))
        self.assertEqual(result, {"clusters": 2, "tokens": 125})

    def test_empty_clusters_is_zero_not_an_error(self):
        self.assertEqual(br.duplication_summary(_duplication([])), {"clusters": 0, "tokens": 0})


class RuleDeltasTests(unittest.TestCase):
    def test_arch_006_comes_from_duplication_not_rule_signals(self):
        metrics_a, metrics_b = _metrics(1, 0, 100, 5), _metrics(1, 0, 100, 5)
        dup_a, dup_b = _duplication([50]), _duplication([50, 60])
        by_rule, _unmapped = br.rule_deltas(STYLE_GUIDE_MAP, metrics_a, metrics_b, dup_a, dup_b)
        self.assertEqual(by_rule["ARCH-006"]["before"], {"clusters": 1, "tokens": 50})
        self.assertEqual(by_rule["ARCH-006"]["after"], {"clusters": 2, "tokens": 110})
        self.assertEqual(by_rule["ARCH-006"]["delta"], {"clusters": 1, "tokens": 60})

    def test_mapped_rule_delta_from_rule_signals(self):
        metrics_a, metrics_b = _metrics(3, 0, 100, 5), _metrics(1, 0, 100, 5)
        by_rule, _ = br.rule_deltas(STYLE_GUIDE_MAP, metrics_a, metrics_b, _duplication([]), _duplication([]))
        self.assertEqual(by_rule["ARCH-004"], {"before": 3, "after": 1, "delta": -2})

    def test_every_metric_maps_or_is_unmapped(self):
        # negative control: no shape_metrics metric may disappear
        # without going through either 'mapped' or 'unmapped'.
        metrics_a, metrics_b = _metrics(1, 2, 100, 5), _metrics(1, 2, 100, 5)
        by_rule, unmapped = br.rule_deltas(STYLE_GUIDE_MAP, metrics_a, metrics_b, _duplication([]), _duplication([]))
        mapped_names = {name for names in STYLE_GUIDE_MAP.values() for name in names}
        all_names = set(metrics_a["totals"])
        for name in all_names:
            self.assertTrue(name in mapped_names or name in unmapped, f"{name} se perdió")

    def test_unmapped_metric_has_correct_delta(self):
        metrics_a, metrics_b = _metrics(1, 0, 100, 5), _metrics(1, 0, 150, 5)
        _by_rule, unmapped = br.rule_deltas(STYLE_GUIDE_MAP, metrics_a, metrics_b, _duplication([]), _duplication([]))
        self.assertEqual(unmapped["loc"], {"before": 100, "after": 150, "delta": 50})


DIRECTION_STYLE_MAP = {
    "metric_directions": {
        "loc": "neutral",
        "files_over_500": "lower_is_better",
        "tests_total": "higher_is_better",
    }
}


def _direction_payload(totals_changed=None, dup_delta=None, dep_delta=0, tests_delta=0, domain_invariants_delta=None) -> dict:
    return {
        "totals_delta": {"added": [], "removed": [], "changed": totals_changed or {}},
        "by_rule": {"ARCH-006": {"delta": dup_delta or {"clusters": 0, "tokens": 0}}},
        "dep_violations": {"delta": dep_delta},
        "tests_total": {"delta": tests_delta},
        "domain_invariants_delta": domain_invariants_delta or {},
    }


class ByDirectionTests(unittest.TestCase):
    def test_neutral_metric_never_appears_under_mejora_or_empeora(self):
        # negative control: reproduces the measured defect ("loc: +9369" under
        # "Qué mejora"): loc is neutral, so a delta of it must not
        # appear in either mejora or empeora, only in sin_direccion.
        payload = _direction_payload({"totals.loc": {"before": 100, "after": 9469, "delta": 9369}})
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        self.assertNotIn("loc", {e["metric"] for e in result["mejora"]})
        self.assertNotIn("loc", {e["metric"] for e in result["empeora"]})
        self.assertIn("loc", {e["metric"] for e in result["sin_direccion"]})

    def test_lower_is_better_metric_with_positive_delta_is_empeora(self):
        payload = _direction_payload({"totals.files_over_500": {"before": 1, "after": 4, "delta": 3}})
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        self.assertIn("files_over_500", {e["metric"] for e in result["empeora"]})
        self.assertNotIn("files_over_500", {e["metric"] for e in result["mejora"]})

    def test_lower_is_better_metric_with_negative_delta_is_mejora(self):
        payload = _direction_payload({"totals.files_over_500": {"before": 4, "after": 1, "delta": -3}})
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        self.assertIn("files_over_500", {e["metric"] for e in result["mejora"]})
        self.assertNotIn("files_over_500", {e["metric"] for e in result["empeora"]})

    def test_higher_is_better_metric_with_negative_delta_is_empeora(self):
        payload = _direction_payload(tests_delta=-5)
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        self.assertIn("tests_total", {e["metric"] for e in result["empeora"]})

    def test_zero_delta_is_listed_in_no_bucket(self):
        payload = _direction_payload({"totals.loc": {"before": 100, "after": 100, "delta": 0}})
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        all_metrics = {e["metric"] for bucket in result.values() for e in bucket}
        self.assertNotIn("loc", all_metrics)

    def test_metric_without_declared_direction_is_ignored(self):
        payload = _direction_payload({"totals.unknown_metric": {"before": 1, "after": 2, "delta": 1}})
        result = br.by_direction(DIRECTION_STYLE_MAP, payload)
        all_metrics = {e["metric"] for bucket in result.values() for e in bucket}
        self.assertNotIn("unknown_metric", all_metrics)


class RenderMarkdownDirectionSectionsTests(unittest.TestCase):
    def _base_content(self) -> dict:
        return {
            "ref_a": "vOLD", "ref_b": "vNEW", "sha_a": "a" * 40, "sha_b": "b" * 40,
            "totals_delta": {"added": [], "removed": [], "changed": {}},
            "tests_total": {"before": 1, "after": 1, "delta": 0},
            "dep_violations": {"before": 0, "after": 0, "delta": 0},
            "by_rule": {"ARCH-006": {
                "before": {"clusters": 0, "tokens": 0}, "after": {"clusters": 0, "tokens": 0},
                "delta": {"clusters": 0, "tokens": 0},
            }},
            "unmapped_metrics": {},
            "by_property": {"status": "x", "property_order": [], "groups": {}},
            "domain_invariants_delta": {},
            "change_cards": {"commits_with_card": 0, "k_of_n": "0-of-0", "cards": []},
            "not_measured": [],
            "tool_versions": {"python": "3.11"},
        }

    def test_three_sections_exist_and_neutral_metric_lands_only_in_its_own(self):
        # Uses the real config: loc is neutral there (config/style-guide-map.json),
        # same as in the measured defect.
        real_style_map = baseline.load_json(TOOLS_ROOT / "config" / "style-guide-map.json")
        content = self._base_content()
        content["totals_delta"]["changed"]["totals.loc"] = {"before": 100, "after": 9469, "delta": 9369}
        content["by_direction"] = br.by_direction(real_style_map, content)
        text = br.render_markdown(content)

        self.assertIn("## What improves", text)
        self.assertIn("## What gets worse", text)
        self.assertIn("## Changes without direction", text)

        mejora_section = text.split("## What improves")[1].split("## What gets worse")[0]
        empeora_section = text.split("## What gets worse")[1].split("## Changes without direction")[0]
        sin_direccion_section = text.split("## Changes without direction")[1]

        self.assertNotIn("loc:", mejora_section)
        self.assertNotIn("loc:", empeora_section)
        self.assertIn("loc: +9369", sin_direccion_section)

    def test_lower_is_better_metric_with_positive_delta_lands_in_empeora_section(self):
        real_style_map = baseline.load_json(TOOLS_ROOT / "config" / "style-guide-map.json")
        content = self._base_content()
        content["totals_delta"]["changed"]["totals.files_over_500"] = {"before": 1, "after": 4, "delta": 3}
        content["by_direction"] = br.by_direction(real_style_map, content)
        text = br.render_markdown(content)

        mejora_section = text.split("## What improves")[1].split("## What gets worse")[0]
        empeora_section = text.split("## What gets worse")[1].split("## Changes without direction")[0]
        self.assertNotIn("files_over_500:", mejora_section)
        self.assertIn("files_over_500: +3", empeora_section)


class PropertyGroupsTests(unittest.TestCase):
    def test_groups_rules_by_declared_property_in_order(self):
        by_rule = {"ARCH-004": {"delta": -2}, "LOG-001": {"delta": 1}}
        result = br.property_groups(PROPERTY_HIERARCHY, by_rule)
        self.assertEqual(result["property_order"], ["Auditability", "Security"])
        self.assertEqual(set(result["groups"]["Auditability"]), {"ARCH-004"})
        self.assertEqual(set(result["groups"]["Security"]), {"LOG-001"})

    def test_property_not_in_property_order_still_surfaces(self):
        # negative control: ARCH-006 -> "Integrity", which is NOT in
        # this fixture's property_order; it must not be silently lost.
        by_rule = {"ARCH-006": {"delta": {"clusters": 1, "tokens": 10}}}
        result = br.property_groups(PROPERTY_HIERARCHY, by_rule)
        self.assertIn("Integrity", result["groups"])
        self.assertIn("ARCH-006", result["groups"]["Integrity"])

    def test_rule_without_metadata_falls_back(self):
        by_rule = {"UNKNOWN-999": {"delta": 1}}
        result = br.property_groups(PROPERTY_HIERARCHY, by_rule)
        self.assertIn("(no property assigned)", result["groups"])

    def test_empty_property_order_entries_still_reported(self):
        by_rule = {"LOG-001": {"delta": 1}}
        result = br.property_groups(PROPERTY_HIERARCHY, by_rule)
        # Auditability has no rule in this by_rule, but it still
        # appears (empty) because it is in property_order.
        self.assertEqual(result["groups"]["Auditability"], {})

    def test_status_is_carried_through(self):
        result = br.property_groups(PROPERTY_HIERARCHY, {})
        self.assertEqual(result["status"], "v1 unreviewed (Asumido)")


class ParseCommitLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.repo / "f.txt").write_text("1", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "chore: init")
        self.sha_base = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, message: str) -> str:
        (self.repo / "f.txt").write_text(message, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-am", message], check=True)
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

    def test_parses_multiline_body_correctly(self):
        multi = "feat: algo\n\nsegunda línea\ntercera línea"
        sha = self._commit(multi)
        commits = br.parse_commit_log(self.repo, f"{self.sha_base}..{sha}")
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["sha"], sha)
        self.assertIn("segunda línea", commits[0]["body"])

    def test_range_excludes_base(self):
        sha = self._commit("feat: uno")
        commits = br.parse_commit_log(self.repo, f"{self.sha_base}..{sha}")
        shas = [c["sha"] for c in commits]
        self.assertNotIn(self.sha_base, shas)


class ChangeCardSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)

        self.git = git
        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.repo / "f.txt").write_text("0", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "chore: init")
        self.sha_base = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, n: int, message: str) -> str:
        (self.repo / "f.txt").write_text(str(n), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-am", message], check=True)
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

    def test_k_of_n_zero_when_no_commit_has_a_card(self):
        self._commit(1, "feat(payment): sin ficha en absoluto")
        self._commit(2, "fix: tampoco esta")
        sha_tip = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        result = br.change_card_summary(self.repo, f"{self.sha_base}..{sha_tip}")
        self.assertEqual(result["k_of_n"], "0-of-2")
        self.assertEqual(result["commits_with_card"], 0)
        self.assertEqual(result["cards"], [])

    def test_harvests_for_what_and_invariant_from_a_real_card(self):
        card = (
            "feat(payment): algo\n\n"
            "**Why**: reason [Medido]\n"
            "**For what**: Data integrity [Medido]\n"
            "**What it risks**: double charge [Probado]\n"
            "**When**: always [Medido]\n"
            "**How**: with a guard [Probado]\n"
            "**How far**: refund only [Asumido]\n"
            "**How we'll know**: test [Probado]\n"
            "**Invariant**: INV-07\n"
            "**Ticket**: DEV-1\n"
        )
        self._commit(1, card)
        sha_tip = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        result = br.change_card_summary(self.repo, f"{self.sha_base}..{sha_tip}")
        self.assertEqual(result["k_of_n"], "1-of-1")
        self.assertEqual(result["cards"][0]["for_what"], "Data integrity [Medido]")
        self.assertEqual(result["cards"][0]["invariant"], "INV-07")
        self.assertEqual(result["cards"][0]["verdict"], "PASS")


class DomainInvariantsDeltaTests(unittest.TestCase):
    def test_computes_before_after_delta_per_field(self):
        before = _domain_invariants(guards=2, journal_files=0)
        after = _domain_invariants(guards=5, journal_files=1)
        result = br.domain_invariants_delta(before, after)
        self.assertEqual(result["guards"], {"before": 2, "after": 5, "delta": 3})
        self.assertEqual(result["journal_files"], {"before": 0, "after": 1, "delta": 1})


class BuildBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

        def git(*args):
            return subprocess.run(
                ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True
            ).stdout.strip()

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.repo / "f.txt").write_text("0", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "chore: init")
        self.sha_a = git("rev-parse", "HEAD")
        (self.repo / "f.txt").write_text("1", encoding="utf-8")
        git("commit", "-q", "-am", "feat: sin ficha")
        self.sha_b = git("rev-parse", "HEAD")

        _write_sha_payloads(
            self.sha_a, _metrics(3, 2, 500, 10), _duplication([50, 60]), _deps(4), _domain_invariants(guards=1),
        )
        _write_sha_payloads(
            self.sha_b, _metrics(1, 0, 400, 15), _duplication([50]), _deps(1), _domain_invariants(guards=3),
        )

    def tearDown(self):
        self.tmp.cleanup()
        shutil.rmtree(TOOLS_ROOT / "out" / self.sha_a, ignore_errors=True)
        shutil.rmtree(TOOLS_ROOT / "out" / self.sha_b, ignore_errors=True)

    def test_uses_real_repo_config_and_produces_full_payload(self):
        content = br.build_benchmark(TOOLS_ROOT, self.repo, self.sha_a, self.sha_b, "vOLD", "vNEW")
        self.assertEqual(content["sha_a"], self.sha_a)
        self.assertEqual(content["sha_b"], self.sha_b)
        self.assertEqual(content["dep_violations"], {"before": 4, "after": 1, "delta": -3})
        self.assertEqual(content["tests_total"], {"before": 11, "after": 16, "delta": 5})
        self.assertEqual(content["change_cards"]["commits_with_card"], 0)
        self.assertEqual(len(content["not_measured"]), 7)
        self.assertIn("by_rule", content)
        self.assertIn("by_property", content)
        self.assertIn("domain_invariants_delta", content)

    def test_determinism(self):
        first = br.build_benchmark(TOOLS_ROOT, self.repo, self.sha_a, self.sha_b, "vOLD", "vNEW")
        second = br.build_benchmark(TOOLS_ROOT, self.repo, self.sha_a, self.sha_b, "vOLD", "vNEW")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_render_markdown_mentions_zero_cards_plainly(self):
        content = br.build_benchmark(TOOLS_ROOT, self.repo, self.sha_a, self.sha_b, "vOLD", "vNEW")
        content["tool_versions"] = {"python": "3.11"}
        text = br.render_markdown(content)
        self.assertIn("No commit in the range carries a change card", text)
        self.assertIn("0-of-1", text)

    def test_before_after_columns_never_get_a_plus_sign(self):
        # negative control: ARCH-004 before=3 (positive) must not come out "+3"
        # in the before/after columns: that would suggest a change that is not one.
        content = br.build_benchmark(TOOLS_ROOT, self.repo, self.sha_a, self.sha_b, "vOLD", "vNEW")
        content["tool_versions"] = {"python": "3.11"}
        text = br.render_markdown(content)
        self.assertIn("| ARCH-004 | 3 | 1 | -2 |", text)


class ResolveShaTests(unittest.TestCase):
    def test_resolves_a_real_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            (repo / "f.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
            expected = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            self.assertEqual(br.resolve_sha(repo, "HEAD"), expected)

    def test_unresolvable_ref_exits_loudly_without_fetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            (repo / "f.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
            # negative control: a ref that does not exist must fail clean, never invent a sha.
            with self.assertRaises(SystemExit):
                br.resolve_sha(repo, "no-existe-esta-rama")


if __name__ == "__main__":
    unittest.main()
