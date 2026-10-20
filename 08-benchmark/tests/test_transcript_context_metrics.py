"""Tests for the context-method metrics (M100-M107) in transcript_metrics.

Synthetic transcripts only: every fixture is built here, no real data is read.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import transcript_metrics as tm  # noqa: E402

SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
COMMON = {"sessionId": SID, "cwd": "/home/x/ctx", "version": "2.1.209", "gitBranch": "main",
          "isSidechain": False, "userType": "external"}
H1 = "a" * 64            # routing decision made in the session
H2 = "b" * 64            # routing decision from another session
H3 = "c" * 64            # in the session, but the router status was not ok


def _rec(**kw):
    d = dict(COMMON)
    d.update(kw)
    return d


def _usage(inp=1, cw=0, cr=0, out=1):
    return {"input_tokens": inp, "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr, "output_tokens": out}


class Script:
    """Builds one transcript in order: each call appends records."""

    def __init__(self, sidechain=False):
        self.recs = []
        self.n = 0
        self.sidechain = sidechain

    def _ts(self):
        self.n += 1
        return f"2026-10-18T10:{self.n // 60:02d}:{self.n % 60:02d}.000Z"

    def human(self, text):
        self.recs.append(_rec(type="user", timestamp=self._ts(), origin={"kind": "human"},
                              message={"role": "user", "content": text}))

    def assistant(self, msg_id, blocks, usage=None, model="claude-opus-5-5"):
        ts = self._ts()
        for b in blocks:
            r = _rec(type="assistant", timestamp=ts, requestId="req_" + msg_id,
                     message={"id": msg_id, "model": model, "role": "assistant", "content": [b],
                              "usage": usage or _usage()})
            if self.sidechain:
                r["isSidechain"] = True
            self.recs.append(r)

    def call(self, msg_id, tool_id, name, inp, usage=None):
        self.assistant(msg_id, [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}], usage)

    def text(self, msg_id, text, usage=None):
        self.assistant(msg_id, [{"type": "text", "text": text}], usage)

    def result(self, tool_id, content):
        self.recs.append(_rec(type="user", timestamp=self._ts(),
                              message={"role": "user", "content": [
                                  {"type": "tool_result", "tool_use_id": tool_id, "content": content}]}))

    def hook(self, text, tool_id=None, event="PostToolUse"):
        att = {"type": "hook_additional_context", "hookEvent": event,
               "command": ": metodo-hook; H=x", "content": [text]}
        if tool_id:
            att["toolUseID"] = tool_id
        self.recs.append({"type": "attachment", "sessionId": SID, "timestamp": self._ts(), "attachment": att})

    def dump(self):
        return "\n".join(json.dumps(r) for r in self.recs) + "\n"


def write_session(root, main, subagents=()):
    """subagents: (agent_id, agent_type, tool_use_id, Script)."""
    proj = root / "-home-x-ctx"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / f"{SID}.jsonl").write_text(main.dump())
    if subagents:
        sub = proj / SID / "subagents"
        sub.mkdir(parents=True)
        for agent_id, agent_type, tool_use_id, script in subagents:
            meta = {"toolUseId": tool_use_id, "model": "sonnet"}
            if agent_type:
                meta["agentType"] = agent_type
            (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))
            (sub / f"agent-{agent_id}.jsonl").write_text(script.dump())
    return proj / f"{SID}.jsonl"


def write_contracts(root):
    d = root / "contracts"
    d.mkdir()
    (d / "generic-judge.contract.json").write_text(json.dumps({"agent": "generic-judge", "max_context_tokens": 1000}))
    (d / "generic-proposer.contract.json").write_text(json.dumps({"agent": "generic-proposer", "max_context_tokens": 5000}))
    (d / "broken.contract.json").write_text("{not json")
    return d


def _entry(role, launch="run", delegate="subagent"):
    return {"role": role, "tier": "medium", "model": "m", "effort": "high", "launch": launch, "step": "B3",
            "delegate": delegate, "background": False}


def write_routing_log(root):
    lines = [
        {"inputs_hash": H2, "status": "ok", "rule": "x", "roster": [_entry("generic-verifier")]},
        {"inputs_hash": H1, "status": "ok", "rule": "x", "roster": [
            _entry("generic-proposer"), _entry("generic-challenger"), _entry("generic-judge"),
            _entry("generic-mechanic", launch="skip"), _entry("generic-cartographer", delegate="main")]},
        {"inputs_hash": H3, "status": "blocked", "rule": "x", "roster": [_entry("generic-verifier")]},
    ]
    p = root / "routing.jsonl"
    p.write_text("\n".join(json.dumps(l, sort_keys=True) for l in lines) + "\nnot json\n")
    return p


def ctx(session):
    return session["context_metrics"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, main, subagents=(), contracts=None, routing=None):
        path = write_session(self.root, main, subagents)
        return tm.analyze_session(path, contracts=contracts if contracts is not None else {}, routing=routing)


class PerRolePeakVsCap(Base):
    """M100: per subagent run, the peak context vs its role contract's max_context_tokens."""

    def test_peak_against_contract_cap(self):
        main = Script()
        main.call("m1", "t_j1", "Agent", {"subagent_type": "generic-judge", "prompt": "p"})
        main.call("m2", "t_j2", "Agent", {"subagent_type": "generic-judge", "prompt": "p"})
        main.call("m3", "t_ex", "Agent", {"subagent_type": "Explore", "prompt": "p"})
        j1, j2, ex = Script(True), Script(True), Script(True)
        j1.text("s1", "a", _usage(inp=500, cr=1000))          # peak 1500 > 1000
        j2.text("s2", "a", _usage(inp=300, cw=500))           # peak 800
        ex.text("s3", "a", _usage(inp=9000))                  # no contract
        caps = tm.load_contract_caps(write_contracts(self.root))
        self.assertEqual(caps, {"generic-judge": 1000, "generic-proposer": 5000})
        m = ctx(self.analyze(main, [("a1", "generic-judge", "t_j1", j1),
                                    ("a2", None, "t_j2", j2),   # role from the Agent call's subagent_type
                                    ("a3", "Explore", "t_ex", ex)], contracts=caps))["per_role_peak"]
        self.assertEqual(m["id"], "M100")
        self.assertEqual(m["label"], "Measured")
        self.assertEqual(m["by_role"]["generic-judge"], {"runs": 2, "cap": 1000, "peak_max": 1500,
                                                         "over_cap_runs": 1, "peak_to_cap_max": 1.5})
        self.assertEqual(m["by_role"]["Explore"], {"runs": 1, "cap": None, "peak_max": 9000,
                                                   "over_cap_runs": None, "peak_to_cap_max": None})
        self.assertEqual(list(m["by_role"]), sorted(m["by_role"]))

    def test_default_contracts_are_the_kit_roles(self):
        caps = tm.load_contract_caps(tm.DEFAULT_CONTRACTS_DIR)
        self.assertIn("generic-judge", caps)
        self.assertTrue(all(isinstance(v, int) and v > 0 for v in caps.values()))

    def test_missing_contract_dir_gives_no_caps(self):
        self.assertEqual(tm.load_contract_caps(self.root / "nope"), {})


