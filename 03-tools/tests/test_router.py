"""router.route() is pure: one test per guard, per decision row (P1-P6,
B0-B8), per post-pass, the escalation ladder, the Fable rule (L11: only on
the owner's request, joining the team, effort <= high, bounded context, run
only on approval) and the routing log. Negative controls: byte-identical
output for the same input, no Fable without a request and no launch without
approval, offline never yields a remote
provider, no step above the fan-out cap. B7 is the fail-closed fallthrough
that no valid input reaches once B8 (verify) exists; a patched kind proves
it still fails closed."""
import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import baseline, router

TOOLS = Path(__file__).resolve().parent.parent
CATALOG = baseline.load_json(TOOLS / "config" / "model-tiers.json")
AS_OF = "2026-10-16"
FABLE = "claude-fable-5-1"


def _task(**overrides):
    task = {
        "task_kind": "implement",
        "tier": "medium",
        "lane": "sonnet",
        "critical_hit": False,
        "owner_gate": False,
        "changed_lines": 50,
        "modules": 1,
        "full_required": False,
        "map_age_days": 1,
        "offline": False,
        "owner_named": False,
        "prior": {},
        "approvals": [],
    }
    task.update(overrides)
    return task


def _route(catalog=None, as_of=AS_OF, **overrides):
    return router.route(_task(**overrides), catalog or CATALOG, as_of)


def _running(result):
    return [e for e in result["roster"] if e["launch"] == "run"]


def _roles(result):
    return [(e["role"], e["tier"], e["model"], e["effort"]) for e in _running(result)]


def _fixture_catalog(*, large_argon=False, local_small=False, trial=False):
    """The real catalog with a few statuses flipped, only inside the test."""
    cat = copy.deepcopy(CATALOG)
    if large_argon:
        for entry in cat["tiers"]["large"]["candidates"]:
            if entry["id"] == "gemini-4-argon":
                entry["status"] = "admitted"
            elif entry["status"] == "admitted":
                entry["status"] = "candidate"
    if local_small:
        for entry in cat["tiers"]["small"]["candidates"]:
            if entry.get("local"):
                entry["status"] = "admitted"
                break
    if trial:
        cat["router"]["trial_slot"] = True
    return cat


