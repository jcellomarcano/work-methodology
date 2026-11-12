"""hooks/bench_queue.py (benchmark-port S7) as a subprocess over a throwaway
tools instance under the system temp dir: a copy of hooks/ plus a stub
bin/bench.sh that records its argv and its process group. The real bench.sh
never runs here. In every case the hook exits 0 and prints nothing, on stdout
and on stderr, and it never waits for the collector."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
HOOKS = TOOLS_ROOT / "hooks"
SETTINGS = HOOKS / "hooks.settings.json"
HOOK = "bench_queue.py"
# Variables of the caller's shell that would point the hook at another instance, config or repo.
SCRUBBED = ("METODO_TOOLS", "METODO_PROJECT_CONFIG", "METODO_ACTIVATION_CONFIG", "METODO_HOOKS_DIR",
            "METODO_BENCH_NO_SPAWN", "CLAUDE_PROJECT_DIR")

# Records the argv, then its own pid and process group: a detached collector leads its own group.
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$$" "$(ps -o pgid= -p $$ | tr -d ' ')" > "{marker}.group"
printf '%s\\n' "$@" > "{marker}.tmp" && mv "{marker}.tmp" "{marker}"
"""

KIT_COMMAND = ': metodo-hook; H="${{METODO_TOOLS:-__TOOLS_DEFAULT__}}/hooks"; [ -f "$H/{script}" ] || exit 0; exec python3 "$H/{script}"'
GATES = "Bash|mcp__metodo__receipt_start|mcp__metodo__receipt_finalize|mcp__metodo__receipt_acknowledge"
WRITES = "Edit|Write|MultiEdit"
# Every entry the kit shipped before SessionEnd, in file order: (event, matcher, script, timeout).
OTHER_ENTRIES = [
    ("PreToolUse", WRITES, "guard_paths.py", 10),
    ("PreToolUse", GATES, "guard_gates.py", 10),
    ("PreToolUse", "Task|Agent", "guard_spawn.py", 10),
    ("PreToolUse", "", "budget.py", 10),
    ("PostToolUse", "Bash", "guard_gates.py", 10),
    ("PostToolUse", "Bash", "tool_output_filter.py", 10),
    ("PostToolUse", WRITES, "touched_paths.py", 10),
    ("PostToolUse", "mcp__metodo__output_write", "output_author.py", 10),
    ("PostToolUse", WRITES, "output_author.py", 10),
    ("Stop", "", "done_gate.py", 30),
    ("SubagentStop", "", "done_gate.py", 30),
    ("SessionStart", "startup|resume|compact|clear", "session_start_status.py", 10),
]


class BenchQueueFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-queue-"))
        self.tools = self.tmp / "tools"
        shutil.copytree(HOOKS, self.tools / "hooks", ignore=shutil.ignore_patterns("__pycache__", "pi", "agy"))
        (self.tools / "config").mkdir()
        (self.tools / "bin").mkdir()
        self.marker = self.tmp / "bench-argv.txt"
        self.write_stub(STUB)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.queue = self.tools / "out" / "bench" / "queue"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_stub(self, text: str) -> None:
        stub = self.tools / "bin" / "bench.sh"
        stub.write_text(text.format(marker=self.marker), encoding="utf-8")
        stub.chmod(0o755)

    def set_config(self, config: dict) -> None:
        (self.tools / "config" / "project.json").write_text(json.dumps(config), encoding="utf-8")

    def run_hook(self, payload, spawn: bool = False, raw: str | None = None, project_dir: bool = True) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        env.update(METODO_TOOLS=str(self.tools), METODO_HOOKS_DIR=str(self.tmp / "hooks-out"))
        if project_dir:
            env["CLAUDE_PROJECT_DIR"] = str(self.repo)
        if not spawn:
            env["METODO_BENCH_NO_SPAWN"] = "1"
        proc = subprocess.run(["python3", str(self.tools / "hooks" / HOOK)], input=json.dumps(payload) if raw is None else raw,
                              capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=20)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        return proc

    def payload(self, **extra) -> dict:
        base = {"session_id": "abc-123", "transcript_path": str(self.tmp / "abc-123.jsonl"), "cwd": str(self.repo),
                "hook_event_name": "SessionEnd", "reason": "other"}
        base.update(extra)
        return base

    def queue_items(self) -> list[str]:
        return sorted(p.name for p in self.queue.iterdir()) if self.queue.is_dir() else []

    def item(self, session_id: str = "abc-123") -> dict:
        return json.loads((self.queue / f"{session_id}.json").read_text(encoding="utf-8"))

    def wait_marker(self, seconds: float = 10.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline and not self.marker.exists():
            time.sleep(0.05)
        return self.marker.exists()

    def assert_never_spawned(self) -> None:
        time.sleep(0.5)
        self.assertFalse(self.marker.exists(), "the collector was spawned")


class QueueTests(BenchQueueFixture):
    def test_writes_the_queue_item_with_the_contract_shape(self):
        self.run_hook(self.payload())
        self.assertEqual(self.queue_items(), ["abc-123.json"])
        text = (self.queue / "abc-123.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), {"session_id": "abc-123", "transcript_path": str(self.tmp / "abc-123.jsonl")})
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True) + "\n")

    def test_rewrites_the_item_when_the_session_ends_again(self):
        self.run_hook(self.payload(transcript_path="/a.jsonl"))
        self.run_hook(self.payload(transcript_path="/b.jsonl"))
        self.assertEqual(self.queue_items(), ["abc-123.json"])
        self.assertEqual(self.item(), {"session_id": "abc-123", "transcript_path": "/b.jsonl"})

    def test_a_missing_or_non_text_transcript_path_is_queued_as_empty(self):
        missing = self.payload(session_id="no-path")
        del missing["transcript_path"]
        self.run_hook(missing)
        self.run_hook(self.payload(session_id="null-path", transcript_path=None))
        self.run_hook(self.payload(session_id="empty-path", transcript_path=""))
        for session_id in ("no-path", "null-path", "empty-path"):
            with self.subTest(session=session_id):
                self.assertEqual(self.item(session_id), {"session_id": session_id, "transcript_path": ""})

    def test_bench_disabled_writes_nothing_and_spawns_nothing(self):
        self.set_config({"bench": {"enabled": False}})
        self.run_hook(self.payload(), spawn=True)
        self.assertFalse((self.tools / "out").exists())
        self.assert_never_spawned()

    def test_an_absent_bench_key_means_enabled(self):
        for name, config in (("no-key", {"rdd": {"enabled": False}}), ("no-enabled", {"bench": {}}),
                             ("enabled", {"bench": {"enabled": True}})):
            with self.subTest(config=name):
                self.set_config(config)
                self.run_hook(self.payload(session_id=name))
                self.assertIn(f"{name}.json", self.queue_items())

    def test_a_bad_session_id_exits_silently_and_queues_nothing(self):
        for session_id in ("", "../escape", "a/b", "a\\b", "..", ".", ".hidden", "abc\n", "x" * 129, None, 42, ["abc"]):
            with self.subTest(session=session_id):
                self.run_hook(self.payload(session_id=session_id), spawn=True)
        self.assertEqual(self.queue_items(), [])
        self.assertFalse((self.tools / "out" / "bench" / "escape.json").exists())
        self.assertFalse((self.tools / "out" / "escape.json").exists())
        self.assert_never_spawned()

    def test_bad_stdin_exits_silently_and_queues_nothing(self):
        for raw in ("{not json", "", "[1, 2]", '"abc-123"', "null"):
            with self.subTest(stdin=raw):
                self.run_hook(None, spawn=True, raw=raw)
        self.assertEqual(self.queue_items(), [])
        self.assert_never_spawned()

    def test_a_queue_that_cannot_be_written_exits_silently(self):
        self.queue.parent.mkdir(parents=True)
        self.queue.write_text("a file where the queue directory goes\n", encoding="utf-8")
        self.run_hook(self.payload())
        self.assertTrue(self.queue.is_file())


