"""lib/activation.py (T8, WU14; odd/research/context/activation.md section 3):
the first-match profile rows P0-P5, the 14-element x 5-profile matrix from
config/activation.json, the absolute set that stays BLOCK in every column,
the modifiers, the session floor (tier only rises within a session),
determinism and the CLI."""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import activation as act

TOOLS_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = TOOLS_ROOT / "config" / "activation.json"
SCRIPT = TOOLS_ROOT / "lib" / "activation.py"

PROFILES = ("bare", "light", "scripts", "standard", "full")
# activation.md section 3, encoded as OFF/LOG/WARN/BLOCK (ON that runs silently = LOG, ON visible = WARN).
EXPECTED_MATRIX = {
    "push_gate": ("OFF", "OFF", "WARN", "WARN", "BLOCK"),
    "history_rewrite": ("OFF", "LOG", "LOG", "LOG", "LOG"),
    "subagent_scope": ("OFF", "OFF", "LOG", "LOG", "BLOCK"),
    "subagent_output": ("OFF", "OFF", "BLOCK", "BLOCK", "BLOCK"),
    "touched_paths": ("OFF", "LOG", "LOG", "LOG", "LOG"),
    "session_start_status": ("OFF", "WARN", "WARN", "WARN", "WARN"),
    "reply_lint": ("OFF", "OFF", "OFF", "OFF", "OFF"),
    "human_reply_skill": ("OFF", "OFF", "OFF", "OFF", "WARN"),
    "roles": ("OFF", "OFF", "WARN", "WARN", "WARN"),
    "comment_gate": ("OFF", "OFF", "WARN", "WARN", "WARN"),
    "docs_caps": ("OFF", "BLOCK", "BLOCK", "BLOCK", "BLOCK"),
    "test_sectors": ("OFF", "OFF", "BLOCK", "BLOCK", "BLOCK"),
    "kit_status_drift": ("BLOCK", "BLOCK", "BLOCK", "BLOCK", "BLOCK"),
    "router": ("WARN", "WARN", "WARN", "WARN", "WARN"),
}
ABSOLUTE = ("subagent_build_files", "force_push", "subagent_delivery", "budget_deny", "main_build_file_ask")


def shipped() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class ProfileRows(unittest.TestCase):
    def check(self, inputs, profile, rule):
        result = act.profile(inputs)
        self.assertEqual((result["profile"], result["rule"]), (profile, rule), result)
        self.assertTrue(result["reasons"], result)
        return result

    def test_p0_rdd_off_is_bare_whatever_the_tier(self):
        self.check({"rdd_on": False, "tier": "high", "task_kind": "release"}, "bare", "P0")

    def test_p1_high_critical_or_release_is_full(self):
        self.check({"rdd_on": True, "tier": "high"}, "full", "P1")
        self.check({"rdd_on": True, "tier": "low", "critical": True}, "full", "P1")
        self.check({"rdd_on": True, "tier": "exempt", "task_kind": "release"}, "full", "P1")

    def test_p2_medium_is_standard(self):
        self.check({"rdd_on": True, "tier": "medium"}, "standard", "P2")

    def test_p3_low_is_scripts(self):
        self.check({"rdd_on": True, "tier": "low"}, "scripts", "P3")

    def test_p4_exempt_is_light(self):
        self.check({"rdd_on": True, "tier": "exempt"}, "light", "P4")

    def test_p5_unknown_tier_is_standard(self):
        self.check({"rdd_on": True, "tier": None}, "standard", "P5")
        self.check({"rdd_on": True}, "standard", "P5")
        self.check({"rdd_on": True, "tier": "unknown"}, "standard", "P5")

    def test_m4_explore_is_light_until_the_first_edit(self):
        result = self.check({"rdd_on": True, "tier": "medium", "phase": "explore"}, "light", "P4")
        self.assertTrue(any("M4" in r for r in result["reasons"]), result)
        # P1 still wins: a release is full even while exploring.
        self.check({"rdd_on": True, "tier": "low", "phase": "explore", "task_kind": "release"}, "full", "P1")

    def test_rdd_on_defaults_to_true(self):
        self.check({"tier": "low"}, "scripts", "P3")

    def test_invalid_inputs_are_errors(self):
        for bad in ({"tier": "huge"}, {"runtime": "vim"}, {"caller": "boss"}, {"phase": "nap"}, {"task_kind": "dance"}):
            with self.assertRaises(ValueError, msg=bad):
                act.profile(dict(bad, rdd_on=True))

    def test_determinism(self):
        inputs = {"rdd_on": True, "tier": "medium", "task_kind": "code", "runtime": "pi", "caller": "subagent",
                  "offline": True, "phase": "deliver"}
        reordered = dict(reversed(list(inputs.items())))
        a = json.dumps(act.profile(inputs), sort_keys=True)
        b = json.dumps(act.profile(copy.deepcopy(inputs)), sort_keys=True)
        c = json.dumps(act.profile(reordered), sort_keys=True)
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_profile_is_pure(self):
        inputs = {"rdd_on": True, "tier": "low"}
        before = copy.deepcopy(inputs)
        act.profile(inputs)
        self.assertEqual(inputs, before)