class ToolOutputShare(Base):
    """M101: ceil(chars/4) of tool_result content over fresh input tokens (input + cache_write)."""

    def test_share_by_tool(self):
        main = Script()
        main.call("m1", "t1", "Read", {"file_path": "/r/a.py"}, _usage(inp=100, cw=900))
        main.result("t1", "x" * 401)                                      # 101 tokens
        main.call("m2", "t2", "Bash", {"command": "ls"}, _usage(inp=50, cw=950, cr=5000))
        main.result("t2", [{"type": "text", "text": "y" * 40}, {"type": "image", "source": {}}])  # 10
        main.result("t_unknown", "z" * 8)                                 # 2, unknown call id
        m = ctx(self.analyze(main))["tool_output_share"]
        self.assertEqual(m["id"], "M101")
        self.assertEqual(m["label"], "Inferred")
        self.assertEqual(m["fresh_input_tokens"], 2000)
        self.assertEqual(m["tool_output_tokens_est"], 113)
        self.assertEqual(m["share"], round(113 / 2000, 6))
        self.assertEqual(m["by_tool"], {"Bash": 10, "Read": 101, "unknown": 2})

    def test_no_usage_gives_no_share(self):
        main = Script()
        main.result("t1", "abc")
        m = ctx(self.analyze(main))["tool_output_share"]
        self.assertIsNone(m["share"])
        self.assertEqual(m["tool_output_tokens_est"], 1)


