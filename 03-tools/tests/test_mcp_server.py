"""The MCP server as a subprocess (real stdio handshake) and in-process
(passthrough == direct script, outfile, isError, JSON-RPC errors, write
guard). A temporary git repo stands in for the analyzed repo."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp import catalog, registry, server

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SERVER = TOOLS_ROOT / "mcp" / "server.py"

CARD = """**Why**: x [Medido]
**For what**: UX [Medido]
**What it risks**: none [Medido]
**When**: now [Medido]
**How**: c [Medido]
**How far**: d [Medido]
**How we'll know**: e [Medido]
**Invariant**: n/a
**Ticket**: no ticket
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _rpc(msg_id, method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        msg["id"] = msg_id
    if params is not None:
        msg["params"] = params
    return msg


class HandshakeSubprocessTests(unittest.TestCase):
    def test_initialize_list_and_ping_over_stdio(self):
        messages = [
            _rpc(1, "initialize", {"protocolVersion": server.PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}),
            _rpc(None, "notifications/initialized"),
            _rpc(2, "tools/list"),
            _rpc(3, "ping"),
        ]
        lines = "\n".join(json.dumps(m) for m in messages) + "\nnot json at all\n" + json.dumps(_rpc(4, "nope/method")) + "\n"
        proc = subprocess.run(["python3", str(SERVER)], input=lines, capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, METODO_REPO=""))
        responses = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        by_id = {r.get("id"): r for r in responses}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], server.PROTOCOL_VERSION)
        self.assertIn("tools", by_id[1]["result"]["capabilities"])
        self.assertEqual(len(by_id[2]["result"]["tools"]), len(catalog.TOOLS))
        self.assertEqual(by_id[3]["result"], {})
        self.assertEqual(by_id[None]["error"]["code"], server.PARSE_ERROR)
        self.assertEqual(by_id[4]["error"]["code"], server.METHOD_NOT_FOUND)
        # the notification gets no response: 5 responses for 6 lines
        self.assertEqual(len(responses), 5)
        self.assertNotIn("Traceback", proc.stderr)


class CatalogShapeTests(unittest.TestCase):
    def test_every_schema_is_a_closed_object_with_valid_required(self):
        names = [t.name for t in catalog.TOOLS]
        self.assertEqual(len(names), len(set(names)))
        for tool in catalog.TOOLS:
            schema = tool.input_schema
            self.assertEqual(schema["type"], "object", tool.name)
            self.assertIs(schema["additionalProperties"], False, tool.name)
            self.assertTrue(set(schema["required"]) <= set(schema["properties"]), tool.name)
            self.assertRegex(tool.name, r"^[a-z][a-z0-9_]*$")
            for prop in schema["properties"].values():
                if "enum" in prop:
                    self.assertTrue(prop["enum"], tool.name)

    def test_no_print_in_mcp_package(self):
        for path in (TOOLS_ROOT / "mcp").glob("*.py"):
            if path.name == "server.py":
                continue  # server.py prints only in --selftest
            self.assertNotIn("print(", path.read_text(encoding="utf-8"), path.name)

    def test_selftest_passes(self):
        proc = subprocess.run(["python3", str(SERVER), "--selftest"], capture_output=True, text=True, env=dict(os.environ, METODO_REPO=""))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["problems"], [])


class InProcessCallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "settings.gradle").write_text("include ':a'\n", encoding="utf-8")
        (self.repo / "a" / "src" / "main").mkdir(parents=True)
        (self.repo / "a" / "src" / "main" / "A.kt").write_text("class A {\n    fun f() = 1\n}\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.sha = _git(self.repo, "rev-parse", "HEAD")
        self.ctx = registry.Ctx(tools_root=TOOLS_ROOT, repo=self.repo, project_config={})
        self.card = self.tmp / "ficha.md"
        self.card.write_text(CARD, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(TOOLS_ROOT / "out" / self.sha, ignore_errors=True)

    def _call(self, name, arguments, msg_id=7):
        return server.handle(_rpc(msg_id, "tools/call", {"name": name, "arguments": arguments}), self.ctx)

    def test_passthrough_equals_direct_script(self):
        direct = json.loads(subprocess.run(
            ["python3", str(TOOLS_ROOT / "lib" / "change_card_validator.py"), "--config",
             str(TOOLS_ROOT / "config" / "project.json"), str(self.card)], capture_output=True, text=True).stdout)
        response = self._call("change_card_validate", {"card_path": str(self.card)})
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], direct)
        self.assertEqual(json.loads(result["content"][0]["text"]), direct)

    def test_card_text_goes_through_stdin(self):
        result = self._call("change_card_validate", {"card_text": CARD})["result"]
        self.assertEqual(result["structuredContent"]["verdict"], "PASS")
        self.assertEqual(result["structuredContent"]["routing"], "sonnet")

    def test_outfile_mode_returns_script_json(self):
        result = self._call("shape_metrics", {"repo": str(self.repo)})["result"]
        self.assertFalse(result["isError"], result["structuredContent"])
        on_disk = json.loads((TOOLS_ROOT / "out" / self.sha / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(result["structuredContent"], on_disk)

    def test_is_error_path_has_fixed_keys(self):
        result = self._call("change_card_validate", {"card_path": str(self.tmp / "missing.md")})["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(sorted(result["structuredContent"]), ["error", "exit_code", "stderr_tail"])

    def test_extra_property_is_invalid_params(self):
        response = self._call("change_card_validate", {"card_path": str(self.card), "rpeo": "x"})
        self.assertEqual(response["error"]["code"], server.INVALID_PARAMS)
        # negative control: the same call without the extra key works
        self.assertIn("result", self._call("change_card_validate", {"card_path": str(self.card)}))

    def test_unknown_tool_is_invalid_params(self):
        self.assertEqual(self._call("nope_tool", {})["error"]["code"], server.INVALID_PARAMS)

    def test_one_of_card_path_or_text(self):
        result = self._call("change_card_validate", {})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("exactly one", result["structuredContent"]["error"])

    def test_write_guard_refuses_round_inside_repo_and_build_file(self):
        doc = {"round": "r", "role": "judge", "rulings": []}
        inside = self._call("output_write", {"round_dir": str(self.repo / "round"), "role": "judge", "document": doc})["result"]
        self.assertTrue(inside["isError"])
        outside = self._call("output_write", {"round_dir": str(self.tmp / "round"), "role": "judge", "document": doc})["result"]
        self.assertFalse(outside["isError"], outside["structuredContent"])
        self.assertEqual(outside["structuredContent"]["verdict"], "PASS")
        handoff = self._call("handoff_write", {"round_dir": str(self.repo / "round"), "from_role": "judge", "to_role": "proposer",
                                               "topic": "x", "artifact_path": "a.json", "summary": "s", "residual_risks": []})["result"]
        self.assertTrue(handoff["isError"])
        self.assertIn("inside the analyzed repo", handoff["structuredContent"]["stderr_tail"][-1])

    def test_job_and_status(self):
        started = self._call("verify_commit", {"repo": str(self.repo), "range": f"{self.sha}~0..{self.sha}"})["result"]
        self.assertFalse(started["isError"], started)
        run_id = started["structuredContent"]["run_id"]
        status = self._call("job_status", {"run_id": run_id, "wait_seconds": 30})["result"]["structuredContent"]
        self.assertEqual(status["status"], "done")
        self.assertIsNotNone(status["exit_code"])
        shutil.rmtree(TOOLS_ROOT / "out" / "jobs" / run_id, ignore_errors=True)

    def test_repo_resolution_falls_back_to_ctx(self):
        result = self._call("test_sectors", {})["result"]
        self.assertFalse(result["isError"], result["structuredContent"])
        self.assertIn("full_required", result["structuredContent"])


REVIEW_TASK = {"task_kind": "review", "tier": "medium", "lane": "sonnet", "modules": 1, "map_age_days": 1,
               "prior": {"findings": 2}}


class RouteToolTests(unittest.TestCase):
    """`route` (mcp__metodo__route): the router's roster in-process, one log
    line in <tools>/out/runs/routing.jsonl, never inside the target repo.
    A temporary tools root keeps the kit's own out/ untouched."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp-route-"))
        self.tools = self.tmp / "tools"
        (self.tools / "config").mkdir(parents=True)
        shutil.copy(TOOLS_ROOT / "config" / "model-tiers.json", self.tools / "config" / "model-tiers.json")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        self.ctx = registry.Ctx(tools_root=self.tools, repo=self.repo, project_config={})
        self.log = self.tools / "out" / "runs" / "routing.jsonl"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("METODO_OFFLINE", None)
        os.environ.pop("METODO_PROJECT_CONFIG", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, arguments, ctx=None):
        return server.handle(_rpc(9, "tools/call", {"name": "route", "arguments": arguments}), ctx or self.ctx)

    def test_tools_list_contains_route_with_a_task_schema(self):
        listed = server.handle(_rpc(1, "tools/list"), self.ctx)["result"]["tools"]
        tool = next(t for t in listed if t["name"] == "route")
        schema = tool["inputSchema"]
        self.assertEqual(sorted(schema["required"]), ["as_of", "task"])
        self.assertIn("approvals", schema["properties"])
        self.assertIs(schema["properties"]["task"]["additionalProperties"], False)

    def test_call_returns_the_roster_and_appends_one_log_line(self):
        result = self._call({"task": REVIEW_TASK, "as_of": "2026-10-16"})["result"]
        self.assertFalse(result["isError"], result["structuredContent"])
        payload = result["structuredContent"]
        self.assertEqual((payload["rule"], payload["status"]), ("B5", "ok"))
        self.assertEqual([e["role"] for e in payload["roster"]],
                         ["generic-challenger", "generic-verifier", "generic-judge"])
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["inputs_hash"], payload["inputs_hash"])
        # same roster as the CLI's pure route()
        from lib import baseline, router
        direct = router.route(REVIEW_TASK, baseline.load_json(TOOLS_ROOT / "config" / "model-tiers.json"), "2026-10-16")
        self.assertEqual(payload["roster"], direct["roster"])
        self._call({"task": REVIEW_TASK, "as_of": "2026-10-16"})
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 2)

    def test_delegation_reaches_the_payload_and_the_log(self):
        # S1: read_files is a task field; coordinator, delegate and background come back; the log counts them
        payload = self._call({"task": dict(REVIEW_TASK, read_files=3), "as_of": "2026-10-16"})["result"]["structuredContent"]
        self.assertEqual(payload["coordinator"], "main")
        self.assertEqual([(e["delegate"], e["background"]) for e in payload["roster"]],
                         [("subagent", True), ("subagent", True), ("subagent", False)])
        line = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(line["delegation"], {"subagent": 3, "main": 0, "background": 2})
        result = self._call({"task": dict(REVIEW_TASK, read_files=-1), "as_of": "2026-10-16"})["result"]
        self.assertTrue(result["isError"], result)
        self.assertIn("read_files", result["structuredContent"]["error"])

    def test_approvals_reach_the_router_and_the_log(self):
        task = dict(REVIEW_TASK, owner_named=True)
        denied = self._call({"task": task, "as_of": "2026-10-16"})["result"]["structuredContent"]
        fable = [e for e in denied["roster"] if e["requires_approval"]]
        self.assertEqual([e["launch"] for e in fable], ["skip"])
        approved = self._call({"task": task, "as_of": "2026-10-16", "approvals": ["escalate-fable"]})["result"]["structuredContent"]
        self.assertEqual([e["launch"] for e in approved["roster"] if e["requires_approval"]], ["run"])
        last = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["approvals"], ["escalate-fable"])

    def test_offline_comes_from_the_active_project_config(self):
        config = self.tmp / "project.json"
        config.write_text(json.dumps({"offline": True}), encoding="utf-8")
        os.environ["METODO_PROJECT_CONFIG"] = str(config)
        payload = self._call({"task": REVIEW_TASK, "as_of": "2026-10-16"})["result"]["structuredContent"]
        self.assertEqual(payload["status"], "blocked")
        # the task's own key wins over the config
        payload = self._call({"task": dict(REVIEW_TASK, offline=False), "as_of": "2026-10-16"})["result"]["structuredContent"]
        self.assertEqual(payload["status"], "ok")

    def test_bad_input_is_invalid_params_and_logs_nothing(self):
        for arguments in ({"task": REVIEW_TASK},
                          {"task": dict(REVIEW_TASK, task_kind="dance"), "as_of": "2026-10-16"},
                          {"task": dict(REVIEW_TASK, rpeo="x"), "as_of": "2026-10-16"},
                          {"task": REVIEW_TASK, "as_of": "2026-10-16", "approvals": ["anything"]}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self._call(arguments)["error"]["code"], server.INVALID_PARAMS)
        self.assertFalse(self.log.exists())

    def test_malformed_task_values_are_is_error_never_a_raise(self):
        cases = ({"modules": [1, "a"]}, {"map_age_days": -1}, {"budget_usd": -5}, {"new_comments": -1},
                 {"changed_lines": -3}, {"prior": {"p0_from_lower_tier": "huge"}}, {"prior": {"stalls": -1}},
                 {"prior": {"tier": "medium", "role": "generic-judge", "findings": -1}})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                response = self._call({"task": dict(REVIEW_TASK, **overrides), "as_of": "2026-10-16"})
                result = response["result"]
                self.assertTrue(result["isError"], result)
                self.assertIn("guard:input", result["structuredContent"]["error"])
        self.assertFalse(self.log.exists())

    def test_bad_as_of_and_malformed_catalog_are_is_error(self):
        for as_of in ("2026-13-45", "16/10/2026"):
            with self.subTest(as_of=as_of):
                result = self._call({"task": REVIEW_TASK, "as_of": as_of})["result"]
                self.assertTrue(result["isError"], result)
                self.assertIn("guard:as_of", result["structuredContent"]["error"])
        catalog = json.loads((self.tools / "config" / "model-tiers.json").read_text(encoding="utf-8"))
        for broken in ([], dict(catalog, router=dict(catalog["router"], max_parallel=0))):
            with self.subTest(catalog=type(broken).__name__):
                (self.tools / "config" / "model-tiers.json").write_text(json.dumps(broken), encoding="utf-8")
                result = self._call({"task": REVIEW_TASK, "as_of": "2026-10-16"})["result"]
                self.assertTrue(result["isError"], result)
                self.assertIn("guard:catalog", result["structuredContent"]["error"])
        self.assertFalse(self.log.exists())

    def test_log_inside_the_target_repo_is_refused(self):
        inside = self.repo / "tools"
        shutil.copytree(self.tools, inside)
        ctx = registry.Ctx(tools_root=inside, repo=self.repo, project_config={})
        result = self._call({"task": REVIEW_TASK, "as_of": "2026-10-16"}, ctx)["result"]
        self.assertTrue(result["isError"])
        self.assertIn("inside the target repo", result["structuredContent"]["error"])
        self.assertFalse((inside / "out" / "runs" / "routing.jsonl").exists())


class ReceiptStartBaseTests(unittest.TestCase):
    """receipt_start without `base` takes it from lib/base_ref.py: the
    config's test_sectors.base_ref, then origin/HEAD, then origin/develop."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp-base-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "f.txt").write_text("x", encoding="utf-8")
        _git(self.repo, "add", "f.txt")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.spec = next(t for t in catalog.TOOLS if t.name == "receipt_start")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _base(self, config: dict, **args) -> str:
        ctx = registry.Ctx(tools_root=TOOLS_ROOT, repo=self.repo, project_config=config)
        cmd = self.spec.argv({"round_dir": str(self.tmp / "round"), **args}, ctx)
        return cmd[cmd.index("--base") + 1]

    def _set_origin_head(self, name: str):
        _git(self.repo, "update-ref", f"refs/remotes/origin/{name}", "HEAD")
        _git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{name}")

    def test_config_base_ref_is_used(self):
        self._set_origin_head("main")
        self.assertEqual(self._base({"test_sectors": {"base_ref": "origin/release"}}), "origin/release")

    def test_unset_config_falls_back_to_origin_head(self):
        self._set_origin_head("main")
        self.assertEqual(self._base({}), "origin/main")

    def test_neither_falls_back_to_origin_develop(self):
        self.assertEqual(self._base({}), "origin/develop")

    def test_explicit_base_still_wins(self):
        self._set_origin_head("main")
        self.assertEqual(self._base({"test_sectors": {"base_ref": "origin/release"}}, base="feature/x"), "feature/x")