class MatrixLookups(unittest.TestCase):
    def test_shipped_config_has_a_comment_and_validates(self):
        data = shipped()
        self.assertIn("_comment", data)
        config = act.validate_config(data)
        self.assertEqual(set(config["matrix"]), set(EXPECTED_MATRIX) | set(ABSOLUTE))

    def test_fourteen_elements_match_activation_md(self):
        self.assertEqual(len(EXPECTED_MATRIX), 14)
        self.assertEqual(tuple(act.ELEMENTS), tuple(EXPECTED_MATRIX))
        for element, row in EXPECTED_MATRIX.items():
            for profile, mode in zip(PROFILES, row):
                self.assertEqual(act.element_mode(profile, element), mode, (element, profile))

    def test_spot_checks(self):
        self.assertEqual(act.element_mode("full", "push_gate"), "BLOCK")
        self.assertEqual(act.element_mode("light", "push_gate"), "OFF")
        self.assertEqual(act.element_mode("scripts", "subagent_scope"), "LOG")
        self.assertEqual(act.element_mode("standard", "subagent_output"), "BLOCK")
        self.assertEqual(act.element_mode("bare", "docs_caps"), "OFF")

    def test_unknown_profile_or_element_is_an_error(self):
        with self.assertRaises(ValueError):
            act.element_mode("huge", "push_gate")
        with self.assertRaises(ValueError):
            act.element_mode("full", "teleport")

    def test_absolute_set_is_block_in_every_profile_whatever_the_modifiers(self):
        modifiers = {"caller": "subagent", "runtime": "pi", "offline": True, "gradle": False, "kit_repo": False,
                     "verdicts": {e: "demote" for e in ABSOLUTE}}
        self.assertEqual(tuple(act.ABSOLUTE), ABSOLUTE)
        for element in ABSOLUTE:
            for profile in PROFILES:
                self.assertEqual(act.element_mode(profile, element), "BLOCK", (element, profile))
                self.assertEqual(act.element_mode(profile, element, modifiers), "BLOCK", (element, profile))

    def test_roles_cap_per_profile(self):
        self.assertEqual(act.roles_cap("bare"), [])
        self.assertEqual(act.roles_cap("light"), [])
        self.assertIn("generic-proposer", act.roles_cap("scripts"))
        self.assertNotIn("generic-challenger", act.roles_cap("scripts"))
        self.assertIn("generic-challenger", act.roles_cap("standard"))
        self.assertIn("generic-judge", act.roles_cap("full"))
        for lower, higher in zip(PROFILES, PROFILES[1:]):
            self.assertLessEqual(set(act.roles_cap(lower)), set(act.roles_cap(higher)), (lower, higher))


