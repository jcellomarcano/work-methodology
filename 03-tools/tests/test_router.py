"""router.route() is pure: one test per guard, per decision row (P1-P6,
B0-B7), per post-pass, the escalation ladder, the Fable approval rule (L6)
and the routing log. Negative controls: byte-identical output for the same
input, no Fable launch without approval, offline never yields a remote
provider, no step above the fan-out cap."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

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

    def test_b7_kind_without_a_base_row_fails_closed(self):
        result = _route(task_kind="verify", tier="medium")
        self.assertEqual((result["rule"], result["status"]), ("B7", "error"))


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


class FableTests(unittest.TestCase):
    def _grid(self):
        for kind in router.TASK_KINDS:
            for tier in router.RDD_TIERS:
                lane = "opus" if tier == "high" else "sonnet"
                yield _task(task_kind=kind, tier=tier, lane=lane)
                yield _task(task_kind=kind, tier=tier, lane=lane, critical_hit=True, map_age_days=None)

    def test_no_default_row_proposes_fable(self):
        for task in self._grid():
            result = router.route(task, CATALOG, AS_OF)
            with self.subTest(kind=task["task_kind"], tier=task["tier"]):
                self.assertNotIn(FABLE, [e["model"] for e in result["roster"]])

    def test_unapproved_fable_never_runs_and_opus_xhigh_runs_instead(self):
        result = _route(owner_named=True)
        self.assertEqual(result["rule"], "escalate-fable")
        fable = [e for e in result["roster"] if e["model"] == FABLE]
        self.assertEqual([(e["launch"], e["requires_approval"]) for e in fable], [("skip", True)])
        self.assertIn(("large", "claude-opus-5-5", "xhigh"), [r[1:] for r in _roles(result)])

    def test_approved_fable_runs(self):
        result = _route(owner_named=True, approvals=["escalate-fable"])
        fable = [e for e in _running(result) if e["model"] == FABLE]
        self.assertEqual(len(fable), 1)
        self.assertTrue(fable[0]["requires_approval"])
        self.assertNotIn("claude-opus-5-5", [e["model"] for e in _running(result)])

    def test_fable_triggers_for_highest_reasoning_verification(self):
        cases = [
            dict(task_kind="review", tier="high", critical_hit=True, prior={"p0_from_lower_tier": "medium"}),
            dict(task_kind="review", tier="high", prior={"disagreement": True, "judge_tier": "large"}),
            dict(task_kind="review", tier="high", prior={"escalated_count": 2}),
        ]
        for case in cases:
            with self.subTest(case=case):
                result = _route(**case)
                self.assertEqual(result["rule"], "escalate-fable")
                self.assertEqual([e for e in _running(result) if e["model"] == FABLE], [])
        lower = _route(task_kind="review", tier="medium", prior={"escalated_count": 2})
        self.assertNotEqual(lower["rule"], "escalate-fable")


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
            self.assertEqual(set(line), {"as_of", "catalog_version", "inputs_hash", "rule", "status", "roster"})
            self.assertEqual((line["rule"], line["status"], line["as_of"]), ("B6", "ok", AS_OF))
            self.assertEqual(json.loads(proc.stdout)["inputs_hash"], line["inputs_hash"])

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


if __name__ == "__main__":
    unittest.main()
