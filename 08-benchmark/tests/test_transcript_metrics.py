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


# A message typed while the agent works is a queued_command attachment with a human origin
# (verified 2026-10-17); subagent hand-backs share the type with other origins.
QUEUED_RECORDS = [
    {"type": "attachment", "sessionId": SID, "timestamp": "2026-09-20T10:00:20.000Z",
     "attachment": {"type": "queued_command", "prompt": "also check the logs", "origin": {"kind": "human"}}},
    {"type": "attachment", "sessionId": SID, "timestamp": "2026-09-20T10:00:21.000Z",
     "attachment": {"type": "queued_command", "prompt": "<task-notification> done",
                    "commandMode": "task-notification", "origin": {"kind": "task-notification"}}},
    {"type": "attachment", "sessionId": SID, "timestamp": "2026-09-20T10:00:22.000Z",
     "attachment": {"type": "queued_command", "prompt": "subagent result", "origin": {"kind": "peer"}}},
]


def build_fixture(root: pathlib.Path, extra=()) -> pathlib.Path:
    """The shared synthetic session; `extra` records are appended before the cost-state record."""
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
    recs += list(extra)
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

    def test_previous_output_is_unchanged(self):
        # analyze_session on this fixture, captured before the queued, model x effort and
        # context_metrics keys landed; each of them is additive and has its own tests
        actual = json.loads(json.dumps(self.session))
        for key in ("queued_count", "queued_chars_total"):
            actual["human_prompts"].pop(key, None)
        actual.pop("model_effort", None)
        actual.pop("context_metrics", None)
        self.assertEqual(actual, PREVIOUS_OUTPUT)

    def test_model_effort_mix_per_request(self):
        self.assertEqual(self.session["model_effort"],
                         {"claude-haiku-5-5": {"unset": 1}, "claude-opus-5-5": {"high": 1, "unset": 3}})

    def test_benchmark_skill_is_not_a_kit_skill(self):
        # the benchmark skill runs in vanilla sessions too; using it must not flag the kit
        self.assertNotIn("harness-benchmark", tm.KIT_SKILLS)


class QueuedHumanMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        proj = build_fixture(pathlib.Path(self.tmp.name), extra=QUEUED_RECORDS)
        self.session = tm.analyze_session(proj / f"{SID}.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_queued_message_counts_apart(self):
        hp = self.session["human_prompts"]
        self.assertEqual(hp["queued_count"], 1)
        self.assertEqual(hp["queued_chars_total"], len("also check the logs"))
        # real turns stay anchored on the typed prompts
        self.assertEqual(hp["count"], 2)
        self.assertEqual(self.session["latency_s"]["turn_wall_clock"], [300.0])

    def test_no_queued_text_in_output(self):
        dump = json.dumps(self.session)
        self.assertNotIn("check the logs", dump)
        self.assertNotIn("subagent result", dump)

    def test_without_queued_records_the_counts_are_zero(self):
        with tempfile.TemporaryDirectory() as d:
            proj = build_fixture(pathlib.Path(d))
            hp = tm.analyze_session(proj / f"{SID}.jsonl")["human_prompts"]
        self.assertEqual((hp["queued_count"], hp["queued_chars_total"]), (0, 0))


class TranscriptDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(os.path.realpath(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _expected(path):
        return "".join(c if c.isascii() and c.isalnum() else "-" for c in os.path.realpath(path))

    def test_every_non_alphanumeric_becomes_a_dash(self):
        repo = self.base / "my_repo.v2" / ".claude" / "x"
        repo.mkdir(parents=True)
        got = tm.transcript_dir(repo, root=self.base / "projects")
        self.assertEqual(got, self.base / "projects" / self._expected(repo))
        self.assertTrue(got.name.endswith("-my-repo-v2--claude-x"))

    def test_symlinked_repo_resolves_to_its_real_path(self):
        real = self.base / "real_repo"
        real.mkdir()
        link = self.base / "link"
        link.symlink_to(real, target_is_directory=True)
        self.assertEqual(tm.transcript_dir(link, root=self.base).name, self._expected(real))
        self.assertTrue(tm.transcript_dir(link, root=self.base).name.endswith("-real-repo"))

    def test_root_defaults_to_env_then_home(self):
        repo = self.base / "r"
        repo.mkdir()
        old = os.environ.get("CLAUDE_PROJECTS_DIR")
        try:
            os.environ["CLAUDE_PROJECTS_DIR"] = str(self.base / "env-root")
            self.assertEqual(tm.transcript_dir(repo).parent, self.base / "env-root")
            del os.environ["CLAUDE_PROJECTS_DIR"]
            self.assertEqual(tm.transcript_dir(repo).parent,
                             pathlib.Path("~/.claude/projects").expanduser())
        finally:
            if old is None:
                os.environ.pop("CLAUDE_PROJECTS_DIR", None)
            else:
                os.environ["CLAUDE_PROJECTS_DIR"] = old


PREVIOUS_OUTPUT = {
    "agent_prompt_chars": [7], "agent_tool_calls_by_type": {"generic-judge": 1}, "api_errors": 0,
    "branches": ["main"], "cache_hit_ratio": 0.895219,
    "compactions": [{"post": 20000, "pre": 150000, "trigger": "auto"}], "cost_usd": 0.42,
    "duration_s": 302.0, "effort_levels": {"high": 1},
    "engram": {"other_calls": 0, "recall_calls": 1, "save_calls": 0},
    "final_replies": {"chars": [120, 8], "chars_total": 128, "count": 2},
    "first_ts": "2026-09-20T10:00:00.000Z",
    "hooks": {"by_event": {"PostToolUse:hook_success": 1, "SessionStart:hook_success": 1}, "metodo_runs": 1},
    "human_prompts": {"chars": [24, 6], "chars_total": 30, "count": 2},
    "kit": {"first_marker_ts": "2026-09-20T10:00:00.000Z",
            "marker_ts": {"hook:metodo": "2026-09-20T10:00:00.000Z",
                          "subagent:generic-judge": "2026-09-20T10:00:06.000Z"},
            "markers": ["hook:metodo", "subagent:generic-judge"], "uses_kit": True,
            "weak_markers": ["skill:respuesta-humana"]},
    "last_ts": "2026-09-20T10:05:02.000Z",
    "latency_s": {"first_response": [3.0, 2.0], "turn_wall_clock": [300.0]},
    "mcp_servers": {"engram": 1}, "model_switches": 1,
    "models": {"claude-haiku-5-5": 1, "claude-opus-5-5": 4}, "output_style": "Gentleman",
    "peak_context_tokens": 2105, "permission_modes": {"acceptEdits": 2}, "project": "proj",
    "project_dir": "-home-x-proj", "requests": 5, "session_id": SID,
    "skills": {"respuesta-humana": 1}, "slash_commands": 0,
    "subagents": {"by_model": {"claude-sonnet-5-5": 1}, "by_type": {"generic-judge": 1}, "count": 1,
                  "peak_context_tokens": 100, "requests": 1},
    "tokens": {"main": {"cache_read": 8800, "cache_write": 1000, "input": 30, "output": 160},
               "subagents": {"cache_read": 0, "cache_write": 0, "input": 100, "output": 200}},
    "tool_calls": {"Agent": 1, "Skill": 1, "mcp__engram__mem_search": 1}, "turn_durations_ms": [],
    "versions": ["2.1.209"],
}


if __name__ == "__main__":
    unittest.main()