class Modifiers(unittest.TestCase):
    def test_m1_subagent_skips_main_only_elements(self):
        for element in ("push_gate", "session_start_status", "reply_lint", "human_reply_skill"):
            self.assertEqual(act.element_mode("full", element, {"caller": "subagent"}), "OFF", element)
        # subagent-only elements keep the parent's profile
        self.assertEqual(act.element_mode("full", "subagent_scope", {"caller": "subagent"}), "BLOCK")
        self.assertEqual(act.element_mode("scripts", "subagent_output", {"caller": "subagent"}), "BLOCK")

    def test_m2_pi_turns_subagent_output_block_into_log(self):
        self.assertEqual(act.element_mode("standard", "subagent_output", {"runtime": "pi"}), "LOG")
        self.assertEqual(act.element_mode("standard", "subagent_output", {"runtime": "claude"}), "BLOCK")
        self.assertEqual(act.element_mode("full", "subagent_scope", {"runtime": "pi"}), "BLOCK")

    def test_m3_offline_changes_no_matrix_element(self):
        for element in EXPECTED_MATRIX:
            for profile in PROFILES:
                self.assertEqual(act.element_mode(profile, element, {"offline": True}),
                                 act.element_mode(profile, element), (element, profile))

    def test_m5_no_gradle_turns_sectors_off(self):
        self.assertEqual(act.element_mode("full", "test_sectors", {"gradle": False}), "OFF")
        self.assertEqual(act.element_mode("full", "test_sectors", {"gradle": True}), "BLOCK")

    def test_kit_status_drift_only_in_the_kit_repo(self):
        self.assertEqual(act.element_mode("bare", "kit_status_drift", {"kit_repo": False}), "OFF")
        self.assertEqual(act.element_mode("bare", "kit_status_drift", {"kit_repo": True}), "BLOCK")

    def test_m6_verdicts_demote_and_promote(self):
        self.assertEqual(act.element_mode("standard", "subagent_scope", {"verdicts": {"subagent_scope": "promote"}}), "BLOCK")
        self.assertEqual(act.element_mode("standard", "push_gate", {"verdicts": {"push_gate": "demote"}}), "OFF")
        with self.assertRaises(ValueError):
            act.element_mode("standard", "push_gate", {"verdicts": {"push_gate": "keep-warn"}})

    def test_unknown_modifier_is_an_error(self):
        with self.assertRaises(ValueError):
            act.element_mode("full", "push_gate", {"moon_phase": "full"})