class RereadRatio(Base):
    """M102: Reads of a path already read, over all Reads; same-range and cross-context variants."""

    def test_reread_counts(self):
        main = Script()
        main.call("m1", "r1", "Read", {"file_path": "/r/a.py"})
        main.call("m2", "r2", "Read", {"file_path": "/r/a.py"})
        main.call("m3", "r3", "Read", {"file_path": "/r/a.py", "offset": 10, "limit": 5})
        main.call("m4", "r4", "Read", {"file_path": "/r/b.py"})
        main.call("m5", "g1", "Grep", {"pattern": "x"})
        main.call("m6", "ag", "Agent", {"subagent_type": "generic-judge", "prompt": "p"})
        sub = Script(True)
        sub.call("s1", "sr1", "Read", {"file_path": "/r/a.py"})
        sub.call("s2", "sr2", "Read", {"file_path": "/r/c.py"})
        m = ctx(self.analyze(main, [("a1", "generic-judge", "ag", sub)]))["reread"]
        self.assertEqual(m["id"], "M102")
        self.assertEqual(m["label"], "Measured")
        self.assertEqual((m["reads"], m["distinct_paths"], m["rereads"]), (4, 2, 2))
        self.assertEqual(m["ratio"], 0.5)
        self.assertEqual((m["rereads_same_range"], m["ratio_same_range"]), (1, 0.25))
        self.assertEqual(m["all_contexts"], {"reads": 6, "distinct_paths": 3, "rereads": 3, "ratio": 0.5})

    def test_no_reads(self):
        m = ctx(self.analyze(Script()))["reread"]
        self.assertEqual(m["reads"], 0)
        self.assertIsNone(m["ratio"])


class SubagentReportSize(Base):
    """M103: ceil(chars/4) of the tool_result answering each Agent/Task call vs the 2,000-token cap (D9)."""

    def test_report_sizes(self):
        main = Script()
        main.call("m1", "a1", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})
        main.result("a1", "r" * 8004)                                     # 2001 > cap
        main.call("m2", "a2", "Task", {"subagent_type": "generic-challenger", "prompt": "p"})
        main.result("a2", [{"type": "text", "text": "c" * 800}])          # 200
        main.call("m3", "a3", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})
        main.result("a3", "q" * 8000)                                     # 2000, at the cap
        main.call("m4", "b1", "Bash", {"command": "ls"})
        main.result("b1", "w" * 99999)                                    # not a report
        m = ctx(self.analyze(main))["subagent_reports"]
        self.assertEqual(m["id"], "M103")
        self.assertEqual(m["label"], "Inferred")
        self.assertEqual(m["cap_tokens"], 2000)
        self.assertEqual(m["tokens_est"], [2001, 200, 2000])
        self.assertEqual((m["reports"], m["over_cap"], m["max_tokens_est"]), (3, 1, 2001))
        self.assertEqual(m["by_role"], {"generic-challenger": {"reports": 1, "over_cap": 0, "max_tokens_est": 200},
                                        "generic-proposer": {"reports": 2, "over_cap": 1, "max_tokens_est": 2001}})


class StartupLoad(Base):
    """M104: input + cache_write + cache_read of the first request, main and per subagent role."""

    def test_first_request(self):
        main = Script()
        main.call("m1", "ag", "Agent", {"subagent_type": "generic-judge", "prompt": "p"},
                  _usage(inp=3, cw=4000, cr=0))
        main.text("m2", "done", _usage(inp=1, cw=10, cr=9000))
        s1, s2, s3 = Script(True), Script(True), Script(True)
        s1.text("s1", "a", _usage(inp=2, cw=700))
        s1.text("s1b", "b", _usage(inp=2, cr=5000))
        s2.text("s2", "a", _usage(inp=5, cr=900))
        s3.human("no usage at all")
        m = ctx(self.analyze(main, [("a1", "generic-judge", "ag", s1), ("a2", "generic-judge", "ag", s2),
                                    ("a3", "generic-verifier", "x", s3)]))["startup_load"]
        self.assertEqual(m["id"], "M104")
        self.assertEqual(m["label"], "Measured")
        self.assertEqual(m["main_tokens"], 4003)
        self.assertEqual(m["subagents_by_role"], {"generic-judge": [702, 905], "generic-verifier": []})

    def test_no_usage(self):
        self.assertIsNone(ctx(self.analyze(Script()))["startup_load"]["main_tokens"])


