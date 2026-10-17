"""Tests for transcript_metrics: synthetic Claude Code transcripts, no real data."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import transcript_metrics as tm  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"
COMMON = {"sessionId": SID, "cwd": "/home/x/proj", "version": "2.1.209",
          "gitBranch": "main", "isSidechain": False, "userType": "external"}


def _rec(**kw):
    d = dict(COMMON)
    d.update(kw)
    return d


def _assistant(ts, msg_id, blocks, usage, model="claude-opus-5-5", extra=None):
    out = []
    for b in blocks:
        r = _rec(type="assistant", timestamp=ts, requestId="req_" + msg_id,
                 message={"id": msg_id, "model": model, "role": "assistant",
                          "content": [b], "usage": usage})
        if extra:
            r.update(extra)
        out.append(r)
    return out


def _human(ts, text, mode="acceptEdits"):
    return _rec(type="user", timestamp=ts, permissionMode=mode,
                origin={"kind": "human"}, message={"role": "user", "content": text})


def _tool_result(ts, tool_use_id, content="ok", tool_use_result=None):
    r = _rec(type="user", timestamp=ts,
             message={"role": "user", "content": [{"type": "tool_result",
                                                   "tool_use_id": tool_use_id,
                                                   "content": content}]})
    if tool_use_result is not None:
        r["toolUseResult"] = tool_use_result
    return r


USAGE1 = {"input_tokens": 10, "cache_creation_input_tokens": 1000,
          "cache_read_input_tokens": 500, "output_tokens": 40}
USAGE2 = {"input_tokens": 5, "cache_creation_input_tokens": 0,
          "cache_read_input_tokens": 2000, "output_tokens": 60}
USAGE3 = {"input_tokens": 5, "cache_creation_input_tokens": 0,
          "cache_read_input_tokens": 2100, "output_tokens": 20}


def build_fixture(root: pathlib.Path) -> pathlib.Path:
    proj = root / "-home-x-proj"
    proj.mkdir(parents=True)
    recs = []
    recs.append({"type": "attachment", "attachment": {"type": "output_style", "style": "Gentleman"},
                 "sessionId": SID, "timestamp": "2026-09-20T10:00:00.000Z"})
    # hook attachments carry content as a string or as a list of blocks (seen in real data)
    recs.append({"type": "attachment", "sessionId": SID, "timestamp": "2026-09-20T10:00:00.000Z",
                 "attachment": {"type": "hook_success", "hookEvent": "SessionStart", "exitCode": 0,
                                "command": ": metodo-hook; H=x", "content": [{"type": "text", "text": "[metodo] ok"}]}})
    # same command, but the hook exited silently (METODO_TOOLS pointed nowhere): not a kit run
    recs.append({"type": "attachment", "sessionId": SID, "timestamp": "2026-09-20T10:00:00.500Z",
                 "attachment": {"type": "hook_success", "hookEvent": "PostToolUse", "exitCode": 0,
                                "command": ": metodo-hook; H=x", "content": ""}})
    recs.append(_human("2026-09-20T10:00:00.000Z", "fix the login bug please"))
    # one API message split into 2 records (text + tool_use) sharing usage
    recs += _assistant("2026-09-20T10:00:03.000Z", "msg_1",
                       [{"type": "text", "text": "Looking."},
                        {"type": "tool_use", "id": "toolu_1", "name": "mcp__engram__mem_search",
                         "input": {"query": "login"}}], USAGE1)
    recs.append(_tool_result("2026-09-20T10:00:04.000Z", "toolu_1"))
    recs += _assistant("2026-09-20T10:00:06.000Z", "msg_2",
                       [{"type": "tool_use", "id": "toolu_2", "name": "Agent",
                         "input": {"description": "map", "prompt": "explore", "subagent_type": "generic-judge"}}],
                       USAGE2, extra={"effort": "high"})
    recs.append(_tool_result("2026-09-20T10:00:30.000Z", "toolu_2",
                             tool_use_result={"status": "completed", "agentId": "agentA",
                                              "agentType": "generic-judge", "totalTokens": 300}))
    recs.append({"type": "system", "subtype": "compact_boundary", "sessionId": SID,
                 "timestamp": "2026-09-20T10:00:31.000Z",
                 "compactMetadata": {"trigger": "auto", "preTokens": 150000, "postTokens": 20000}})
    recs += _assistant("2026-09-20T10:00:35.000Z", "msg_2b",
                       [{"type": "tool_use", "id": "toolu_2b", "name": "Skill", "input": {"skill": "respuesta-humana"}}],
                       USAGE3)
    recs.append(_tool_result("2026-09-20T10:00:36.000Z", "toolu_2b"))
    recs += _assistant("2026-09-20T10:00:40.000Z", "msg_3",
                       [{"type": "text", "text": "Done. " * 20}], USAGE3)
    recs.append(_human("2026-09-20T10:05:00.000Z", "thanks"))
    recs += _assistant("2026-09-20T10:05:02.000Z", "msg_4",
                       [{"type": "text", "text": "Welcome."}], USAGE3, model="claude-haiku-5-5")
    # real shape (verified 2026-10-13): totals sit at the top level of the record
    recs.append({"type": "cost-state", "sessionId": SID, "totalCostUSD": 0.42, "totalDuration": 310000})
    (proj / f"{SID}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    sub = proj / SID / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-agentA.meta.json").write_text(json.dumps(
        {"agentType": "generic-judge", "toolUseId": "toolu_2", "model": "sonnet"}))
    srecs = [dict(r, isSidechain=True, agentId="agentA") for r in _assistant(
        "2026-09-20T10:00:10.000Z", "msg_s1",
        [{"type": "tool_use", "id": "toolu_s1", "name": "Read", "input": {"file_path": "/a"}}],
        {"input_tokens": 100, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 0, "output_tokens": 200}, model="claude-sonnet-5-5")]
    (sub / "agent-agentA.jsonl").write_text("\n".join(json.dumps(r) for r in srecs) + "\n")
    return proj


class TranscriptMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.proj = build_fixture(self.root)
        self.session = tm.analyze_session(self.proj / f"{SID}.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tokens_deduped_by_message_id(self):
        t = self.session["tokens"]["main"]
        # msg_1 counted once although it is split into two records
        self.assertEqual(t["input"], 10 + 5 + 5 + 5 + 5)
        self.assertEqual(t["cache_write"], 1000)
        self.assertEqual(t["cache_read"], 500 + 2000 + 2100 + 2100 + 2100)
        self.assertEqual(t["output"], 40 + 60 + 20 + 20 + 20)
        self.assertEqual(self.session["requests"], 5)

    def test_peak_context_and_cache_ratio(self):
        self.assertEqual(self.session["peak_context_tokens"], 2105)
        total_in = 30 + 1000 + 8800
        self.assertAlmostEqual(self.session["cache_hit_ratio"], 8800 / total_in, places=6)

    def test_subagent_tokens_and_types(self):
        self.assertEqual(self.session["tokens"]["subagents"]["output"], 200)
        self.assertEqual(self.session["subagents"]["count"], 1)
        self.assertEqual(self.session["subagents"]["by_type"], {"generic-judge": 1})
        self.assertEqual(self.session["subagents"]["by_model"], {"claude-sonnet-5-5": 1})
        self.assertEqual(self.session["subagents"]["peak_context_tokens"], 100)
        self.assertEqual(self.session["agent_prompt_chars"], [len("explore")])

    def test_models_tools_skills_markers(self):
        self.assertEqual(self.session["models"], {"claude-haiku-5-5": 1, "claude-opus-5-5": 4})
        self.assertEqual(self.session["tool_calls"]["Agent"], 1)
        self.assertEqual(self.session["tool_calls"]["mcp__engram__mem_search"], 1)
        self.assertEqual(self.session["mcp_servers"], {"engram": 1})
        self.assertEqual(self.session["engram"]["recall_calls"], 1)
        self.assertEqual(self.session["engram"]["save_calls"], 0)
        self.assertTrue(self.session["kit"]["uses_kit"])
        self.assertEqual(self.session["kit"]["markers"], ["hook:metodo", "subagent:generic-judge"])
        # a kit-named skill alone is weak evidence: user-level skills share names
        self.assertEqual(self.session["kit"]["weak_markers"], ["skill:respuesta-humana"])
        self.assertEqual(self.session["kit"]["marker_ts"], {"hook:metodo": "2026-09-20T10:00:00.000Z",
                                                             "subagent:generic-judge": "2026-09-20T10:00:06.000Z"})
        self.assertEqual(self.session["kit"]["first_marker_ts"], "2026-09-20T10:00:00.000Z")
        self.assertEqual(self.session["skills"], {"respuesta-humana": 1})
        self.assertEqual(self.session["hooks"], {"by_event": {"PostToolUse:hook_success": 1, "SessionStart:hook_success": 1},
                                                 "metodo_runs": 1})
        self.assertEqual(self.session["effort_levels"], {"high": 1})

    def test_prompts_replies_latency(self):
        self.assertEqual(self.session["human_prompts"]["count"], 2)
        self.assertEqual(self.session["human_prompts"]["chars_total"], len("fix the login bug please") + len("thanks"))
        self.assertEqual(self.session["final_replies"]["count"], 2)
        self.assertEqual(self.session["final_replies"]["chars_total"], len("Done. " * 20) + len("Welcome."))
        self.assertEqual(self.session["latency_s"]["first_response"], [3.0, 2.0])
        self.assertEqual(self.session["latency_s"]["turn_wall_clock"], [300.0])
        self.assertEqual(self.session["permission_modes"], {"acceptEdits": 2})
        self.assertEqual(self.session["output_style"], "Gentleman")

    def test_compaction_cost_span(self):
        self.assertEqual(self.session["compactions"], [{"trigger": "auto", "pre": 150000, "post": 20000}])
        self.assertEqual(self.session["cost_usd"], 0.42)
        self.assertEqual(self.session["first_ts"], "2026-09-20T10:00:00.000Z")
        self.assertEqual(self.session["duration_s"], 302.0)

    def test_no_private_text_in_output(self):
        dump = json.dumps(self.session)
        self.assertNotIn("login bug", dump)
        self.assertNotIn("Welcome", dump)

    def test_cli_is_deterministic(self):
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                out = pathlib.Path(od) / "x.json"
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "transcript_metrics.py"),
                                "--root", str(self.root), "--out", str(out)],
                               check=True, capture_output=True)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        payload = json.loads(outs[0])
        self.assertEqual(payload["schema_version"], tm.SCHEMA_VERSION)
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["project"], "proj")


if __name__ == "__main__":
    unittest.main()
