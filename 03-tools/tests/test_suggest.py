"""lib/suggest.py and config/suggestions.json (kit-init T8, S3, Log L14).

Every helper is detected against a controlled PATH (a temp dir of stub
binaries) and a fake HOME. Global configs (~/.claude.json,
~/.pi/agent/mcp.json) are read only with read_global_config=True: without
it the fake HOME's files are never opened, which the tests prove by
recording every open() during the call."""
import builtins
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DATA = TOOLS_ROOT / "config" / "suggestions.json"
SUGGEST = TOOLS_ROOT / "lib" / "suggest.py"
REQUIRED_IDS = {"engram", "context7", "gentle-ai", "gh", "java", "node"}

sys.path.insert(0, str(TOOLS_ROOT))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def stub(bin_dir: Path, name: str, body: str = "exit 0") -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class SuggestionsDataTests(unittest.TestCase):
    def test_every_entry_is_data_with_source_and_verified_flag(self):
        entries = json.loads(DATA.read_text(encoding="utf-8"))["suggestions"]
        ids = [e["id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertTrue(REQUIRED_IDS <= set(ids), sorted(REQUIRED_IDS - set(ids)))
        for entry in entries:
            for key in ("id", "why", "detect", "command", "source", "verified"):
                self.assertIn(key, entry, entry.get("id"))
            self.assertIsInstance(entry["verified"], bool, entry["id"])
            self.assertTrue(entry["source"].strip(), entry["id"])
            self.assertTrue(entry["why"].strip(), entry["id"])
            self.assertIsInstance(entry["command"], dict, entry["id"])


class SuggestTests(unittest.TestCase):
    def setUp(self):
        from lib import suggest
        self.suggest = suggest
        self.tmp = Path(tempfile.mkdtemp(prefix="suggest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.home = self.tmp / "home"
        (self.home / ".pi" / "agent").mkdir(parents=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        self.tools = self.tmp / "tools"
        (self.tools / "config").mkdir(parents=True)
        (self.tools / "config" / "project.json").write_text(json.dumps({"memory": {"enabled": True}}), encoding="utf-8")
        self.env = {"PATH": str(self.bin), "HOME": str(self.home)}

    def run_suggest(self, read_global=False, runtime="all"):
        return {e["id"]: e for e in self.suggest.suggest(self.repo, self.tools, runtime, read_global, env=self.env)}

    def test_output_shape(self):
        out = self.suggest.suggest(self.repo, self.tools, "all", False, env=self.env)
        self.assertTrue(REQUIRED_IDS <= {e["id"] for e in out})
        for entry in out:
            self.assertEqual(set(entry), {"id", "status", "why", "command"}, entry)
            self.assertIn(entry["status"], {"present", "missing", "unknown"})
            if entry["status"] == "present":
                self.assertIsNone(entry["command"], entry)
            else:
                self.assertIsInstance(entry["command"], str, entry)

    def test_empty_path_reports_binaries_missing_with_a_command(self):
        got = self.run_suggest()
        for name in ("engram", "gentle-ai", "gh", "java", "node"):
            self.assertEqual(got[name]["status"], "missing", got[name])
            self.assertTrue(got[name]["command"], got[name])
        self.assertIn("brew install gentleman-programming/tap/engram", got["engram"]["command"])
        self.assertIn("engram setup claude-code", got["engram"]["command"])
        self.assertIn("engram setup pi", got["engram"]["command"])

    def test_stub_binaries_are_present(self):
        stub(self.bin, "engram")
        stub(self.bin, "gentle-ai", 'echo "receipt-driven development: off"')
        stub(self.bin, "gh")
        stub(self.bin, "java")
        stub(self.bin, "node", 'echo v22.6.0')
        got = self.run_suggest()
        for name in ("engram", "gentle-ai", "gh", "java", "node"):
            self.assertEqual(got[name]["status"], "present", got[name])
            self.assertIsNone(got[name]["command"])

    def test_old_node_is_missing(self):
        stub(self.bin, "node", 'echo v20.11.0')
        got = self.run_suggest()
        self.assertEqual(got["node"]["status"], "missing")
        self.assertIn("22.6", got["node"]["why"])

    def test_java_stub_that_fails_is_missing(self):
        stub(self.bin, "java", "exit 1")
        self.assertEqual(self.run_suggest()["java"]["status"], "missing")

    def test_engram_binary_present_but_memory_disabled_is_missing(self):
        stub(self.bin, "engram")
        (self.tools / "config" / "project.json").write_text(json.dumps({"memory": {"enabled": False}}), encoding="utf-8")
        got = self.run_suggest()["engram"]
        self.assertEqual(got["status"], "missing")
        self.assertIn("memory.enabled", got["command"])

    def test_node_is_only_suggested_for_pi(self):
        self.assertNotIn("node", self.run_suggest(runtime="claude"))
        self.assertIn("node", self.run_suggest(runtime="pi"))

    def test_agy_gets_its_own_commands_and_no_pi_only_helper(self):
        got = self.run_suggest(runtime="agy")
        self.assertNotIn("node", got)
        self.assertIn("agy mcp add context7", got["context7"]["command"])
        self.assertNotIn("claude mcp add", got["context7"]["command"])
        for helper in ("engram", "gentle-ai", "gh", "java"):
            self.assertIn(helper, got)

    def test_all_still_means_claude_and_pi(self):
        got = self.run_suggest(runtime="all")
        self.assertNotIn("agy mcp add", got["context7"]["command"])
        self.assertIn("claude mcp add", got["context7"]["command"])
        self.assertEqual(self.suggest._runtimes("all"), ("claude", "pi"))

    def test_agy_does_not_read_the_repo_mcp_json(self):
        # agy loads MCP servers from its global config or a plugin, never from .mcp.json or .pi/mcp.json
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"context7": {"command": "npx"}}}), encoding="utf-8")
        self.assertEqual(self.run_suggest(runtime="claude")["context7"]["status"], "present")
        self.assertEqual(self.run_suggest(runtime="pi")["context7"]["status"], "present")
        got = self.run_suggest(runtime="agy")["context7"]
        self.assertEqual(got["status"], "unknown")
        self.assertNotIn("the repo's the repo", got["why"])
        self.assertIn("~/.gemini/config/mcp_config.json", got["why"])

    def test_cli_accepts_the_agy_runtime(self):
        proc = subprocess.run([sys.executable, str(SUGGEST), str(self.repo), "--tools", str(self.tools), "--runtime", "agy"],
                              capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("node", [e["id"] for e in json.loads(proc.stdout)])

    def test_context7_in_repo_mcp_json_is_present(self):
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"context7": {"command": "npx"}}}), encoding="utf-8")
        self.assertEqual(self.run_suggest()["context7"]["status"], "present")

    def test_context7_in_repo_pi_mcp_json_is_present(self):
        (self.repo / ".pi").mkdir()
        (self.repo / ".pi" / "mcp.json").write_text(json.dumps({"mcpServers": {"context7": {}}}), encoding="utf-8")
        self.assertEqual(self.run_suggest()["context7"]["status"], "present")

    def _plant_global_context7(self):
        payload = json.dumps({"mcpServers": {"context7": {"command": "npx", "env": {"TOKEN": "secret-value"}}}})
        (self.home / ".claude.json").write_text(payload, encoding="utf-8")
        (self.home / ".pi" / "agent" / "mcp.json").write_text(payload, encoding="utf-8")

    def test_global_mcp_configs_are_read_per_runtime(self):
        gemini = self.home / ".gemini" / "config" / "mcp_config.json"
        gemini.parent.mkdir(parents=True)
        gemini.write_text(json.dumps({"mcpServers": {"context7": {"command": "npx"}}}), encoding="utf-8")
        self.assertEqual(self.run_suggest(read_global=True, runtime="claude")["context7"]["status"], "missing")
        self.assertEqual(self.run_suggest(read_global=True, runtime="pi")["context7"]["status"], "missing")
        self.assertEqual(self.run_suggest(read_global=True, runtime="all")["context7"]["status"], "missing")
        self.assertEqual(self.run_suggest(read_global=True, runtime="agy")["context7"]["status"], "present")
        self.assertNotIn(".gemini", self.run_suggest(runtime="claude")["context7"]["why"])
        self.assertNotIn(".claude.json", self.run_suggest(runtime="agy")["context7"]["why"])

    def test_a_plain_file_list_still_applies_to_every_runtime(self):
        entries = [{"id": "x", "why": "w", "runtimes": ["claude", "pi", "agy"], "command": {"claude": "c", "agy": "a"},
                    "detect": {"mcp_server": {"key": "x", "repo": [".mcp.json"], "global": ["~/.claude.json"]}}}]
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {}}}), encoding="utf-8")
        for runtime in ("claude", "pi", "agy", "all"):
            got = self.suggest.suggest(self.repo, self.tools, runtime, False, env=self.env, entries=entries)
            self.assertEqual(got[0]["status"], "present", runtime)

    def test_global_configs_are_never_opened_without_the_flag(self):
        self._plant_global_context7()
        opened = []
        real_open = builtins.open

        def spy(file, *args, **kwargs):
            opened.append(os.fspath(file) if isinstance(file, (str, os.PathLike)) else str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
            got = self.run_suggest(read_global=False)
        home = os.path.realpath(self.home)
        touched = [p for p in opened if os.path.realpath(p).startswith(home + os.sep)]
        self.assertEqual(touched, [])
        self.assertNotEqual(got["context7"]["status"], "present")
        self.assertEqual(got["context7"]["status"], "unknown")
        self.assertIn("--read-global-config", got["context7"]["why"])

    def test_unreadable_global_config_without_flag_is_no_error_and_no_detection(self):
        self._plant_global_context7()
        for path in (self.home / ".claude.json", self.home / ".pi" / "agent" / "mcp.json"):
            path.chmod(0)
        self.addCleanup(lambda: [p.chmod(0o600) for p in (self.home / ".claude.json", self.home / ".pi" / "agent" / "mcp.json")])
        got = self.run_suggest(read_global=False)
        self.assertEqual(got["context7"]["status"], "unknown")

    def test_global_configs_are_read_with_the_flag_and_never_printed(self):
        self._plant_global_context7()
        got = self.run_suggest(read_global=True)
        self.assertEqual(got["context7"]["status"], "present")
        self.assertNotIn("secret-value", json.dumps(got))

    def test_flag_without_context7_anywhere_is_missing_with_a_command(self):
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")
        got = self.run_suggest(read_global=True)["context7"]
        self.assertEqual(got["status"], "missing")
        self.assertTrue(got["command"])

    def test_cli_prints_json_and_writes_nothing(self):
        stub(self.bin, "engram")
        before = sorted(p.relative_to(self.tmp).as_posix() for p in self.tmp.rglob("*"))
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.path.dirname(sys.executable), HOME=str(self.home))
        proc = subprocess.run([sys.executable, str(SUGGEST), str(self.repo), "--tools", str(self.tools)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual({e["id"]: e["status"] for e in data}["engram"], "present")
        after = sorted(p.relative_to(self.tmp).as_posix() for p in self.tmp.rglob("*"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