class CatalogTests(unittest.TestCase):
    """R7: one catalog carries effort, dated prices, token assumptions and launch syntax."""

    def _entries(self):
        for tier_name, tier in CATALOG["tiers"].items():
            for entry in tier["candidates"]:
                yield tier_name, entry

    def test_every_entry_has_read_date_schedule_effort_and_launch(self):
        for tier_name, entry in self._entries():
            with self.subTest(tier=tier_name, id=entry["id"]):
                self.assertRegex(entry["read"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(entry["price_schedule"])
                self.assertTrue(entry["effort_levels"])
                self.assertTrue(entry["effort_by_role"])
                for role, level in entry["effort_by_role"].items():
                    self.assertIn(level, entry["effort_levels"], role)
                self.assertIn("pi", entry["launch"])
                self.assertIn("claude-code", entry["launch"])
                for runtime in entry["launch"].values():
                    self.assertIn("verified", runtime)

    def test_argon_doubles_from_december(self):
        argon = [e for _, e in self._entries() if e["id"] == "gemini-4-argon"][0]
        self.assertIn({"from": "2026-12-01", "usd_in": 4.0, "usd_out": 20.0}, argon["price_schedule"])

    def test_statuses_follow_owner_decisions(self):
        for tier_name, entry in self._entries():
            with self.subTest(id=entry["id"]):
                if entry["id"] == FABLE:
                    self.assertEqual(entry["status"], "approval-only")
                elif entry["provider"] in ("google", "openai", "local"):
                    self.assertEqual(entry["status"], "candidate")
                if entry["provider"] == "local":
                    self.assertEqual(tier_name, "small")
                    self.assertTrue(entry["offline_only"])
        orchestrator = CATALOG["tiers"]["orchestrator"]["candidates"]
        self.assertEqual([e["id"] for e in orchestrator if e["status"] == "admitted"], ["claude-opus-5-5"])

    def test_token_assumptions_are_labeled_assumed(self):
        for tier_name, tier in CATALOG["tiers"].items():
            for role, tokens in tier["token_assumptions"].items():
                with self.subTest(tier=tier_name, role=role):
                    self.assertEqual(tokens["tag"], "Assumed")
                    self.assertGreater(tokens["assumed_tokens_in"], 0)
                    self.assertGreater(tokens["assumed_tokens_out"], 0)


class GuardTests(unittest.TestCase):
    def test_unknown_task_kind_fails_closed(self):
        result = _route(task_kind="refactor")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["rule"], "guard:task_kind")
        self.assertEqual(result["roster"], [])

    def test_missing_tier_fails_closed(self):
        task = _task()
        del task["tier"]
        result = router.route(task, CATALOG, AS_OF)
        self.assertEqual((result["status"], result["rule"]), ("error", "guard:tier"))

    def test_opus_lane_below_high_fails_closed(self):
        result = _route(lane="opus", tier="medium")
        self.assertEqual((result["status"], result["rule"]), ("error", "guard:lane"))

    def test_full_required_below_high_fails_closed(self):
        result = _route(full_required=True, tier="medium")
        self.assertEqual((result["status"], result["rule"]), ("error", "guard:full_required"))

    def test_bad_as_of_fails_closed(self):
        result = _route(as_of="16/10/2026")
        self.assertEqual((result["status"], result["rule"]), ("error", "guard:as_of"))


class PriorRowTests(unittest.TestCase):
    def test_p1_two_stalls_go_to_owner(self):
        result = _route(prior={"stalls": 2})
        self.assertEqual((result["rule"], result["status"]), ("P1", "owner"))
        self.assertEqual(result["roster"], [])

    def test_p2_truncated_splits_by_module_same_tier_and_effort(self):
        result = _route(task_kind="map", modules=5, prior={
            "truncated": True, "role": "generic-cartographer", "tier": "medium", "effort": "medium"})
        self.assertEqual(result["rule"], "P2")
        self.assertEqual(len(_running(result)), 5)
        self.assertEqual({r[1:] for r in _roles(result)}, {("medium", "claude-sonnet-5-5", "medium")})

    def test_p3_schema_fail_raises_effort_then_tier(self):
        prior = {"schema_fail": 1, "role": "generic-verifier", "tier": "medium", "effort": "high"}
        first = _route(prior=prior)
        self.assertEqual(first["rule"], "P3")
        self.assertEqual(_roles(first), [("generic-verifier", "medium", "claude-sonnet-5-5", "xhigh")])
        second = _route(prior=dict(prior, schema_fail=2))
        self.assertEqual(_roles(second)[0][1:3], ("large", "claude-opus-5-5"))

    def test_p4_p0_from_lower_tier_is_confirmed_one_tier_up(self):
        result = _route(task_kind="review", prior={"p0_from_lower_tier": "medium", "role": "generic-judge"})
        self.assertEqual(result["rule"], "P4")
        self.assertEqual(_roles(result), [("generic-judge", "large", "claude-opus-5-5", "high")])

    def test_p4_small_p0_without_critical_hit_goes_one_tier_up_to_medium(self):
        result = _route(task_kind="review", prior={"p0_from_lower_tier": "small", "role": "generic-judge"})
        self.assertEqual((result["rule"], result["status"]), ("P4", "ok"))
        self.assertEqual([r[:3] for r in _roles(result)], [("generic-judge", "medium", "claude-sonnet-5-5")])
        self.assertNotEqual(_roles(result)[0][3], "xhigh")

    def test_p4_p0_on_a_critical_path_is_confirmed_on_the_large_tier_at_xhigh(self):
        # L13: a small-tier P0 on a critical path no longer stops at Sonnet xhigh.
        for origin in ("small", "medium"):
            with self.subTest(origin=origin):
                result = _route(task_kind="review", tier="high", lane="opus", critical_hit=True,
                                prior={"p0_from_lower_tier": origin, "role": "generic-judge"})
                self.assertEqual((result["rule"], result["status"]), ("P4", "ok"))
                self.assertEqual(_roles(result), [("generic-judge", "large", "claude-opus-5-5", "xhigh")])

    def test_p4_p0_already_from_the_large_tier_goes_to_the_owner(self):
        # L13: never dropped silently; there is no higher automatic tier to confirm it.
        for critical in (False, True):
            with self.subTest(critical=critical):
                result = _route(task_kind="review", tier="high", lane="opus", critical_hit=critical,
                                prior={"p0_from_lower_tier": "large", "role": "generic-judge"})
                self.assertEqual((result["rule"], result["status"], result["roster"]), ("P4", "owner", []))
                self.assertIn("P0 from the large tier", " ".join(result["reasons"]))
                self.assertIn("owner", " ".join(result["reasons"]))

    def test_p5_disagreement_goes_to_large_judge(self):
        result = _route(task_kind="review", prior={"disagreement": True})
        self.assertEqual(result["rule"], "P5")
        self.assertEqual(_roles(result), [("generic-judge", "large", "claude-opus-5-5", "high")])
        critical = _route(task_kind="review", tier="high", critical_hit=True, prior={"disagreement": True})
        self.assertEqual(_roles(critical)[0][3], "xhigh")

    def test_p6_verifier_fail_reruns_proposer_once(self):
        result = _route(prior={"verifier": "FAIL"})
        self.assertEqual(result["rule"], "P6")
        self.assertEqual(_roles(result), [("generic-proposer", "medium", "claude-sonnet-5-5", "medium")])


class BaseRowTests(unittest.TestCase):
    def test_b0_exempt_launches_nothing(self):
        result = _route(tier="exempt", task_kind="review")
        self.assertEqual((result["rule"], result["status"], result["roster"]), ("B0", "ok", []))

    def test_b1_low_tier_is_scripts_only_and_comment_gate_on_new_comments(self):
        result = _route(tier="low")
        self.assertEqual((result["rule"], _running(result)), ("B1", []))
        gated = _route(task_kind="comment", tier="high", lane="opus", new_comments=2)
        self.assertEqual(gated["rule"], "B1")
        self.assertEqual(_roles(gated), [("generic-comment-gate", "small", "claude-haiku-5-5", "low")])

    def test_b2_map_single_module_is_small(self):
        result = _route(task_kind="map", modules=1)
        self.assertEqual(result["rule"], "B2")
        self.assertEqual(_roles(result), [("generic-cartographer", "small", "claude-haiku-5-5", "medium")])

    def test_b2_map_many_modules_is_medium_in_batches_of_three(self):
        result = _route(task_kind="map", modules=7)
        self.assertEqual(len(_running(result)), 7)
        self.assertEqual({r[1:] for r in _roles(result)}, {("medium", "claude-sonnet-5-5", "medium")})
        self.assertEqual(sorted({e["step"] for e in result["roster"]}), [1, 2, 3])
        self.assertTrue(all(e["order"] == "parallel" for e in result["roster"]))

    def test_b3_implement_medium_fresh_map(self):
        result = _route()
        self.assertEqual(result["rule"], "B3")
        self.assertEqual(_roles(result), [
            ("generic-proposer", "medium", "claude-sonnet-5-5", "medium"),
            ("generic-verifier", "medium", "claude-sonnet-5-5", "high")])
        self.assertEqual([e["order"] for e in result["roster"]], ["sequential", "sequential"])

    def test_b3_stale_map_adds_optional_cartographer_first(self):
        result = _route(map_age_days=9)
        first = result["roster"][0]
        self.assertEqual((first["role"], first["step"], first["optional"]),
                         ("generic-cartographer", 1, "stale-map-cartographer"))

    def test_b4_implement_high_adds_the_high_review(self):
        result = _route(tier="high", lane="opus")
        self.assertEqual(result["rule"], "B4")
        roles = _roles(result)
        self.assertIn(("generic-proposer", "medium", "claude-sonnet-5-5", "high"), roles)
        self.assertIn(("generic-challenger", "large", "claude-opus-5-5", "high"), roles)
        self.assertIn(("generic-blind-spot-adversary", "large", "claude-opus-5-5", "high"), roles)

    def test_b5_review_medium(self):
        result = _route(task_kind="review", prior={"findings": 2})
        self.assertEqual(result["rule"], "B5")
        self.assertEqual(_roles(result), [
            ("generic-challenger", "medium", "claude-sonnet-5-5", "high"),
            ("generic-verifier", "medium", "claude-sonnet-5-5", "medium"),
            ("generic-judge", "medium", "claude-sonnet-5-5", "high")])
        zero = _route(task_kind="docs", prior={"findings": 0})
        self.assertNotIn("generic-judge", [r[0] for r in _roles(zero)])

    def test_b6_review_high_critical_raises_effort_and_judge(self):
        result = _route(task_kind="review", tier="high", critical_hit=True)
        self.assertEqual(result["rule"], "B6")
        roles = _roles(result)
        self.assertIn(("generic-challenger", "large", "claude-opus-5-5", "xhigh"), roles)
        self.assertIn(("generic-judge", "large", "claude-opus-5-5", "xhigh"), roles)
        self.assertIn(("generic-verifier", "medium", "claude-sonnet-5-5", "high"), roles)
        plain = _route(task_kind="review", tier="high")
        self.assertIn(("generic-judge", "medium", "claude-sonnet-5-5", "high"), _roles(plain))

    def test_b8_verify_medium_is_one_verifier_at_sonnet_high(self):
        result = _route(task_kind="verify", tier="medium")
        self.assertEqual((result["rule"], result["status"]), ("B8", "ok"))
        self.assertEqual(_roles(result), [("generic-verifier", "medium", "claude-sonnet-5-5", "high")])
        self.assertEqual(result["roster"][0]["order"], "sequential")

    def test_b8_verify_high_adds_the_large_judge_only_on_prior_findings(self):
        verifier = ("generic-verifier", "medium", "claude-sonnet-5-5", "high")
        judge = ("generic-judge", "large", "claude-opus-5-5", "high")
        found = _route(task_kind="verify", tier="high", lane="opus", prior={"findings": 2})
        self.assertEqual((found["rule"], found["status"]), ("B8", "ok"))
        self.assertEqual(_roles(found), [verifier, judge])
        self.assertEqual([e["step"] for e in found["roster"]], [1, 2])
        self.assertIsNone(found["roster"][1]["optional"])
        for prior in ({"findings": 0}, {}):
            with self.subTest(prior=prior):
                result = _route(task_kind="verify", tier="high", lane="opus", prior=prior)
                self.assertEqual(result["rule"], "B8")
                self.assertEqual(_roles(result), [verifier])
                skipped = [e for e in result["roster"] if e["launch"] == "skip"]
                self.assertEqual([(e["role"], e["model"]) for e in skipped], [("generic-judge", "claude-opus-5-5")])
        critical = _route(task_kind="verify", tier="high", lane="opus", critical_hit=True, prior={"findings": 1})
        self.assertEqual(_roles(critical)[1], ("generic-judge", "large", "claude-opus-5-5", "xhigh"))

    def test_b7_is_unreachable_from_valid_input_but_still_fails_closed(self):
        for kind in router.TASK_KINDS:
            for tier in router.RDD_TIERS:
                lane = "opus" if tier == "high" else "sonnet"
                with self.subTest(kind=kind, tier=tier):
                    self.assertNotEqual(_route(task_kind=kind, tier=tier, lane=lane)["rule"], "B7")
        self.assertIn("B7", router.UNREACHABLE_RULES)
        with mock.patch.object(router, "TASK_KINDS", router.TASK_KINDS + ("audit",)):
            result = _route(task_kind="audit", tier="medium")
        self.assertEqual((result["rule"], result["status"], result["roster"]), ("B7", "error", []))

    def test_rule_ids_constant_lists_every_rule_the_router_emits(self):
        ids = router.RULE_IDS
        self.assertEqual(len(ids), len(set(ids)))
        expected = {"guard:as_of", "guard:task_kind", "guard:tier", "guard:lane", "guard:full_required",
                    "guard:input", "guard:catalog", "P1", "P2", "P3", "P4", "P5", "P6", router.FABLE_RULE,
                    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "error"}
        self.assertEqual(set(ids), expected)
        self.assertTrue(set(router.UNREACHABLE_RULES) <= set(ids))


class BaseRuleTests(unittest.TestCase):
    """L13: the result and the log line name the table row that ran before the
    Fable step (`base_rule`); `rule` keeps its meaning."""

    def test_base_rule_equals_rule_without_a_fable_request(self):
        for overrides in ({}, {"tier": "exempt"}, {"prior": {"stalls": 2}}, {"task_kind": "refactor"}):
            with self.subTest(overrides=overrides):
                result = _route(**overrides)
                self.assertEqual(result["base_rule"], result["rule"])
        self.assertEqual(_route(modules=[1, "a"])["base_rule"], "guard:input")

    def test_base_rule_names_the_row_under_escalate_fable(self):
        result = _route(owner_named=True, approvals=["escalate-fable"])
        self.assertEqual((result["rule"], result["base_rule"]), (router.FABLE_RULE, "B3"))
        review = _route(owner_named=True, task_kind="review", tier="high", lane="opus")
        self.assertEqual((review["rule"], review["base_rule"]), (router.FABLE_RULE, "B6"))
        line = json.loads(router.log_line(result))
        self.assertEqual((line["rule"], line["base_rule"]), (router.FABLE_RULE, "B3"))


class PostPassTests(unittest.TestCase):
    def test_budget_never_drops_mandatory_roles(self):
        full = _route(task_kind="review", tier="high")
        result = _route(task_kind="review", tier="high", budget_usd=0.01)
        self.assertEqual(result["status"], "over_budget")
        self.assertEqual(_roles(result), _roles(full))

    def test_budget_drops_optional_roles_in_fixed_order(self):
        cat = _fixture_catalog(trial=True)
        full = _route(cat, task_kind="review", tier="high")
        trial = [e for e in _running(full) if e["trial"]]
        self.assertEqual(len(trial), 1)
        budget = full["cost_estimate_usd"] - 0.0001
        result = _route(cat, task_kind="review", tier="high", budget_usd=budget)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([e for e in _running(result) if e["trial"]], [])
        stale = _route(map_age_days=30)
        dropped = _route(map_age_days=30, budget_usd=stale["cost_estimate_usd"] - 0.0001)
        self.assertEqual(dropped["status"], "ok")
        self.assertNotIn("generic-cartographer", [r[0] for r in _roles(dropped)])

    def test_offline_without_admitted_local_model_is_blocked(self):
        result = _route(task_kind="map", offline=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(_running(result), [])

    def test_offline_with_admitted_local_model_stays_local(self):
        result = _route(_fixture_catalog(local_small=True), task_kind="map", offline=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual({e["provider"] for e in _running(result)}, {"local"})


class FanOutAndLadderTests(unittest.TestCase):
    def test_no_step_runs_more_than_three_in_parallel(self):
        tasks = [_task(task_kind="map", modules=n) for n in (1, 3, 4, 10)]
        tasks += [_task(task_kind="review", tier="high"), _task(task_kind="implement", tier="high", lane="opus")]
        tasks += [_task(task_kind="map", modules=8, prior={"truncated": True, "role": "generic-cartographer"})]
        for task in tasks:
            result = router.route(task, _fixture_catalog(trial=True), AS_OF)
            per_step = {}
            for e in _running(result):
                per_step[e["step"]] = per_step.get(e["step"], 0) + 1
            with self.subTest(task=task["task_kind"], modules=task["modules"]):
                self.assertLessEqual(max(per_step.values() or [0]), router.MAX_PARALLEL)

    def test_escalation_raises_effort_first_then_tier(self):
        step = router.escalate(CATALOG, "generic-verifier", "medium", "high", "diligence")
        self.assertEqual(step, ("medium", "xhigh"))
        step = router.escalate(CATALOG, "generic-verifier", "medium", "xhigh", "diligence")
        self.assertEqual(step, ("large", "high"))  # max is never automatic
        step = router.escalate(CATALOG, "generic-proposer", "medium", "medium", "wrong")
        self.assertEqual(step[0], "large")
        self.assertIsNone(router.escalate(CATALOG, "generic-challenger", "large", "xhigh", "diligence"))


class DeterminismTests(unittest.TestCase):
    def test_same_input_is_byte_identical(self):
        task = _task(task_kind="review", tier="high", approvals=["b", "a"])
        one = router.dumps(router.route(task, CATALOG, AS_OF))
        two = router.dumps(router.route(copy.deepcopy(task), copy.deepcopy(CATALOG), AS_OF))
        self.assertEqual(one, two)

    def test_argon_cost_changes_across_december_first(self):
        cat = _fixture_catalog(large_argon=True)
        before = _route(cat, as_of="2026-11-30", task_kind="review", tier="high")
        after = _route(cat, as_of="2026-12-01", task_kind="review", tier="high")
        self.assertIn("gemini-4-argon", [e["model"] for e in _running(before)])
        self.assertGreater(after["cost_estimate_usd"], before["cost_estimate_usd"])
        self.assertEqual(before["inputs_hash"], after["inputs_hash"])


def _fable_entries(result):
    return [e for e in result["roster"] if e["model"] == FABLE or e["role"] == router.FABLE_ROLE]


class DeepReasonerCapTests(unittest.TestCase):
    """Verifier blocker (L13): the deep-reasoner role carries the Fable cap
    on any model, so P2/P3/P4 escalations of it never exceed `high`."""

    def test_escalations_of_the_deep_reasoner_never_exceed_high(self):
        cases = {
            "P2": {"truncated": True},
            "P3": {"schema_fail": 1},
            "P3x2": {"schema_fail": 2},
            "P4": {"p0_from_lower_tier": "medium"},
        }
        for name, signal in cases.items():
            for effort in ("high", "xhigh", "max"):
                prior = {"role": router.FABLE_ROLE, "tier": "orchestrator", "effort": effort, **signal}
                with self.subTest(case=name, effort=effort):
                    result = _route(task_kind="review", tier="high", critical_hit=True, prior=prior)
                    for entry in result["roster"]:
                        if entry["role"] == router.FABLE_ROLE:
                            self.assertLessEqual(router.EFFORT_RANK[entry["effort"]],
                                                 router.EFFORT_RANK[router.FABLE_EFFORT_CAP], (result, entry))

    def test_the_cap_holds_for_the_role_on_a_non_fable_model(self):
        prior = {"role": router.FABLE_ROLE, "tier": "orchestrator", "effort": "high", "schema_fail": 1}
        result = _route(task_kind="review", tier="high", prior=prior)
        runs = [e for e in result["roster"] if e["role"] == router.FABLE_ROLE]
        self.assertTrue(all(e["effort"] == "high" for e in runs), result)
        self.assertTrue(all("max_context_tokens" in e for e in runs), result)


class FableTests(unittest.TestCase):
    """L11: Fable only on demand (owner_named), joins the team in its own
    final step, never replaces it, effort capped at high, bounded context."""

    PRIORS = ({}, {"p0_from_lower_tier": "medium"}, {"p0_from_lower_tier": "small"},
              {"disagreement": True}, {"disagreement": True, "judge_tier": "large"},
              {"disagreement": True, "judge_tier": "large", "effort": "xhigh"}, {"escalated_count": 2},
              {"escalated_count": 3, "disagreement": True, "judge_tier": "large", "p0_from_lower_tier": "medium"})

    def _grid(self):
        for kind in router.TASK_KINDS:
            for tier in router.RDD_TIERS:
                lane = "opus" if tier == "high" else "sonnet"
                for prior in self.PRIORS:
                    for critical in (False, True):
                        for approvals in ([], ["escalate-fable"]):
                            yield _task(task_kind=kind, tier=tier, lane=lane, critical_hit=critical,
                                        map_age_days=None, prior=prior, approvals=approvals)

    def test_no_input_without_a_fable_request_yields_fable(self):
        for task in self._grid():
            result = router.route(task, CATALOG, AS_OF)
            with self.subTest(kind=task["task_kind"], tier=task["tier"], prior=task["prior"],
                              critical=task["critical_hit"], approvals=task["approvals"]):
                self.assertEqual(_fable_entries(result), [])
                self.assertNotEqual(result["rule"], router.FABLE_RULE)
                self.assertEqual(result["approvals"], [])

    def test_p0_on_a_critical_path_escalates_to_opus_xhigh_not_fable(self):
        for origin in ("small", "medium"):
            with self.subTest(origin=origin):
                result = _route(task_kind="review", tier="high", lane="opus", critical_hit=True,
                                prior={"p0_from_lower_tier": origin})
                self.assertEqual((result["rule"], result["status"]), ("P4", "ok"))
                self.assertEqual(_roles(result), [("generic-judge", "large", "claude-opus-5-5", "xhigh")])

    def test_disagreement_after_the_large_judge_goes_to_xhigh_then_the_owner(self):
        first = _route(task_kind="review", tier="high", lane="opus",
                       prior={"disagreement": True, "judge_tier": "large", "effort": "high"})
        self.assertEqual((first["rule"], first["status"]), ("P5", "ok"))
        self.assertEqual(_roles(first), [("generic-judge", "large", "claude-opus-5-5", "xhigh")])
        exhausted = _route(task_kind="review", tier="high", lane="opus",
                           prior={"disagreement": True, "judge_tier": "large", "effort": "xhigh"})
        self.assertEqual((exhausted["rule"], exhausted["status"], exhausted["roster"]), ("P5", "owner", []))
        critical = _route(task_kind="review", tier="high", lane="opus", critical_hit=True,
                          prior={"disagreement": True, "judge_tier": "large"})
        self.assertEqual((critical["rule"], critical["status"]), ("P5", "owner"))

    def test_high_receipt_escalated_twice_goes_to_the_owner(self):
        result = _route(task_kind="review", tier="high", lane="opus", prior={"escalated_count": 2})
        self.assertEqual((result["rule"], result["status"], result["roster"]), ("P1", "owner", []))
        lower = _route(task_kind="review", tier="medium", prior={"escalated_count": 2})
        self.assertEqual(lower["rule"], "B5")

    def test_requested_and_approved_joins_the_full_team_at_high(self):
        cases = [dict(), dict(task_kind="review", tier="high", lane="opus", critical_hit=True),
                 dict(task_kind="implement", tier="high", lane="opus", critical_hit=True),
                 dict(task_kind="verify", tier="high", lane="opus", prior={"findings": 1}),
                 dict(task_kind="map", modules=4)]
        for case in cases:
            with self.subTest(case=case):
                base = _route(**case)
                result = _route(owner_named=True, approvals=["escalate-fable"], **case)
                self.assertEqual((result["rule"], result["status"]), (router.FABLE_RULE, "ok"))
                team = [e for e in result["roster"] if e["role"] != router.FABLE_ROLE]
                self.assertEqual(team, base["roster"])
                fable = _fable_entries(result)
                self.assertEqual(len(fable), 1)
                f = fable[0]
                self.assertEqual((f["role"], f["model"], f["launch"], f["effort"], f["requires_approval"]),
                                 (router.FABLE_ROLE, FABLE, "run", "high", True))
                self.assertEqual(f["step"], max([e["step"] for e in team], default=0) + 1)
                self.assertIs(result["roster"][-1], f)
                self.assertEqual(result["approvals"], ["escalate-fable"])

    def test_requested_not_approved_keeps_the_team_skips_fable_without_substitute(self):
        for case in (dict(), dict(task_kind="review", tier="high", lane="opus")):
            with self.subTest(case=case):
                base = _route(**case)
                result = _route(owner_named=True, **case)
                self.assertEqual((result["rule"], result["status"]), (router.FABLE_RULE, "ok"))
                self.assertEqual([e for e in result["roster"] if e["role"] != router.FABLE_ROLE], base["roster"])
                fable = _fable_entries(result)
                self.assertEqual([(e["launch"], e["requires_approval"]) for e in fable], [("skip", True)])
                self.assertEqual(len(result["roster"]), len(base["roster"]) + 1)
                self.assertEqual(_roles(result), _roles(base))
                self.assertIn("fable requested, awaiting owner approval", " ".join(result["reasons"]))
                self.assertEqual(result["approvals"], [])
        medium = _route(owner_named=True)
        self.assertNotIn(("large", "claude-opus-5-5", "xhigh"), [r[1:] for r in _roles(medium)])

    def test_fable_effort_never_above_high(self):
        cat = copy.deepcopy(CATALOG)
        cat["router"]["fable"]["effort"] = "max"
        cat["router"]["effort_ceiling"] = {"tier": "orchestrator", "effort": "max"}
        for catalog in (CATALOG, cat):
            for approvals in ([], ["escalate-fable"]):
                result = _route(catalog, task_kind="review", tier="high", lane="opus", critical_hit=True,
                                owner_named=True, approvals=approvals)
                with self.subTest(tampered=catalog is cat, approvals=approvals):
                    self.assertEqual([e["effort"] for e in _fable_entries(result)], ["high"])
        lowered = copy.deepcopy(CATALOG)
        entry = next(e for e in lowered["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)
        entry["effort_ceiling"] = "medium"
        result = _route(lowered, owner_named=True, approvals=["escalate-fable"])
        self.assertEqual([e["effort"] for e in _fable_entries(result)], ["medium"])

    def test_catalog_caps_fable_effort_and_context(self):
        entry = next(e for e in CATALOG["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)
        self.assertEqual(entry["effort_ceiling"], "high")
        self.assertEqual(entry["max_context_tokens"], 120000)
        self.assertIn("Assumed", entry["_comment"])
        self.assertNotIn("fallback", CATALOG["router"]["fable"])

    def test_fable_entry_carries_max_context_tokens_from_the_catalog(self):
        result = _route(owner_named=True, approvals=["escalate-fable"])
        self.assertEqual([e["max_context_tokens"] for e in _fable_entries(result)], [120000])
        cat = copy.deepcopy(CATALOG)
        next(e for e in cat["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)["max_context_tokens"] = 50000
        tuned = _route(cat, owner_named=True)
        self.assertEqual([e["max_context_tokens"] for e in _fable_entries(tuned)], [50000])

    def test_cost_counts_fable_only_when_approved_and_at_the_context_cap(self):
        base = _route()
        denied = _route(owner_named=True)
        self.assertEqual(denied["cost_estimate_usd"], base["cost_estimate_usd"])
        approved = _route(owner_named=True, approvals=["escalate-fable"])
        tokens_in, tokens_out = router._tokens(CATALOG, "orchestrator", router.FABLE_ROLE, FABLE)
        self.assertLessEqual(tokens_in, 120000)
        expected = round(base["cost_estimate_usd"] + (tokens_in * 10.0 + tokens_out * 50.0) / 1_000_000, 6)
        self.assertAlmostEqual(approved["cost_estimate_usd"], expected, places=6)
        cat = copy.deepcopy(CATALOG)
        next(e for e in cat["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)["max_context_tokens"] = 10000
        self.assertEqual(router._tokens(cat, "orchestrator", router.FABLE_ROLE, FABLE)[0], 10000)

    def test_owner_request_does_not_rescue_a_step_that_goes_to_the_owner(self):
        result = _route(owner_named=True, approvals=["escalate-fable"], prior={"stalls": 2})
        self.assertEqual((result["rule"], result["status"], result["roster"]), ("P1", "owner", []))

    def test_fable_role_is_the_deep_reasoner(self):
        self.assertEqual(router.FABLE_ROLE, "generic-deep-reasoner")
        self.assertEqual(router.ROLE_TIER[router.FABLE_ROLE], CATALOG["router"]["fable"]["tier"])
        self.assertEqual(CATALOG["router"]["fable"]["role"], router.FABLE_ROLE)
        self.assertIn(router.FABLE_ROLE, CATALOG["tiers"]["orchestrator"]["roles"])
        self.assertIn(router.FABLE_ROLE, CATALOG["tiers"]["orchestrator"]["token_assumptions"])
        # the frontmatter fallback is the admitted orchestrator model; Fable only on approval
        self.assertEqual(router.fallback_model(CATALOG, router.FABLE_ROLE), "claude-opus-5-5")

    def test_offline_drops_an_approved_fable_first_and_the_team_still_runs(self):
        cat = _fixture_catalog(local_small=True)
        base = _route(cat, task_kind="map", offline=True)
        result = _route(cat, task_kind="map", offline=True, owner_named=True, approvals=["escalate-fable"])
        self.assertEqual((result["rule"], result["status"]), (router.FABLE_RULE, "ok"))
        self.assertEqual(_roles(result), _roles(base))
        self.assertTrue(_running(result))
        self.assertEqual([e["launch"] for e in _fable_entries(result)], ["skip"])
        reasons = " ".join(result["reasons"])
        self.assertIn(f"offline: dropped the owner-requested {router.FABLE_ROLE} step first", reasons)
        self.assertNotIn("runs", reasons)
        self.assertEqual(result["approvals"], [])

    def test_offline_without_a_local_team_is_blocked_as_usual(self):
        result = _route(task_kind="map", offline=True, owner_named=True, approvals=["escalate-fable"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(_running(result), [])
        self.assertIn(f"dropped the owner-requested {router.FABLE_ROLE} step first", " ".join(result["reasons"]))

    def test_budget_drops_an_approved_fable_first_and_the_team_that_fits_stays_ok(self):
        base = _route()
        result = _route(owner_named=True, approvals=["escalate-fable"], budget_usd=base["cost_estimate_usd"])
        self.assertEqual((result["rule"], result["status"]), (router.FABLE_RULE, "ok"))
        self.assertEqual(_roles(result), _roles(base))
        self.assertEqual([e["launch"] for e in _fable_entries(result)], ["skip"])
        self.assertEqual(result["cost_estimate_usd"], base["cost_estimate_usd"])
        reasons = " ".join(result["reasons"])
        self.assertIn(f"budget: dropped the owner-requested {router.FABLE_ROLE} step first", reasons)
        self.assertNotIn("runs", reasons)
        self.assertEqual(result["approvals"], [])
        # a stale-map cartographer (optional) stays when dropping Fable is enough
        stale = _route(map_age_days=30)
        kept = _route(map_age_days=30, owner_named=True, approvals=["escalate-fable"],
                      budget_usd=stale["cost_estimate_usd"])
        self.assertEqual((kept["status"], _roles(kept)), ("ok", _roles(stale)))

    def test_budget_below_the_team_is_over_budget_with_fable_dropped(self):
        result = _route(owner_named=True, approvals=["escalate-fable"], budget_usd=0.0001)
        self.assertEqual(result["status"], "over_budget")
        self.assertEqual([e["launch"] for e in _fable_entries(result)], ["skip"])
        self.assertEqual(_roles(result), _roles(_route()))

    def test_approved_fable_reason_says_runs_only_after_the_post_passes(self):
        result = _route(owner_named=True, approvals=["escalate-fable"], budget_usd=100.0, offline=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reasons"][-1], f"owner approved {router.FABLE_RULE}: {FABLE} runs")

    def _without_fable(self):
        removed = copy.deepcopy(CATALOG)
        removed["tiers"]["orchestrator"]["candidates"] = [
            e for e in removed["tiers"]["orchestrator"]["candidates"] if e["id"] != FABLE]
        unknown = copy.deepcopy(CATALOG)
        unknown["router"]["fable"]["model"] = "claude-fable-9"
        no_model = copy.deepcopy(CATALOG)
        del no_model["router"]["fable"]["model"]
        no_tier = copy.deepcopy(CATALOG)
        del no_tier["tiers"]["orchestrator"]
        return {"entry removed": removed, "unknown model": unknown, "no model key": no_model, "no tier": no_tier}

    def test_a_catalog_without_fable_skips_the_step_and_never_errors(self):
        for name, cat in self._without_fable().items():
            for case in (dict(), dict(task_kind="review", tier="high", lane="opus"), dict(tier="exempt")):
                with self.subTest(catalog=name, case=case):
                    base = _route(cat, **case)
                    self.assertEqual(base["status"], "ok")
                    result = _route(cat, owner_named=True, approvals=["escalate-fable"], **case)
                    self.assertEqual((result["rule"], result["base_rule"], result["status"]),
                                     (router.FABLE_RULE, base["rule"], "ok"))
                    self.assertEqual(result["roster"], base["roster"])
                    self.assertEqual(result["approvals"], [])
                    self.assertIn("step skipped", " ".join(result["reasons"]))

    def test_fable_may_run_alone_when_the_base_roster_is_empty(self):
        result = _route(tier="exempt", task_kind="review", owner_named=True, approvals=["escalate-fable"])
        self.assertEqual((result["rule"], result["base_rule"], result["status"]), (router.FABLE_RULE, "B0", "ok"))
        self.assertEqual([(e["role"], e["model"], e["effort"], e["launch"], e["step"]) for e in result["roster"]],
                         [(router.FABLE_ROLE, FABLE, "high", "run", 1)])
        self.assertEqual(result["approvals"], ["escalate-fable"])


def _at_most_high(test, result):
    """No Fable entry launches with an unknown effort or one above high."""
    for e in _fable_entries(result):
        test.assertIn(e["effort"], router.EFFORT_RANK)
        test.assertLessEqual(router.EFFORT_RANK[e["effort"]], router.EFFORT_RANK["high"])


class FableEffortCapTests(unittest.TestCase):
    """L13: the cap holds whatever the catalog's effort ladder says."""

    def _fable_entry(self, cat):
        return next(e for e in cat["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)

    def test_a_ladder_above_the_cap_fails_closed_never_xhigh_or_max(self):
        cat = copy.deepcopy(CATALOG)
        entry = self._fable_entry(cat)
        entry["effort_levels"] = ["xhigh", "max"]
        entry["effort_by_role"] = {}
        entry["effort_default"] = "xhigh"
        for approvals in ([], ["escalate-fable"]):
            with self.subTest(approvals=approvals):
                result = _route(cat, owner_named=True, approvals=approvals)
                _at_most_high(self, result)
                self.assertEqual((result["status"], result["roster"]), ("error", []))
                self.assertIn("above", " ".join(result["reasons"]))

    def test_unknown_effort_names_are_guard_catalog(self):
        cat = copy.deepcopy(CATALOG)
        self._fable_entry(cat)["effort_levels"] = ["ultra"]
        cat["router"]["fable"]["effort"] = "ultra"
        only_slot = copy.deepcopy(CATALOG)
        only_slot["router"]["fable"]["effort"] = "ultra"
        any_entry = copy.deepcopy(CATALOG)
        any_entry["tiers"]["medium"]["candidates"][0]["effort_levels"] = ["medium", "ultra"]
        for name, catalog in (("fable ladder + slot", cat), ("slot effort", only_slot), ("any ladder", any_entry)):
            with self.subTest(case=name):
                result = _route(catalog, owner_named=True, approvals=["escalate-fable"])
                _guarded(self, result, "guard:catalog")
                _at_most_high(self, result)

    def test_the_hard_cap_holds_without_the_catalog_ceiling(self):
        cat = copy.deepcopy(CATALOG)
        del self._fable_entry(cat)["effort_ceiling"]
        cat["router"]["fable"]["effort"] = "max"
        cat["router"]["effort_ceiling"] = {"tier": "orchestrator", "effort": "max"}
        result = _route(cat, owner_named=True, approvals=["escalate-fable"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual([e["effort"] for e in _fable_entries(result)], ["high"])
        # negative control: this test is what catches a raised FABLE_EFFORT_CAP
        with mock.patch.object(router, "FABLE_EFFORT_CAP", "max"):
            raised = _route(cat, owner_named=True, approvals=["escalate-fable"])
        self.assertEqual([e["effort"] for e in _fable_entries(raised)], ["max"])


class ContextCapTests(unittest.TestCase):
    """L13: the Fable entry's bounded context is mandatory and never vanishes."""

    def test_fable_entry_needs_a_positive_int_context_cap(self):
        for value in (0, -1, "120000", True, 1.5, None):
            cat = copy.deepcopy(CATALOG)
            entry = next(e for e in cat["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)
            if value is None:
                del entry["max_context_tokens"]
            else:
                entry["max_context_tokens"] = value
            with self.subTest(value=value):
                _guarded(self, _route(cat, owner_named=True, approvals=["escalate-fable"]),
                         "guard:catalog", "max_context_tokens")

    def test_a_zero_tier_cap_is_guard_catalog(self):
        cat = copy.deepcopy(CATALOG)
        cat["tiers"]["orchestrator"]["max_context_tokens"] = 0
        _guarded(self, _route(cat), "guard:catalog", "max_context_tokens")

    def test_context_cap_treats_only_none_as_absent(self):
        catalog = {"tiers": {"t": {"max_context_tokens": 0, "candidates": [
            {"id": "m", "provider": "p", "status": "admitted", "max_context_tokens": 500}]}}}
        self.assertEqual(router._context_cap(catalog, "t", "m"), 0)
        catalog["tiers"]["t"]["max_context_tokens"] = None
        self.assertEqual(router._context_cap(catalog, "t", "m"), 500)
        catalog["tiers"]["t"]["candidates"][0]["max_context_tokens"] = None
        self.assertIsNone(router._context_cap(catalog, "t", "m"))

    def test_the_fable_step_carries_the_cap_in_the_roster(self):
        result = _route(tier="exempt", owner_named=True)
        self.assertEqual([(e["role"], e["max_context_tokens"]) for e in result["roster"]],
                         [(router.FABLE_ROLE, 120000)])


class LogTests(unittest.TestCase):
    def test_log_line_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "task.json"
            log_path = Path(tmp) / "runs" / "routing.jsonl"
            task_path.write_text(json.dumps(_task(task_kind="review", tier="high")), encoding="utf-8")
            proc = subprocess.run(
                ["bash", str(TOOLS / "bin" / "route.sh"), str(task_path), "--as-of", AS_OF, "--log", str(log_path)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            line = json.loads(lines[0])
            self.assertEqual(set(line), {"approvals", "as_of", "base_rule", "catalog_version", "delegation",
                                         "inputs_hash", "repo", "rule", "status", "roster"})
            self.assertIsNone(line["repo"], "a task without repo logs repo: null, which no guard matches")
            self.assertEqual(line["approvals"], [])
            self.assertEqual((line["rule"], line["base_rule"], line["status"], line["as_of"]), ("B6", "B6", "ok", AS_OF))
            self.assertEqual(json.loads(proc.stdout)["inputs_hash"], line["inputs_hash"])

    def test_log_line_carries_delegate_and_background_per_entry(self):
        # T7 follow-up: the main-session guard reads per-entry delegation, never infers it from counts
        line = json.loads(router.log_line(_route(task_kind="implement", tier="medium", modules=3, changed_lines=400)))
        self.assertTrue(line["roster"])
        for entry in line["roster"]:
            self.assertIn(entry["delegate"], ("subagent", "main"))
            self.assertIsInstance(entry["background"], bool)

    def test_log_inside_target_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "target"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
            task_path = Path(tmp) / "task.json"
            task_path.write_text(json.dumps(_task(repo=str(repo))), encoding="utf-8")
            log_path = repo / "runs" / "routing.jsonl"
            code = router.main([str(task_path), "--as-of", AS_OF, "--log", str(log_path)])
            self.assertEqual(code, 2)
            self.assertFalse(log_path.exists())

    def test_log_line_carries_the_tasks_resolved_repo(self):
        # T16 (B-006/A-004): the main-session guard matches a decision to its repo, never a line without one
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "target"
            (repo / "sub").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
            task_path = Path(tmp) / "task.json"
            task_path.write_text(json.dumps(_task(repo=str(repo / "sub"))), encoding="utf-8")
            log_path = Path(tmp) / "runs" / "routing.jsonl"
            self.assertEqual(router.main([str(task_path), "--as-of", AS_OF, "--log", str(log_path)]), 0)
            line = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(line["repo"], str(repo.resolve()))
        self.assertEqual(json.loads(router.log_line(_route(), repo="/x/y"))["repo"], "/x/y")

    def test_log_line_records_the_owner_approval(self):
        result = _route(owner_named=True, approvals=["escalate-fable"])
        line = json.loads(router.log_line(result))
        self.assertEqual(line["approvals"], ["escalate-fable"])
        self.assertIn(FABLE, [e["model"] for e in line["roster"] if e["launch"] == "run"])


def _guarded(test, result, rule, field=None):
    test.assertEqual((result["status"], result["rule"], result["roster"]), ("error", rule, []))
    test.assertEqual(result["cost_estimate_usd"], 0.0)
    test.assertEqual(result["approvals"], [])
    if field:
        test.assertIn(field, " ".join(result["reasons"]))


class ApprovalGateTests(unittest.TestCase):
    """L6 security: only the exact list member `escalate-fable` launches Fable,
    and the output records exactly the approvals that granted a launch."""

    def test_string_approvals_cannot_launch_fable(self):
        for approvals in ("not-escalate-fable-denied", "escalate-fable", {"escalate-fable": True},
                          ["escalate-fable", 1], [["escalate-fable"]], 1):
            with self.subTest(approvals=approvals):
                result = _route(owner_named=True, approvals=approvals)
                _guarded(self, result, "guard:input", "approvals")
                self.assertEqual([e for e in _running(result) if e["model"] == FABLE], [])
                self.assertEqual(json.loads(router.log_line(result))["approvals"], [])

    def test_substring_of_the_rule_is_not_an_approval(self):
        for approvals in (["not-escalate-fable-denied"], ["escalate-fable "], ["ESCALATE-FABLE"]):
            with self.subTest(approvals=approvals):
                result = _route(owner_named=True, approvals=approvals)
                self.assertEqual(result["rule"], router.FABLE_RULE)
                self.assertEqual([e for e in _running(result) if e["model"] == FABLE], [])
                self.assertEqual(result["approvals"], [])

    def test_recorded_approvals_are_exactly_the_ones_that_granted_a_launch(self):
        granted = _route(owner_named=True, approvals=["other", "escalate-fable"])
        self.assertEqual(granted["approvals"], ["escalate-fable"])
        unused = _route(approvals=["escalate-fable"])
        self.assertEqual((unused["rule"], unused["approvals"]), ("B3", []))
        self.assertEqual(json.loads(router.log_line(unused))["approvals"], [])


class InputGuardTests(unittest.TestCase):
    """Malformed input never raises: one validation step returns guard:input,
    a reason naming the field, an empty roster."""

    CASES = [
        ("budget_usd", {"budget_usd": -1}), ("budget_usd", {"budget_usd": "5"}),
        ("budget_usd", {"budget_usd": True}), ("budget_usd", {"budget_usd": float("inf")}),
        ("map_age_days", {"map_age_days": -1}), ("map_age_days", {"map_age_days": "3"}),
        ("map_age_days", {"map_age_days": True}),
        ("changed_lines", {"changed_lines": -1}), ("changed_lines", {"changed_lines": 1.5}),
        ("changed_lines", {"changed_lines": "10"}), ("changed_lines", {"changed_lines": True}),
        ("modules", {"modules": [1, "a"]}), ("modules", {"modules": "abc"}), ("modules", {"modules": -1}),
        ("modules", {"modules": [None]}), ("modules", {"modules": True}),
        ("new_comments", {"new_comments": -1}), ("new_comments", {"new_comments": "2"}),
        ("new_comments", {"new_comments": True}), ("new_comments", {"new_comments": 1.5}),
        ("prior", {"prior": []}), ("prior", {"prior": "x"}),
        ("prior.stalls", {"prior": {"stalls": -1}}), ("prior.stalls", {"prior": {"stalls": "2"}}),
        ("prior.stalls", {"prior": {"stalls": True}}),
        ("prior.escalated_count", {"prior": {"escalated_count": 1.5}}),
        ("prior.findings", {"prior": {"findings": "many"}}), ("prior.findings", {"prior": {"findings": -2}}),
        ("prior.schema_fail", {"prior": {"schema_fail": "x"}}),
        ("prior.truncated", {"prior": {"truncated": "yes"}}),
        ("prior.p0_from_lower_tier", {"prior": {"p0_from_lower_tier": "huge"}}),
        ("prior.p0_from_lower_tier", {"prior": {"p0_from_lower_tier": True}}),
        ("prior.p0_from_lower_tier", {"prior": {"p0_from_lower_tier": 1}}),
        ("prior.tier", {"prior": {"tier": ["medium"], "truncated": True, "role": "generic-proposer"}}),
        ("prior.role", {"prior": {"role": {"x": 1}, "schema_fail": 1}}),
        ("owner_named", {"owner_named": "yes"}), ("critical_hit", {"critical_hit": 1}),
        ("offline", {"offline": "no"}),
    ]

    def test_each_malformed_field_is_guard_input_never_an_exception(self):
        for field, overrides in self.CASES:
            with self.subTest(field=field, value=overrides):
                _guarded(self, _route(**overrides), "guard:input", field)

    def test_task_that_is_not_an_object(self):
        for task in ([], "task", None, 3, [_task()]):
            with self.subTest(task=task):
                _guarded(self, router.route(task, CATALOG, AS_OF), "guard:input", "task")

    def test_valid_edge_values_still_route(self):
        for overrides in ({"budget_usd": 0}, {"map_age_days": 0}, {"map_age_days": None}, {"changed_lines": 0},
                          {"modules": ["a", "b"]}, {"modules": 0}, {"new_comments": 0}, {"prior": None},
                          {"prior": {"p0_from_lower_tier": False}}, {"approvals": None}):
            with self.subTest(overrides=overrides):
                self.assertNotEqual(_route(**overrides)["rule"], "guard:input")

    def test_as_of_must_be_a_real_calendar_date(self):
        for as_of in ("2026-13-45", "2026-02-30", "2026-1-16", "20261016", 20261016, None):
            with self.subTest(as_of=as_of):
                _guarded(self, _route(as_of=as_of), "guard:as_of")
        self.assertEqual(_route(as_of="2028-02-29")["status"], "ok")


class CatalogGuardTests(unittest.TestCase):
    """A malformed catalog is guard:catalog, never a traceback."""

    def _broken(self):
        cases = {"list": [], "string": "x", "no tiers": {"version": "v"}}
        cat = copy.deepcopy(CATALOG)
        cat["tiers"]["medium"]["candidates"][0] = "claude-sonnet-5-5"
        cases["candidate not an object"] = cat
        for key in ("provider", "id", "usd_in"):
            cat = copy.deepcopy(CATALOG)
            del cat["tiers"]["medium"]["candidates"][0][key]
            cases[f"missing {key}"] = cat
        cat = copy.deepcopy(CATALOG)
        del cat["tiers"]["medium"]
        cases["tier missing"] = cat
        cat = copy.deepcopy(CATALOG)
        cat["tiers"]["large"]["candidates"] = {"id": "x"}
        cases["candidates not a list"] = cat
        for value in (0, -1, "3", True, 1.5):
            cat = copy.deepcopy(CATALOG)
            cat["router"]["max_parallel"] = value
            cases[f"max_parallel {value!r}"] = cat
        cat = copy.deepcopy(CATALOG)
        cat["router"] = ["x"]
        cases["router not an object"] = cat
        return cases

    def test_malformed_catalog_is_guard_catalog(self):
        for name, catalog in self._broken().items():
            for task in (_task(task_kind="map", modules=4), _task(owner_named=True, approvals=["escalate-fable"])):
                with self.subTest(case=name, kind=task["task_kind"]):
                    result = router.route(task, catalog, AS_OF)
                    _guarded(self, result, "guard:catalog")

    def test_the_kit_catalog_passes_the_check(self):
        self.assertEqual(_route()["status"], "ok")


class HardLimitTests(unittest.TestCase):
    """Limits a catalog cannot override: fan-out cap 3, Fable and non-admitted
    models never launch without approval, no automatic `max`."""

    def test_catalog_cap_above_three_is_clamped_to_three(self):
        cat = copy.deepcopy(CATALOG)
        cat["router"]["max_parallel"] = 10
        result = router.route(_task(task_kind="map", modules=7), cat, AS_OF)
        per_step = {}
        for e in _running(result):
            per_step[e["step"]] = per_step.get(e["step"], 0) + 1
        self.assertEqual(len(_running(result)), 7)
        self.assertEqual(max(per_step.values()), 3)
        cat["router"]["max_parallel"] = 2
        lower = router.route(_task(task_kind="map", modules=4), cat, AS_OF)
        self.assertEqual(sorted({e["step"] for e in lower["roster"]}), [1, 2])

    def _tampered(self):
        """Fable marked admitted everywhere and placed first in every tier."""
        cat = copy.deepcopy(CATALOG)
        fable = next(e for e in cat["tiers"]["orchestrator"]["candidates"] if e["id"] == FABLE)
        fable["status"] = "admitted"
        for tier in ("small", "medium", "large"):
            cat["tiers"][tier]["candidates"].insert(0, copy.deepcopy(fable))
        cat["tiers"]["orchestrator"]["candidates"].sort(key=lambda e: e["id"] != FABLE)
        return cat

    def test_tampered_catalog_with_fable_admitted_still_needs_approval(self):
        cat = self._tampered()
        tasks = [_task(task_kind=k, tier=t, lane="opus" if t == "high" else "sonnet")
                 for k in router.TASK_KINDS for t in router.RDD_TIERS]
        tasks += [_task(owner_named=True), _task(owner_named=True, task_kind="review", tier="high", lane="opus",
                                                 critical_hit=True), _task(task_kind="map", modules=4),
                  _task(prior={"truncated": True, "role": "generic-proposer"}),
                  _task(prior={"schema_fail": 2, "role": "generic-verifier"})]
        for task in tasks:
            result = router.route(task, cat, AS_OF)
            with self.subTest(kind=task["task_kind"], tier=task["tier"], prior=task["prior"]):
                self.assertEqual([e for e in _running(result) if e["model"] == FABLE], [])
                for e in result["roster"]:
                    if e["model"] == FABLE:
                        self.assertEqual((e["launch"], e["requires_approval"]), ("skip", True))

    def test_a_legacy_fallback_in_the_catalog_is_ignored(self):
        cat = copy.deepcopy(CATALOG)
        cat["router"]["fable"]["fallback"] = {"model": "claude-opus-5-5", "tier": "large", "effort": "xhigh"}
        result = router.route(_task(owner_named=True), cat, AS_OF)
        self.assertEqual(result["rule"], router.FABLE_RULE)
        self.assertNotIn(("large", "claude-opus-5-5", "xhigh"), [r[1:] for r in _roles(result)])

    def test_any_model_in_the_fable_slot_needs_approval(self):
        for model, tier in (("gpt-6-astra", "large"), ("claude-opus-5-5", "large")):
            cat = copy.deepcopy(CATALOG)
            cat["router"]["fable"].update(model=model, tier=tier)
            with self.subTest(model=model):
                result = router.route(_task(owner_named=True), cat, AS_OF)
                slot = [e for e in result["roster"] if e["role"] == router.FABLE_ROLE]
                self.assertEqual([(e["model"], e["launch"], e["requires_approval"]) for e in slot],
                                 [(model, "skip", True)])

    def test_approved_fable_in_a_tampered_catalog_runs_only_on_the_escalation(self):
        cat = self._tampered()
        approved = router.route(_task(owner_named=True, approvals=["escalate-fable"]), cat, AS_OF)
        self.assertEqual(len([e for e in _running(approved) if e["model"] == FABLE]), 1)
        self.assertEqual([e["role"] for e in _running(approved) if e["model"] == FABLE], [router.FABLE_ROLE])
        self.assertEqual([e["effort"] for e in _running(approved) if e["model"] == FABLE], ["high"])
        default = router.route(_task(task_kind="review", tier="high", lane="opus", approvals=["escalate-fable"]), cat, AS_OF)
        self.assertEqual([e for e in _running(default) if e["model"] == FABLE], [])

    def test_p2_and_p6_never_keep_max(self):
        p2 = _route(task_kind="map", modules=2, prior={
            "truncated": True, "role": "generic-cartographer", "tier": "medium", "effort": "max"})
        self.assertEqual(p2["rule"], "P2")
        self.assertEqual({e["effort"] for e in _running(p2)}, {"xhigh"})
        p6 = _route(prior={"verifier": "FAIL", "tier": "large", "effort": "max"})
        self.assertEqual(p6["rule"], "P6")
        self.assertNotIn("max", {e["effort"] for e in _running(p6)})

    def test_escalation_never_reaches_max_even_if_the_catalog_allows_it(self):
        cat = copy.deepcopy(CATALOG)
        cat["router"]["never_automatic_effort"] = []
        cat["router"]["effort_ceiling"] = {"tier": "large", "effort": "max"}
        step = router.escalate(cat, "generic-challenger", "large", "xhigh", "diligence")
        self.assertNotEqual((step or (None, None))[1], "max")
        p2 = router.route(_task(task_kind="map", modules=1, prior={
            "truncated": True, "role": "generic-cartographer", "tier": "large", "effort": "max"}), cat, AS_OF)
        self.assertNotIn("max", {e["effort"] for e in _running(p2)})


class CliGuardTests(unittest.TestCase):
    """bin/route.sh: malformed JSON, a JSON list, guard:input and guard:catalog
    exit 2 with one line on stderr, never a traceback."""

    def _run(self, task_text, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.json"
            path.write_text(task_text, encoding="utf-8")
            args = ["bash", str(TOOLS / "bin" / "route.sh"), str(path), "--as-of", AS_OF]
            for name, text in extra:
                other = Path(tmp) / name
                other.write_text(text, encoding="utf-8")
                args += ["--config", str(other)]
            return subprocess.run(args, capture_output=True, text=True, timeout=60)

    def _assert_usage(self, proc):
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1, proc.stderr)

    def test_malformed_json_and_list_exit_two(self):
        for text in ("{not json", "[]", json.dumps([_task()]), "\"task\"", ""):
            with self.subTest(text=text):
                self._assert_usage(self._run(text))

    def test_guard_input_exits_two(self):
        for task in (_task(modules=[1, "a"]), _task(owner_named=True, approvals="not-escalate-fable-denied")):
            with self.subTest(task=task):
                proc = self._run(json.dumps(task))
                self._assert_usage(proc)
                self.assertNotIn(FABLE, proc.stdout)

    def test_guard_catalog_exits_two(self):
        broken = copy.deepcopy(CATALOG)
        broken["router"]["max_parallel"] = 0
        for text in ("[]", json.dumps(broken)):
            with self.subTest(catalog=text[:20]):
                self._assert_usage(self._run(json.dumps(_task(task_kind="map", modules=4)), ("cat.json", text)))


class OfflineSourceTests(unittest.TestCase):
    """L4: offline comes from the task, else the active project config, else
    METODO_OFFLINE=1; input wins over config wins over env. route() stays pure:
    only main() (and the MCP tool) resolve the source."""

    def test_task_key_wins_over_config_and_env(self):
        for value in (False, True):
            with self.subTest(task=value):
                task = router.resolve_offline({"offline": value}, {"offline": not value}, {"METODO_OFFLINE": "1"})
                self.assertIs(task["offline"], value)

    def test_config_wins_over_env(self):
        task = router.resolve_offline({}, {"offline": False}, {"METODO_OFFLINE": "1"})
        self.assertFalse(task.get("offline"))
        task = router.resolve_offline({}, {"offline": True}, {})
        self.assertIs(task["offline"], True)

    def test_env_applies_only_without_task_or_config_key(self):
        self.assertIs(router.resolve_offline({}, {}, {"METODO_OFFLINE": "1"})["offline"], True)
        self.assertIs(router.resolve_offline({}, None, {"METODO_OFFLINE": "1"})["offline"], True)
        # negative controls: any other env value, or no source at all, leaves the task untouched
        self.assertNotIn("offline", router.resolve_offline({}, {}, {"METODO_OFFLINE": "0"}))
        self.assertNotIn("offline", router.resolve_offline({}, {}, {}))

    def test_resolve_does_not_mutate_the_input(self):
        task = {"task_kind": "map"}
        router.resolve_offline(task, {"offline": True}, {})
        self.assertEqual(task, {"task_kind": "map"})

    def test_project_config_path_prefers_the_env_then_the_tools_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            (tools / "config").mkdir(parents=True)
            (tools / "config" / "project.json").write_text(json.dumps({"offline": True}), encoding="utf-8")
            other = Path(tmp) / "other.json"
            other.write_text(json.dumps({"offline": False}), encoding="utf-8")
            self.assertEqual(router.load_project_config(tools, {}), {"offline": True})
            self.assertEqual(router.load_project_config(tools, {"METODO_PROJECT_CONFIG": str(other)}), {"offline": False})
            # unreadable config is no config: the env source still applies
            self.assertEqual(router.load_project_config(tools, {"METODO_PROJECT_CONFIG": str(Path(tmp) / "nope.json")}), {})

    def _main(self, task: dict, env: dict) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "task.json"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            clean = {k: v for k, v in env.items()}
            with mock.patch.dict("os.environ", clean, clear=False):
                for key in ("METODO_OFFLINE", "METODO_PROJECT_CONFIG"):
                    if key not in clean:
                        os.environ.pop(key, None)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = router.main([str(task_path), "--as-of", AS_OF])
            return code, json.loads(out.getvalue())

    def test_main_reads_offline_from_the_active_project_config(self):
        task = {k: v for k, v in _task(task_kind="map").items() if k != "offline"}
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "project.json"
            config.write_text(json.dumps({"offline": True}), encoding="utf-8")
            code, result = self._main(task, {"METODO_PROJECT_CONFIG": str(config)})
            self.assertEqual((code, result["status"]), (1, "blocked"))
            # config offline:false beats METODO_OFFLINE=1
            config.write_text(json.dumps({"offline": False}), encoding="utf-8")
            code, result = self._main(task, {"METODO_PROJECT_CONFIG": str(config), "METODO_OFFLINE": "1"})
            self.assertEqual((code, result["status"]), (0, "ok"))
            # no key in the config: the env applies
            config.write_text(json.dumps({}), encoding="utf-8")
            code, result = self._main(task, {"METODO_PROJECT_CONFIG": str(config), "METODO_OFFLINE": "1"})
            self.assertEqual((code, result["status"]), (1, "blocked"))
            # the task's own key wins over both
            code, result = self._main(dict(task, offline=False), {"METODO_PROJECT_CONFIG": str(config), "METODO_OFFLINE": "1"})
            self.assertEqual((code, result["status"]), (0, "ok"))


REVIEW_ROLES = ("generic-challenger", "generic-blind-spot-adversary", "generic-judge", "generic-verifier",
                "generic-deep-reasoner", "generic-style-reviewer", "generic-boundary-reviewer",
                "generic-human-reviewer", "generic-comment-gate")


def _by_role(result, role):
    return [e for e in result["roster"] if e["role"] == role]


def _delegation_catalog(**values):
    cat = copy.deepcopy(CATALOG)
    cat["router"].setdefault("delegation", {}).update(values)
    return cat


class DelegationTests(unittest.TestCase):
    """S1 (odd/tasks/delegation-context.md): per roster entry the router says
    who runs it (`delegate`: subagent | main) and how (`background`); the main
    session is always the coordinator. Review roles are always subagents."""

    PRIORS = ([{}, {"findings": 2}, {"findings": 0}, {"disagreement": True}, {"p0_from_lower_tier": "small"},
               {"verifier": "FAIL"}]
              + [{"schema_fail": 1, "role": r} for r in REVIEW_ROLES]
              + [{"truncated": True, "role": r} for r in REVIEW_ROLES])
    CATALOG_TRIAL = _fixture_catalog(trial=True)

    def _grid(self):
        for kind in router.TASK_KINDS:
            for tier in router.RDD_TIERS:
                lane = "opus" if tier == "high" else "sonnet"
                for prior in self.PRIORS:
                    for extra in ({}, {"owner_named": True, "approvals": ["escalate-fable"]},
                                  {"critical_hit": True, "new_comments": 2}, {"changed_lines": 1, "modules": 1}):
                        task = _task(task_kind=kind, tier=tier, lane=lane, prior=prior, **extra)
                        yield task, router.route(task, self.CATALOG_TRIAL, AS_OF)

    def test_every_review_role_is_a_subagent_in_every_rule_row(self):
        seen, rules = set(), set()
        for task, result in self._grid():
            rules.add(result["rule"])
            for e in result["roster"]:
                with self.subTest(kind=task["task_kind"], tier=task["tier"], prior=task["prior"], role=e["role"]):
                    self.assertIn(e["delegate"], ("subagent", "main"))
                    self.assertIsInstance(e["background"], bool)
                    self.assertIsInstance(e["delegation_reason"], str)
                    self.assertTrue(e["delegation_reason"] and "\n" not in e["delegation_reason"])
                    if e["role"] in REVIEW_ROLES:
                        seen.add(e["role"])
                        self.assertEqual(e["delegate"], "subagent", e["delegation_reason"])
                    if e["delegate"] == "main":
                        self.assertFalse(e["background"])
        self.assertEqual(seen, set(REVIEW_ROLES))
        self.assertTrue({"B1", "B2", "B3", "B4", "B5", "B6", "B8", "P2", "P3", "P4", "P5", "P6", router.FABLE_RULE} <= rules)
        self.assertTrue(set(REVIEW_ROLES) <= set(router.REVIEW_ROLES))

    def test_the_main_session_is_always_the_coordinator(self):
        for result in (_route(), _route(task_kind="dance"), _route(budget_usd=-1), _route(tier="exempt")):
            with self.subTest(rule=result["rule"]):
                self.assertEqual(result["coordinator"], "main")

    def test_small_writer_runs_in_the_main_session(self):
        result = _route(changed_lines=50, modules=1)
        proposer = _by_role(result, "generic-proposer")[0]
        self.assertEqual((proposer["delegate"], proposer["background"]), ("main", False))
        self.assertIn("small", proposer["delegation_reason"])
        self.assertEqual(_by_role(result, "generic-verifier")[0]["delegate"], "subagent")

    def test_large_writer_runs_in_a_subagent(self):
        for overrides in ({"changed_lines": 121}, {"modules": 2}, {"modules": ["a", "b"]}, {"changed_lines": None},
                          {"tier": "high", "lane": "opus", "changed_lines": 1}):
            with self.subTest(overrides=overrides):
                proposer = _by_role(_route(**overrides), "generic-proposer")[0]
                self.assertEqual((proposer["delegate"], proposer["background"]), ("subagent", False))
                self.assertIn("not small", proposer["delegation_reason"])
        boundary = _by_role(_route(changed_lines=120), "generic-proposer")[0]
        self.assertEqual(boundary["delegate"], "main")

    def test_writer_at_exempt_or_low_tier_is_small_whatever_its_size(self):
        for tier in ("exempt", "low"):
            with self.subTest(tier=tier):
                result = _route(tier=tier, changed_lines=5000, modules=9, prior={"verifier": "FAIL"})
                self.assertEqual(result["rule"], "P6")
                self.assertEqual(_by_role(result, "generic-proposer")[0]["delegate"], "main")

    def test_mechanic_follows_the_writer_rule(self):
        prior = {"schema_fail": 1, "role": "generic-mechanic"}
        small = _by_role(_route(prior=prior, changed_lines=10), "generic-mechanic")[0]
        large = _by_role(_route(prior=prior, changed_lines=500), "generic-mechanic")[0]
        self.assertEqual((small["delegate"], large["delegate"]), ("main", "subagent"))
        self.assertEqual((small["background"], large["background"]), (False, False))

    def test_cartographer_on_a_fresh_map_one_module_few_reads_is_main(self):
        for overrides in ({}, {"read_files": 8}, {"read_files": 0}):
            with self.subTest(overrides=overrides):
                result = _route(task_kind="map", modules=1, map_age_days=1, **overrides)
                self.assertEqual([e["delegate"] for e in result["roster"]], ["main"])

    def test_cartographer_stale_many_modules_or_many_reads_is_a_subagent(self):
        cases = ({"map_age_days": None}, {"map_age_days": 8}, {"modules": 2}, {"read_files": 9})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                task = dict({"task_kind": "map", "modules": 1, "map_age_days": 1}, **overrides)
                result = _route(**task)
                self.assertEqual({e["delegate"] for e in result["roster"]}, {"subagent"})
        stale = _by_role(_route(map_age_days=30, changed_lines=10), "generic-cartographer")[0]
        self.assertEqual((stale["delegate"], stale["optional"]), ("subagent", "stale-map-cartographer"))
        self.assertIn("stale", stale["delegation_reason"])

    def test_parallel_read_only_entries_run_in_the_background(self):
        result = _route(task_kind="review", prior={"findings": 2})
        flags = [(e["role"], e["step"], e["background"]) for e in result["roster"]]
        self.assertEqual(flags, [("generic-challenger", 1, True), ("generic-verifier", 1, True),
                                 ("generic-judge", 2, False)])
        mapped = _route(task_kind="map", modules=4)
        self.assertEqual([e["background"] for e in mapped["roster"]], [True] * 4)

    def test_writer_entries_are_foreground(self):
        for overrides in ({"changed_lines": 10}, {"changed_lines": 900}, {"prior": {"truncated": True,
                                                                                   "role": "generic-proposer"},
                                                                         "modules": 3, "changed_lines": 900}):
            with self.subTest(overrides=overrides):
                writers = [e for e in _route(**overrides)["roster"] if e["role"] in router.WRITER_ROLES]
                self.assertTrue(writers)
                self.assertEqual({e["background"] for e in writers}, {False})

    def test_the_step_before_a_verifier_or_an_owner_gate_is_foreground(self):
        high = _route(task_kind="review", tier="high", lane="opus")
        adversaries = [e for e in high["roster"] if e["step"] == 1]
        self.assertEqual(len(adversaries), 2)
        self.assertEqual({e["background"] for e in adversaries}, {False})
        self.assertIn("verifier", adversaries[0]["delegation_reason"])
        # zero findings: the judge is skipped, step 1 is the last running step
        free = _route(task_kind="review", prior={"findings": 0})
        gated = _route(task_kind="review", prior={"findings": 0}, owner_gate=True)
        self.assertEqual([e["background"] for e in free["roster"] if e["step"] == 1], [True, True])
        self.assertEqual([e["background"] for e in gated["roster"] if e["step"] == 1], [False, False])
        self.assertIn("owner gate", gated["roster"][0]["delegation_reason"])
        mapped = _route(task_kind="map", modules=4, owner_gate=True)
        self.assertEqual([(e["step"], e["background"]) for e in mapped["roster"]],
                         [(1, True), (1, True), (1, True), (2, False)])

    def test_background_is_one_deterministic_function(self):
        roster = [{"role": "generic-challenger", "order": "parallel", "step": 1, "launch": "run"},
                  {"role": "generic-verifier", "order": "parallel", "step": 1, "launch": "run"},
                  {"role": "generic-verifier", "order": "sequential", "step": 2, "launch": "run"}]
        self.assertEqual(router.background(roster[0], "subagent", roster, False)[0], False)
        self.assertEqual(router.background(roster[0], "main", roster[:2], False)[0], False)
        self.assertEqual(router.background(roster[0], "subagent", roster[:2], False)[0], True)
        self.assertEqual(router.background(roster[0], "subagent", roster[:2], True)[0], False)
        self.assertEqual(router.background(roster[2], "subagent", roster, False)[0], False)

    def test_config_thresholds_are_respected(self):
        tight = _delegation_catalog(writer_main_max_changed_lines=40)
        self.assertEqual(_by_role(_route(catalog=tight, changed_lines=50), "generic-proposer")[0]["delegate"],
                         "subagent")
        wide = _delegation_catalog(writer_main_max_modules=2)
        self.assertEqual(_by_role(_route(catalog=wide, modules=2), "generic-proposer")[0]["delegate"], "main")
        reads = _delegation_catalog(explorer_main_max_read_files=20)
        mapped = _route(catalog=reads, task_kind="map", modules=1, read_files=9)
        self.assertEqual(mapped["roster"][0]["delegate"], "main")

    def test_kit_catalog_declares_the_delegation_thresholds(self):
        block = CATALOG["router"]["delegation"]
        self.assertIn("_comment", block)
        self.assertEqual({k: v for k, v in block.items() if not k.startswith("_")}, router.DELEGATION_DEFAULTS)

    def test_missing_delegation_block_uses_the_defaults(self):
        cat = copy.deepcopy(CATALOG)
        del cat["router"]["delegation"]
        self.assertEqual(router.dumps(_route(catalog=cat)), router.dumps(_route()))
        partial = copy.deepcopy(CATALOG)
        partial["router"]["delegation"] = {"writer_main_max_modules": 1}
        self.assertEqual(router.dumps(_route(catalog=partial)), router.dumps(_route()))

    def test_malformed_delegation_thresholds_are_guard_catalog(self):
        cases = [["x"], "8", {"writer_main_max_lines": 3}]
        for key in router.DELEGATION_DEFAULTS:
            cases += [{key: v} for v in (0, -1, "8", True, 1.5, None)]
        for block in cases:
            with self.subTest(block=block):
                cat = copy.deepcopy(CATALOG)
                cat["router"]["delegation"] = block
                _guarded(self, _route(catalog=cat), "guard:catalog", "delegation")

    def test_read_files_is_a_non_negative_int(self):
        for value in (-1, "3", True, 1.5):
            with self.subTest(value=value):
                _guarded(self, _route(read_files=value), "guard:input", "read_files")
        for value in (0, 7, None):
            self.assertEqual(_route(read_files=value)["status"], "ok")

    def test_log_line_counts_delegation_over_running_entries(self):
        review = json.loads(router.log_line(_route(task_kind="review", prior={"findings": 2})))
        self.assertEqual(review["delegation"], {"subagent": 3, "main": 0, "background": 2})
        small = json.loads(router.log_line(_route(changed_lines=10)))
        self.assertEqual(small["delegation"], {"subagent": 1, "main": 1, "background": 0})
        skipped = json.loads(router.log_line(_route(task_kind="review", prior={"findings": 0})))
        self.assertEqual(skipped["delegation"], {"subagent": 2, "main": 0, "background": 2})
        guard = json.loads(router.log_line(_route(task_kind="dance")))
        self.assertEqual(guard["delegation"], {"subagent": 0, "main": 0, "background": 0})

    def test_delegation_is_deterministic(self):
        for overrides in ({}, {"task_kind": "review", "tier": "high", "lane": "opus"}, {"task_kind": "map", "modules": 5}):
            with self.subTest(overrides=overrides):
                task = _task(**overrides)
                reordered = dict(reversed(list(task.items())))
                one = router.route(task, CATALOG, AS_OF)
                self.assertEqual(router.dumps(one), router.dumps(router.route(reordered, copy.deepcopy(CATALOG), AS_OF)))
                self.assertEqual(router.log_line(one), router.log_line(router.route(task, CATALOG, AS_OF)))


if __name__ == "__main__":
    unittest.main()