class RecallUsed(Base):
    """M105: a mem_search/mem_context result whose #id, topic key or title reappears later."""

    def test_recall_used_rate(self):
        main = Script()
        main.text("m0", "Before the recall #42 is mentioned: does not count.")
        main.call("m1", "e1", "mcp__engram__mem_search", {"query": "router"})
        main.result("e1", "Found 2 memories:\n[1] #42 (decision) — Router decides delegation\n"
                          "[2] #77 (bugfix) — Unrelated thing here\n")
        main.call("m2", "e2", "mcp__engram__mem_context", {"project": "p"})
        main.result("e2", "No memories found for that query")
        main.call("m3", "e3", "mcp__engram__mem_search", {"query": "cache"})
        main.result("e3", json.dumps([{"id": 91, "title": "Cache window decision"}]))
        main.call("m4", "e4", "mcp__plugin_engram_engram__mem_search", {"query": "topic"})
        main.result("e4", "#5 [architecture] Something long enough\ntopic_key: odd/delegation-context/tasks")
        main.call("m5", "e5", "mcp__engram__mem_search", {"query": "obs"})
        main.result("e5", "#314 (pattern) — Ids are fetched later")
        main.call("m6", "e6", "mcp__engram__mem_get_observation", {"id": 314})   # not a search: not counted
        main.result("e6", "full text")
        main.text("m7", "Per #42 the router decides. See odd/delegation-context/tasks.")
        m = ctx(self.analyze(main))["recall_used"]
        self.assertEqual(m["id"], "M105")
        self.assertEqual(m["label"], "Inferred")
        # e1 used (#42 cited), e2 empty, e3 not used, e4 used (topic key), e5 used (get_observation 314)
        self.assertEqual((m["recalls"], m["used"], m["empty"]), (5, 3, 1))
        self.assertEqual(m["rate"], 0.6)
        self.assertGreater(m["result_chars"], 0)

    def test_title_match_is_case_insensitive(self):
        main = Script()
        main.call("m1", "e1", "mcp__engram__mem_search", {"query": "x"})
        main.result("e1", json.dumps({"results": [{"id": 9, "title": "Window Cap Decision"}]}))
        main.call("m2", "w1", "Edit", {"file_path": "/r/x.md", "new_string": "following the window cap decision"})
        m = ctx(self.analyze(main))["recall_used"]
        self.assertEqual((m["recalls"], m["used"], m["rate"]), (1, 1, 1.0))

    def test_no_recalls(self):
        m = ctx(self.analyze(Script()))["recall_used"]
        self.assertEqual(m["recalls"], 0)
        self.assertIsNone(m["rate"])


