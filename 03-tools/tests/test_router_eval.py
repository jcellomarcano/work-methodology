"""lib/router_eval.py scores router.route() against the fixtures in
tests/fixtures/router/ with the real catalog. Positive control: every
shipped fixture passes and every reachable rule id is covered. Negative
controls: a wrong expected roster fails with roles_missing/roles_extra and
exit 1; an effort or tier mismatch is reported above/below; a cost cap is
enforced. Determinism: two CLI runs are byte-identical. The Argon price
change across 2026-12-01 is checked with a catalog fixture, because the real
catalog admits no Argon roster (it is a candidate, trial slot off)."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import baseline, router, router_eval

TOOLS = Path(__file__).resolve().parent.parent
FIXTURES = TOOLS / "tests" / "fixtures" / "router"
CATALOG = baseline.load_json(TOOLS / "config" / "model-tiers.json")
EVAL = TOOLS / "lib" / "router_eval.py"

B3_FIXTURE = {
    "name": "b3-tmp",
    "as_of": "2026-10-16",
    "input": {"task_kind": "implement", "tier": "medium", "lane": "sonnet", "map_age_days": 1, "modules": 1},
    "expect": {
        "rule": "B3",
        "status": "ok",
        "roster": [
            {"role": "generic-proposer", "model": "claude-sonnet-5-5", "effort": "medium", "launch": "run"},
            {"role": "generic-verifier", "model": "claude-sonnet-5-5", "effort": "high", "launch": "run"},
        ],
    },
}


def _write(folder, *fixtures):
    for fx in fixtures:
        (Path(folder) / f"{fx['name']}.json").write_text(json.dumps(fx, indent=2), encoding="utf-8")


def _cli(*args):
    return subprocess.run([sys.executable, str(EVAL), *args], capture_output=True, text=True, timeout=60)


def _by_name(report):
    return {fx["name"]: fx for fx in report["fixtures"]}


class ShippedFixtureTests(unittest.TestCase):
    def test_every_shipped_fixture_passes_and_every_reachable_rule_is_covered(self):
        report = router_eval.evaluate(FIXTURES)
        failing = [fx["name"] for fx in report["fixtures"] if not fx["passed"]]
        self.assertEqual(failing, [])
        self.assertEqual(report["totals"]["failed"], 0)
        self.assertEqual(report["totals"]["passed"], report["totals"]["total"])
        self.assertEqual(report["rules_uncovered"], [])
        self.assertEqual(report["rules_unreachable"], sorted(router.UNREACHABLE_RULES))

    def test_fixtures_have_the_documented_shape_and_unique_names(self):
        names = []
        for path in sorted(FIXTURES.glob("*.json")):
            fx = baseline.load_json(path)
            with self.subTest(fixture=path.name):
                self.assertTrue({"name", "input", "as_of", "expect"} <= set(fx))
                self.assertTrue({"rule", "status", "roster"} <= set(fx["expect"]))
                for entry in fx["expect"]["roster"]:
                    self.assertEqual(set(entry), {"role", "model", "effort", "launch"})
            names.append(fx["name"])
        self.assertEqual(len(names), len(set(names)))

    def test_shipped_fixtures_exercise_post_passes_and_fable(self):
        report = router_eval.evaluate(FIXTURES)
        statuses = {fx["status"] for fx in report["fixtures"]}
        self.assertTrue({"ok", "error", "owner", "blocked", "over_budget"} <= statuses)
        fixtures = [baseline.load_json(p) for p in sorted(FIXTURES.glob("*.json"))]
        fable = [fx for fx in fixtures if fx["expect"]["rule"] == router.FABLE_RULE]
        launches = {e["launch"] for fx in fable for e in fx["expect"]["roster"] if e["model"] == "claude-fable-5-1"}
        self.assertEqual(launches, {"run", "skip"})
        alone = []
        for fx in fable:
            # L11/L13: Fable joins the team as FABLE_ROLE, at most high, on request only; it runs
            # alone only when the base roster is empty (exempt tier), and a catalog without
            # Fable skips the step (no entry) instead of failing.
            with self.subTest(fixture=fx["name"]):
                self.assertIs(fx["input"].get("owner_named"), True)
                extra = [e for e in fx["expect"]["roster"] if e["role"] == router.FABLE_ROLE]
                if fx.get("catalog_patch"):
                    self.assertEqual(extra, [])
                else:
                    self.assertEqual([(e["model"], e["effort"]) for e in extra], [("claude-fable-5-1", "high")])
                if not [e for e in fx["expect"]["roster"] if e["role"] != router.FABLE_ROLE]:
                    self.assertEqual(fx["input"]["tier"], "exempt")
                    alone.append(fx["name"])
        self.assertTrue(alone)
        for fx in fixtures:
            if fx["expect"]["rule"] != router.FABLE_RULE:
                self.assertNotIn("claude-fable-5-1", [e["model"] for e in fx["expect"]["roster"]], fx["name"])

    def test_cli_exits_zero_on_the_shipped_fixtures(self):
        proc = _cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("0 failed", proc.stderr)


class NegativeControlTests(unittest.TestCase):
    def test_wrong_expected_roster_fails_with_missing_and_extra_roles(self):
        wrong = copy.deepcopy(B3_FIXTURE)
        wrong["expect"]["roster"][0]["role"] = "generic-challenger"
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, wrong)
            report = router_eval.evaluate(tmp)
            fx = _by_name(report)["b3-tmp"]
            self.assertFalse(fx["passed"])
            self.assertTrue(fx["rule_ok"] and fx["status_ok"])
            self.assertFalse(fx["roster_ok"])
            self.assertEqual(fx["roles_missing"], ["generic-challenger"])
            self.assertEqual(fx["roles_extra"], ["generic-proposer"])
            self.assertEqual(report["totals"]["failed"], 1)
            proc = _cli("--fixtures", tmp)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("1 failed", proc.stderr)

    def test_effort_and_tier_mismatch_is_reported_above_and_below(self):
        fx = copy.deepcopy(B3_FIXTURE)
        fx["expect"]["roster"][0]["effort"] = "low"  # actual medium: above
        fx["expect"]["roster"][1]["model"] = "claude-opus-5-5"  # actual sonnet: tier below
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, fx)
            got = _by_name(router_eval.evaluate(tmp))["b3-tmp"]
        self.assertFalse(got["passed"])
        self.assertEqual((got["roles_missing"], got["roles_extra"]), ([], []))
        self.assertEqual([(d["role"], d["by"]) for d in got["effort_or_tier_above"]], [("generic-proposer", "effort")])
        self.assertEqual([(d["role"], d["by"]) for d in got["effort_or_tier_below"]], [("generic-verifier", "tier")])

    def test_rule_and_status_mismatch_fail(self):
        fx = copy.deepcopy(B3_FIXTURE)
        fx["expect"]["rule"], fx["expect"]["status"] = "B4", "owner"
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, fx)
            got = _by_name(router_eval.evaluate(tmp))["b3-tmp"]
        self.assertEqual((got["rule_ok"], got["status_ok"], got["roster_ok"], got["passed"]),
                         (False, False, True, False))


class FanOutTests(unittest.TestCase):
    def test_fan_out_fixture_stays_within_the_cap(self):
        got = _by_name(router_eval.evaluate(FIXTURES))["b2-map-fan-out-cap"]
        self.assertEqual((got["max_parallel_step"], got["fanout_ok"]), (router.MAX_PARALLEL, True))

    FAN_OUT = {"name": "fan-out-tmp", "as_of": "2026-10-16",
               "input": {"task_kind": "map", "tier": "medium", "lane": "sonnet", "modules": 5},
               "expect": {"rule": "B2", "status": "ok", "roster": [
                   {"role": "generic-cartographer", "model": "claude-sonnet-5-5", "effort": "medium", "launch": "run"}] * 5}}

    def test_a_catalog_cap_above_the_owner_decision_is_clamped_by_the_router(self):
        cat = copy.deepcopy(CATALOG)
        cat["router"]["max_parallel"] = 5
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, self.FAN_OUT)
            got = _by_name(router_eval.evaluate(tmp, catalog=cat))["fan-out-tmp"]
        self.assertEqual((got["roster_ok"], got["max_parallel_step"], got["fanout_ok"], got["passed"]),
                         (True, router.MAX_PARALLEL, True, True))

    def test_a_step_above_the_cap_fails_the_fixture(self):
        # negative control for fanout_ok: a router whose cap were 5 is caught
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(router, "parallel_cap", lambda catalog: 5):
            _write(tmp, self.FAN_OUT)
            got = _by_name(router_eval.evaluate(tmp))["fan-out-tmp"]
        self.assertTrue(got["roster_ok"])
        self.assertEqual((got["max_parallel_step"], got["fanout_ok"], got["passed"]), (5, False, False))


class CatalogPatchTests(unittest.TestCase):
    """A fixture may carry `catalog_patch`, merged onto a copy of the catalog
    for that fixture only (how the guard:catalog fixture breaks the catalog)."""

    def test_patch_applies_to_one_fixture_only(self):
        broken = {"name": "broken-tmp", "as_of": "2026-10-16", "catalog_patch": {"router": {"max_parallel": 0}},
                  "input": dict(self._map()), "expect": {"rule": "guard:catalog", "status": "error", "roster": []}}
        fine = copy.deepcopy(B3_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, broken, fine)
            report = router_eval.evaluate(tmp)
        got = _by_name(report)
        self.assertTrue(got["broken-tmp"]["passed"], got["broken-tmp"])
        self.assertTrue(got["b3-tmp"]["passed"], got["b3-tmp"])
        self.assertEqual(CATALOG["router"]["max_parallel"], 3)

    def test_patch_merges_nested_objects(self):
        merged = router_eval.patched(CATALOG, {"router": {"max_parallel": 0}})
        self.assertEqual(merged["router"]["max_parallel"], 0)
        self.assertEqual(merged["router"]["tier_ladder"], CATALOG["router"]["tier_ladder"])
        self.assertEqual(router_eval.patched(CATALOG, []), [])

    @staticmethod
    def _map():
        return {"task_kind": "map", "tier": "medium", "lane": "sonnet", "modules": 4}


class DeterminismTests(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "one.json", Path(tmp) / "two.json"
            first = _cli("--out", str(one))
            second = _cli("--out", str(two))
            self.assertEqual((first.returncode, second.returncode), (0, 0))
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(first.stdout + first.stderr, second.stdout + second.stderr)
            text = one.read_text(encoding="utf-8")
        self.assertEqual(text, router.dumps(json.loads(text)))
        self.assertEqual(text, router_eval.render(router_eval.evaluate(FIXTURES)))

    def test_cli_without_out_prints_the_report(self):
        proc = _cli()
        self.assertEqual(json.loads(proc.stdout), router_eval.evaluate(FIXTURES))


class CoverageTests(unittest.TestCase):
    def test_coverage_is_measured_against_the_router_rule_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, B3_FIXTURE)
            report = router_eval.evaluate(tmp)
        reachable = sorted(set(router.RULE_IDS) - set(router.UNREACHABLE_RULES))
        self.assertEqual(report["rule_coverage"], ["B3"])
        self.assertEqual(report["rules_uncovered"], [r for r in reachable if r != "B3"])

    def test_a_rule_id_unknown_to_the_router_is_not_counted(self):
        fx = copy.deepcopy(B3_FIXTURE)
        fx["expect"]["rule"] = "B99"
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, fx)
            report = router_eval.evaluate(tmp)
        self.assertEqual(report["rule_coverage"], ["B3"])  # coverage counts what the router fired


class PriceScheduleTests(unittest.TestCase):
    """Argon doubles on 2026-12-01; only reachable with a catalog fixture."""

    def _argon_catalog(self):
        cat = copy.deepcopy(CATALOG)
        for entry in cat["tiers"]["large"]["candidates"]:
            if entry["id"] == "gemini-4-argon":
                entry["status"] = "admitted"
            elif entry["status"] == "admitted":
                entry["status"] = "candidate"
        return cat

    def _fixture(self, name, as_of, cost_max=None):
        fx = {
            "name": name,
            "as_of": as_of,
            "input": {"task_kind": "verify", "tier": "high", "lane": "opus", "prior": {"findings": 1}},
            "expect": {"rule": "B8", "status": "ok", "roster": [
                {"role": "generic-verifier", "model": "claude-sonnet-5-5", "effort": "high", "launch": "run"},
                {"role": "generic-judge", "model": "gemini-4-argon", "effort": "high", "launch": "run"},
            ]},
        }
        if cost_max is not None:
            fx["expect"]["cost_max_usd"] = cost_max
        return fx

    def test_cost_doubles_for_argon_across_december_first(self):
        cat = self._argon_catalog()
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, self._fixture("argon-before", "2026-11-30"), self._fixture("argon-after", "2026-12-01"))
            report = router_eval.evaluate(tmp, catalog=cat)
        got = _by_name(report)
        self.assertTrue(got["argon-before"]["passed"] and got["argon-after"]["passed"])
        self.assertGreater(got["argon-after"]["cost"], got["argon-before"]["cost"])
        self.assertEqual(report["totals"]["total_cost_usd"],
                         round(got["argon-before"]["cost"] + got["argon-after"]["cost"], 6))

    def test_cost_cap_fails_after_the_price_change(self):
        cat = self._argon_catalog()
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, self._fixture("argon-before", "2026-11-30"))
            cap = _by_name(router_eval.evaluate(tmp, catalog=cat))["argon-before"]["cost"]
            _write(tmp, self._fixture("argon-before", "2026-11-30", cap), self._fixture("argon-after", "2026-12-01", cap))
            got = _by_name(router_eval.evaluate(tmp, catalog=cat))
        self.assertTrue(got["argon-before"]["passed"])
        self.assertTrue(got["argon-after"]["roster_ok"])
        self.assertFalse(got["argon-after"]["cost_ok"])
        self.assertFalse(got["argon-after"]["passed"])


if __name__ == "__main__":
    unittest.main()