class ConfigValidation(unittest.TestCase):
    def assert_refused(self, data, needle):
        with self.assertRaises(act.ActivationConfigError) as ctx:
            act.validate_config(data)
        self.assertIn(needle, str(ctx.exception))

    def test_unknown_element_profile_or_mode_is_refused(self):
        data = shipped()
        data["matrix"]["teleport"] = dict.fromkeys(PROFILES, "OFF")
        self.assert_refused(data, "unknown element")
        data = shipped()
        data["matrix"]["push_gate"]["huge"] = "OFF"
        self.assert_refused(data, "unknown profile")
        data = shipped()
        data["matrix"]["push_gate"]["full"] = "ASK"
        self.assert_refused(data, "unknown mode")

    def test_missing_element_or_profile_is_refused(self):
        data = shipped()
        del data["matrix"]["router"]
        self.assert_refused(data, "missing element")
        data = shipped()
        del data["matrix"]["router"]["bare"]
        self.assert_refused(data, "missing profile")

    def test_config_that_lowers_the_absolute_set_is_refused(self):
        for profile in PROFILES:
            data = shipped()
            data["matrix"]["force_push"][profile] = "WARN"
            self.assert_refused(data, "absolute")
        data = shipped()
        data["absolute"] = [e for e in data["absolute"] if e != "budget_deny"]
        self.assert_refused(data, "absolute")
        data = shipped()
        del data["matrix"]["subagent_delivery"]
        self.assert_refused(data, "subagent_delivery")

    def test_thresholds_are_required_numbers(self):
        data = shipped()
        data["thresholds"]["min_fires"] = "twenty"
        self.assert_refused(data, "thresholds")
        data = shipped()
        del data["thresholds"]["precision_min"]
        self.assert_refused(data, "thresholds")

    def test_load_config_reads_a_file_and_refuses_a_bad_one(self):
        tmp = Path(tempfile.mkdtemp(prefix="act-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        good = tmp / "good.json"
        good.write_text(json.dumps(shipped()), encoding="utf-8")
        self.assertEqual(act.load_config(good)["matrix"]["push_gate"]["full"], "BLOCK")
        bad = shipped()
        bad["matrix"]["budget_deny"]["bare"] = "OFF"
        (tmp / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(act.ActivationConfigError):
            act.load_config(tmp / "bad.json")
        with self.assertRaises(act.ActivationConfigError):
            act.load_config(tmp / "missing.json")

    def test_element_mode_uses_a_given_config(self):
        data = shipped()
        data["matrix"]["subagent_scope"]["standard"] = "WARN"
        config = act.validate_config(data)
        self.assertEqual(act.element_mode("standard", "subagent_scope", config=config), "WARN")
        self.assertEqual(act.element_mode("standard", "subagent_scope"), "LOG")


class SessionFloor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="act-session-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sdir = self.tmp / "s1"

    def test_tier_only_rises_within_a_session(self):
        seq = [("medium", "standard"), ("low", "standard"), ("exempt", "standard"), ("high", "full"),
               ("medium", "full"), (None, "full")]
        for tier, expected in seq:
            result = act.session_profile({"rdd_on": True, "tier": tier}, self.sdir)
            self.assertEqual(result["profile"], expected, (tier, result))
        stored = json.loads((self.sdir / act.SESSION_FILE).read_text(encoding="utf-8"))
        self.assertEqual((stored["profile"], stored["tier"]), ("full", "high"))

    def test_floor_reason_is_recorded(self):
        act.session_profile({"rdd_on": True, "tier": "high"}, self.sdir)
        result = act.session_profile({"rdd_on": True, "tier": "low"}, self.sdir)
        self.assertEqual(result["profile"], "full")
        self.assertEqual(result["rule"], "P3")
        self.assertTrue(any("session floor" in r for r in result["reasons"]), result)

    def test_another_session_starts_fresh(self):
        act.session_profile({"rdd_on": True, "tier": "high"}, self.sdir)
        other = act.session_profile({"rdd_on": True, "tier": "low"}, self.tmp / "s2")
        self.assertEqual(other["profile"], "scripts")

    def test_pure_profile_honors_a_floor(self):
        self.assertEqual(act.profile({"rdd_on": True, "tier": "low"}, floor="standard")["profile"], "standard")
        self.assertEqual(act.profile({"rdd_on": True, "tier": "high"}, floor="standard")["profile"], "full")

    def test_corrupt_floor_file_is_ignored(self):
        self.sdir.mkdir(parents=True)
        (self.sdir / act.SESSION_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(act.session_profile({"rdd_on": True, "tier": "low"}, self.sdir)["profile"], "scripts")

    def test_session_floor_reads_the_stored_profile(self):
        self.assertIsNone(act.session_floor(self.sdir))
        act.session_profile({"rdd_on": True, "tier": "medium"}, self.sdir)
        self.assertEqual(act.session_floor(self.sdir), "standard")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="act-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, *args):
        env = dict(os.environ, METODO_HOOKS_DIR=str(self.tmp))
        return subprocess.run(["python3", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)

    def test_prints_profile_and_element_modes(self):
        proc = self.run_cli("--tier", "medium")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual((out["profile"], out["rule"]), ("standard", "P2"))
        self.assertEqual(out["elements"]["push_gate"], "WARN")
        self.assertEqual(out["elements"]["force_push"], "BLOCK")

    def test_flags_feed_the_rows_and_modifiers(self):
        out = json.loads(self.run_cli("--tier", "low", "--task-kind", "release").stdout)
        self.assertEqual(out["profile"], "full")
        out = json.loads(self.run_cli("--tier", "high", "--caller", "subagent", "--runtime", "pi", "--offline").stdout)
        self.assertEqual(out["elements"]["push_gate"], "OFF")
        self.assertEqual(out["elements"]["subagent_output"], "LOG")

    def test_session_floor_through_the_cli(self):
        self.run_cli("--tier", "high", "--session", "s9")
        out = json.loads(self.run_cli("--tier", "low", "--session", "s9").stdout)
        self.assertEqual(out["profile"], "full")
        self.assertTrue((self.tmp / "s9" / act.SESSION_FILE).is_file())

    def test_same_input_same_bytes(self):
        a = self.run_cli("--tier", "low", "--runtime", "claude").stdout
        b = self.run_cli("--tier", "low", "--runtime", "claude").stdout
        self.assertEqual(a, b)

    def test_bad_tier_is_a_usage_error(self):
        self.assertEqual(self.run_cli("--tier", "huge").returncode, 2)


if __name__ == "__main__":
    unittest.main()