class DelegationRatio(Base):
    """M106 (S3): router-asked subagent entries vs Agent/Task launches by subagent_type."""

    def session(self):
        main = Script()
        main.call("m1", "rt", "mcp__metodo__route", {"task": {}})
        main.result("rt", json.dumps({"inputs_hash": H1, "rule": "x"}))
        main.call("m1b", "rt3", "Bash", {"command": "route.sh t.json"})
        main.result("rt3", f"inputs_hash {H3}")
        main.call("m2", "a1", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})
        main.call("m3", "a2", "Task", {"subagent_type": "generic-challenger", "prompt": "p"})
        main.call("m4", "a3", "Agent", {"subagent_type": "Explore", "prompt": "p"})
        main.call("m5", "a4", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})
        return main

    def test_ratio_against_routing_log(self):
        routing = tm.load_routing_log(write_routing_log(self.root))
        m = ctx(self.analyze(self.session(), routing=routing))["delegation"]
        self.assertEqual(m["id"], "M106")
        self.assertEqual(m["label"], "Inferred")
        self.assertEqual(m["status"], "ok")
        self.assertEqual(m["decisions_matched"], 1)
        self.assertEqual((m["requested_subagent"], m["requested_main"], m["launched"]), (3, 1, 4))
        self.assertEqual(m["delegated"], 2)
        self.assertEqual(m["ratio"], round(2 / 3, 6))
        self.assertEqual(m["unrequested_launches"], 2)    # Explore + the second proposer
        self.assertEqual(m["by_role"]["generic-judge"], {"requested_subagent": 1, "requested_main": 0, "launched": 0})
        self.assertEqual(m["by_role"]["generic-cartographer"],
                         {"requested_subagent": 0, "requested_main": 1, "launched": 0})
        self.assertEqual(m["by_role"]["generic-proposer"], {"requested_subagent": 1, "requested_main": 0, "launched": 2})
        self.assertNotIn("generic-mechanic", m["by_role"])   # launch: skip is not asked
        self.assertNotIn("generic-verifier", m["by_role"])   # other session / status not ok
        self.assertEqual(list(m["by_role"]), sorted(m["by_role"]))

    def test_without_routing_log_is_not_run(self):
        m = ctx(self.analyze(self.session()))["delegation"]
        self.assertEqual(m["status"], "not-run")
        self.assertEqual(m["launched"], 4)
        self.assertIsNone(m["ratio"])
        self.assertIsNone(m["unrequested_launches"])

    def test_a_decision_seen_twice_counts_once(self):
        routing = tm.load_routing_log(write_routing_log(self.root))
        main = self.session()
        main.call("m6", "rt2", "mcp__metodo__route", {"task": {}})
        main.result("rt2", json.dumps({"inputs_hash": H1}))
        m = ctx(self.analyze(main, routing=routing))["delegation"]
        self.assertEqual((m["decisions_matched"], m["requested_subagent"]), (1, 3))

    def test_routing_log_without_match(self):
        routing = tm.load_routing_log(write_routing_log(self.root))
        main = Script()
        main.call("m1", "a1", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})
        m = ctx(self.analyze(main, routing=routing))["delegation"]
        self.assertEqual((m["status"], m["decisions_matched"], m["requested_subagent"]), ("ok", 0, 0))
        self.assertIsNone(m["ratio"])


class WarnActRate(Base):
    """M107: METODO-WARN lines shown, and whether the next assistant message's first call changed tool family."""

    def test_act_rate(self):
        main = Script()
        main.hook("METODO-WARN startup-thing: nothing to compare", event="SessionStart")   # no trigger
        main.call("m1", "e1", "Edit", {"file_path": "/r/a.kt"})
        main.hook("METODO-WARN delegate-writer: launch generic-proposer", tool_id="e1")
        main.result("e1", "ok")
        main.call("m2", "e2", "Write", {"file_path": "/r/b.kt"})         # same family: not acted
        main.result("e2", "ok\nMETODO-WARN delegate-writer: launch generic-proposer")
        main.call("m3", "a1", "Agent", {"subagent_type": "generic-proposer", "prompt": "p"})   # acted
        main.call("m4", "b1", "Bash", {"command": "git push"})
        main.result("b1", "METODO-WARN push-no-receipt: run the review\nMETODO-WARN push-no-receipt: run the review")
        # no later call: not judged
        m = ctx(self.analyze(main))["warn_act"]
        self.assertEqual(m["id"], "M107")
        self.assertEqual(m["label"], "Inferred")
        self.assertEqual((m["fires"], m["judged"], m["acted"]), (4, 2, 1))
        self.assertEqual((m["no_trigger"], m["no_next"]), (1, 1))
        self.assertEqual(m["rate"], 0.5)
        self.assertEqual(m["by_kind"], {"delegate-writer": {"fires": 2, "judged": 2, "acted": 1},
                                        "push-no-receipt": {"fires": 1, "judged": 0, "acted": 0},
                                        "startup-thing": {"fires": 1, "judged": 0, "acted": 0}})

    def test_sibling_call_in_the_same_message_is_not_the_next_call(self):
        main = Script()
        main.call("m1", "e1", "Edit", {"file_path": "/a"})
        main.hook("METODO-WARN delegate-writer: launch generic-proposer", tool_id="e1")
        main.call("m1", "g1", "Grep", {"pattern": "x"})      # same API message as e1: already decided
        main.call("m2", "e2", "Edit", {"file_path": "/b"})
        m = ctx(self.analyze(main))["warn_act"]
        self.assertEqual((m["fires"], m["judged"], m["acted"]), (1, 1, 0))

    def test_quoted_warns_are_not_fires(self):
        main = Script()
        main.call("m1", "r1", "Read", {"file_path": "/r/test_hooks.py"})
        main.result("r1", "METODO-WARN delegate-writer: inside a file read")      # file content
        main.call("m2", "b1", "Bash", {"command": "grep -rn WARN"})
        main.result("b1", "hooks/x.py:12: METODO-WARN delegate-writer: not at line start")
        main.call("m3", "b2", "Bash", {"command": "ls"})
        m = ctx(self.analyze(main))["warn_act"]
        self.assertEqual(m["fires"], 0)

    def test_human_text_is_not_a_warn(self):
        main = Script()
        main.human("METODO-WARN fake: typed by a person")
        main.text("m1", "METODO-WARN fake: quoted by the model")
        m = ctx(self.analyze(main))["warn_act"]
        self.assertEqual(m["fires"], 0)
        self.assertIsNone(m["rate"])


