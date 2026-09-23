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