class SpawnTests(BenchQueueFixture):
    def test_spawns_a_detached_collect_on_the_project_dir(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.run_hook(self.payload(cwd=str(elsewhere)), spawn=True)
        self.assertTrue(self.wait_marker(), "the stub bench.sh never ran")
        self.assertEqual(self.marker.read_text(encoding="utf-8").splitlines(), ["collect", str(self.repo)])
        pid, group = Path(f"{self.marker}.group").read_text(encoding="utf-8").split()
        self.assertEqual(pid, group, "the collector does not lead its own process group")
        self.assertEqual(self.queue_items(), ["abc-123.json"])

    def test_the_repo_falls_back_to_the_input_cwd(self):
        other = self.tmp / "other"
        other.mkdir()
        self.run_hook(self.payload(cwd=str(other)), spawn=True, project_dir=False)
        self.assertTrue(self.wait_marker(), "the stub bench.sh never ran")
        self.assertEqual(self.marker.read_text(encoding="utf-8").splitlines(), ["collect", str(other)])

    def test_no_repo_to_collect_keeps_the_item_and_spawns_nothing(self):
        payload = self.payload()
        del payload["cwd"]
        self.run_hook(payload, spawn=True, project_dir=False)
        self.assertEqual(self.queue_items(), ["abc-123.json"])
        self.assert_never_spawned()

    def test_the_no_spawn_variable_stops_the_spawn(self):
        self.run_hook(self.payload(), spawn=False)
        self.assertEqual(self.queue_items(), ["abc-123.json"])
        self.assert_never_spawned()

    def test_without_bench_sh_the_item_stays_queued(self):
        (self.tools / "bin" / "bench.sh").unlink()
        self.run_hook(self.payload(), spawn=True)
        self.assertEqual(self.queue_items(), ["abc-123.json"])

    def test_the_hook_does_not_wait_for_the_collector(self):
        self.write_stub("#!/usr/bin/env bash\nsleep 4\n" + STUB.split("\n", 1)[1])
        started = time.monotonic()
        self.run_hook(self.payload(), spawn=True)
        elapsed = time.monotonic() - started
        self.assertFalse(self.marker.exists(), "the hook waited for the collector")
        self.assertLess(elapsed, 3.0)


class DeclarationTests(unittest.TestCase):
    def settings(self) -> dict:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]

    def entries(self) -> list[tuple]:
        """(event, matcher, script, timeout) per hook, in file order; the command must be the kit template."""
        found = []
        for event, entries in self.settings().items():
            for entry in entries:
                self.assertEqual(sorted(entry), ["hooks", "matcher"], event)
                for hook in entry["hooks"]:
                    script = hook["command"].rsplit("/", 1)[-1].rstrip('"')
                    self.assertEqual(hook, {"type": "command", "timeout": hook["timeout"],
                                            "command": KIT_COMMAND.format(script=script)}, event)
                    found.append((event, entry["matcher"], script, hook["timeout"]))
        return found

    def test_the_session_end_entry_runs_bench_queue_with_the_kit_marker(self):
        self.assertEqual(self.settings().get("SessionEnd"), [{"matcher": "", "hooks": [{
            "type": "command", "timeout": 10, "command": KIT_COMMAND.format(script=HOOK)}]}])
        self.assertTrue((HOOKS / HOOK).is_file())
        self.assertFalse((HOOKS / "bench_session.py").exists(), "bench_session names another program in this tree")

    def test_every_other_event_keeps_its_order_matcher_and_timeout(self):
        self.assertEqual([entry for entry in self.entries() if entry[0] != "SessionEnd"], OTHER_ENTRIES)
        self.assertEqual([event for event in self.settings() if event != "SessionEnd"],
                         ["PreToolUse", "PostToolUse", "Stop", "SubagentStop", "SessionStart"])


if __name__ == "__main__":
    unittest.main()