class ExistingFieldsUnchanged(unittest.TestCase):
    """Regression: every pre-existing field keeps its value; the new metrics live under one new key."""

    def test_old_fixture_output_matches_the_golden(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from test_transcript_metrics import SID as OLD_SID, build_fixture
        golden = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures"
                             / "transcript_metrics_v1_golden.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            proj = build_fixture(pathlib.Path(d))
            session = tm.analyze_session(proj / f"{OLD_SID}.jsonl")
        self.assertIn("context_metrics", session)
        old = {k: v for k, v in session.items() if k != "context_metrics"}
        self.assertEqual(json.loads(json.dumps(old, sort_keys=True)), golden)


class PrivacyAndDeterminism(Base):
    def build(self):
        main = Script()
        main.human("secret prompt about the login flow")
        main.call("m1", "r1", "Read", {"file_path": "/private/secret_path.py"}, _usage(inp=10, cw=100))
        main.result("r1", "secret file body")
        main.call("m2", "e1", "mcp__engram__mem_search", {"query": "q"})
        main.result("e1", "#42 (decision) — Private memory title here")
        main.call("m3", "rt", "mcp__metodo__route", {"task": {}})
        main.result("rt", json.dumps({"inputs_hash": H1}))
        main.call("m4", "a1", "Agent", {"subagent_type": "generic-proposer", "prompt": "brief text"})
        main.result("a1", "report body")
        main.hook("METODO-WARN delegate-writer: launch generic-proposer", tool_id="a1")
        sub = Script(True)
        sub.text("s1", "sub reply text", _usage(inp=6000))
        write_session(self.root, main, [("x1", "generic-proposer", "a1", sub)])

    def test_cli_is_deterministic_with_contracts_and_routing_log(self):
        self.build()
        contracts = write_contracts(self.root)
        log = write_routing_log(self.root)
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                out = pathlib.Path(od) / "x.json"
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "transcript_metrics.py"),
                                "--root", str(self.root), "--out", str(out), "--contracts", str(contracts),
                                "--routing-log", str(log)], check=True, capture_output=True)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        session = json.loads(outs[0])["sessions"][0]
        m = session["context_metrics"]
        self.assertEqual(sorted(m), ["delegation", "per_role_peak", "recall_used", "reread", "startup_load",
                                     "subagent_reports", "tool_output_share", "warn_act"])
        self.assertEqual(m["per_role_peak"]["by_role"]["generic-proposer"]["over_cap_runs"], 1)
        self.assertEqual(m["delegation"]["status"], "ok")
        text = outs[0].decode("utf-8")
        for private in ("secret", "login", "Private memory", "brief text", "report body", "sub reply", "/private"):
            self.assertNotIn(private, text)
        self.assertNotIn(H1, text)
        self.assertNotIn(str(self.root), text)

    def test_cli_rejects_a_missing_routing_log(self):
        self.build()
        with tempfile.TemporaryDirectory() as od:
            proc = subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "transcript_metrics.py"),
                                   "--root", str(self.root), "--out", str(pathlib.Path(od) / "x.json"),
                                   "--routing-log", str(self.root / "missing.jsonl")], capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"not a readable file", proc.stderr)


if __name__ == "__main__":
    unittest.main()
