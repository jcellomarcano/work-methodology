"""bin/bench.sh and lib/bench_collect.py (benchmark-port S4, S5, S6).

Every test runs on a throwaway instance under the system temp dir whose
bench/lib is a copy of the kit's 08-benchmark/lib, a synthetic transcript root
(CLAUDE_PROJECTS_DIR) and a fake HOME: the real ~/.claude/projects and any
real instance are never read or written."""
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
BENCH_SH = TOOLS_ROOT / "bin" / "bench.sh"
COLLECTOR = TOOLS_ROOT / "lib" / "bench_collect.py"
BENCH_LIB = TOOLS_ROOT.parent / "08-benchmark" / "lib"
SID = "11111111-2222-3333-4444-555555555555"
SID2 = "22222222-3333-4444-5555-666666666666"
SECRET_PROMPT = "fix the login bug with the secret word zebra"
SECRET_REPLY = "Done, the zebra is fixed."
STRIPPED_ENV = ("METODO_TOOLS", "METODO_PROJECT_CONFIG", "CLAUDE_PROJECTS_DIR")
# Echoes its arguments and exits 7: stands in for <instance>/bench/lib/bench_cli.py.
CLI_STUB = "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n"


def transcript_records(session_id: str, cwd: str, kit: bool) -> list[dict]:
    common = {"sessionId": session_id, "cwd": cwd, "version": "2.1.209", "gitBranch": "main",
              "isSidechain": False, "userType": "external"}
    usage = {"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 500,
             "output_tokens": 40}
    tool = "mcp__metodo__doctor" if kit else "Read"
    return [
        dict(common, type="user", timestamp="2026-09-20T10:00:00.000Z", permissionMode="acceptEdits",
             origin={"kind": "human"}, message={"role": "user", "content": SECRET_PROMPT}),
        dict(common, type="assistant", timestamp="2026-09-20T10:00:03.000Z", requestId="req_1",
             message={"id": "msg_1", "model": "claude-opus-5-5", "role": "assistant", "usage": usage,
                      "content": [{"type": "tool_use", "id": "toolu_1", "name": tool, "input": {}}]}),
        dict(common, type="user", timestamp="2026-09-20T10:00:04.000Z",
             message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                   "content": "ok"}]}),
        dict(common, type="assistant", timestamp="2026-09-20T10:00:06.000Z", requestId="req_2",
             message={"id": "msg_2", "model": "claude-opus-5-5", "role": "assistant", "usage": usage,
                      "content": [{"type": "text", "text": SECRET_REPLY}]}),
    ]


def project_dir_name(repo: Path) -> str:
    """The Claude Code rule, spelled out here so the test does not lean on the code under test."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(repo))


class BenchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-collect-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.instance = self.tmp / "inst"
        shutil.copytree(BENCH_LIB, self.instance / "bench" / "lib",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.instance / "config").mkdir(parents=True)
        self.repo = self.tmp / "my_repo"
        self.repo.mkdir()
        self.transcripts = self.tmp / "projects"
        self.project_dir = self.transcripts / project_dir_name(self.repo)
        self.project_dir.mkdir(parents=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.out = self.instance / "out" / "bench"

    def env(self, **extra: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
        env.update(HOME=str(self.home), CLAUDE_PROJECTS_DIR=str(self.transcripts), **extra)
        return env

    def write_transcript(self, session_id: str = SID, kit: bool = True, where: Path | None = None) -> Path:
        path = (where or self.project_dir) / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(r) for r in transcript_records(session_id, str(self.repo), kit)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def queue(self, name: str, payload) -> Path:
        item = self.out / "queue" / f"{name}.json"
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return item

    def bench(self, *args: str, tools: bool = True, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["bash", str(BENCH_SH), *args]
        if tools:
            cmd += ["--tools", str(self.instance)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self.env())
        if check:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def collect(self) -> dict:
        proc = self.bench("collect", str(self.repo))
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        return json.loads(lines[0])

    def aggregate(self) -> dict:
        return json.loads((self.out / "data" / "sessions.json").read_text(encoding="utf-8"))

    def tree_bytes(self) -> dict:
        return {p.relative_to(self.out).as_posix(): p.read_bytes() for p in sorted(self.out.rglob("*")) if p.is_file()}

    def assert_no_absolute_paths(self, text: str, where: str = ""):
        for p in (str(self.tmp), os.path.realpath(self.tmp), str(self.home)):
            self.assertNotIn(p, text, where)


class CollectTests(BenchTestCase):
    def test_first_collect_measures_and_writes_row_and_aggregate(self):
        self.write_transcript()
        summary = self.collect()
        self.assertEqual(summary, {"failed": 0, "measured": 1, "queue_left": 0, "skipped": 0})
        row = json.loads((self.out / "sessions" / f"{SID}.json").read_text(encoding="utf-8"))
        self.assertEqual(row["session_id"], SID)
        self.assertEqual(row["project"], "my_repo")
        self.assertTrue(row["kit"]["uses_kit"])
        agg = self.aggregate()
        self.assertEqual(sorted(agg), ["failures", "root", "schema_version", "sessions", "tool_sha256"])
        self.assertEqual(agg["sessions"], [row])
        self.assertEqual(agg["failures"], [])
        self.assertEqual(agg["root"], "projects")
        source = (self.instance / "bench" / "lib" / "transcript_metrics.py").read_bytes()
        self.assertEqual(agg["tool_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(agg["schema_version"], re.search(rb'^SCHEMA_VERSION = "([^"]+)"', source, re.M).group(1).decode())

    def test_summary_is_one_line_with_sorted_keys(self):
        self.write_transcript()
        out = self.bench("collect", str(self.repo)).stdout
        self.assertEqual(out, json.dumps(json.loads(out), sort_keys=True) + "\n")

    def test_second_collect_skips_a_transcript_that_is_not_newer(self):
        self.write_transcript()
        self.collect()
        row = self.out / "sessions" / f"{SID}.json"
        before = (row.read_bytes(), row.stat().st_mtime_ns)
        self.assertEqual(self.collect(), {"failed": 0, "measured": 0, "queue_left": 0, "skipped": 1})
        self.assertEqual((row.read_bytes(), row.stat().st_mtime_ns), before)

    def test_a_newer_transcript_is_measured_again(self):
        path = self.write_transcript()
        self.collect()
        row = self.out / "sessions" / f"{SID}.json"
        later = row.stat().st_mtime + 10
        os.utime(path, (later, later))
        self.assertEqual(self.collect(), {"failed": 0, "measured": 1, "queue_left": 0, "skipped": 0})

    def test_sessions_of_another_repo_are_not_swept(self):
        self.write_transcript()
        other = self.tmp / "other_repo"
        other.mkdir()
        self.write_transcript(SID2, where=self.transcripts / project_dir_name(other))
        self.collect()
        self.assertEqual([s["session_id"] for s in self.aggregate()["sessions"]], [SID])

    def test_a_symlinked_repo_path_reaches_the_transcripts_of_its_real_dir(self):
        self.write_transcript()
        link = self.tmp / "link"
        link.symlink_to(self.repo)
        proc = self.bench("collect", str(link))
        self.assertEqual(json.loads(proc.stdout)["measured"], 1)

    def test_queue_item_is_measured_and_removed(self):
        elsewhere = self.write_transcript(SID2, kit=False, where=self.tmp / "other-dir")
        item = self.queue(SID2, {"session_id": SID2, "transcript_path": str(elsewhere)})
        self.assertEqual(self.collect(), {"failed": 0, "measured": 1, "queue_left": 0, "skipped": 0})
        self.assertFalse(item.exists())
        self.assertTrue((self.out / "sessions" / f"{SID2}.json").is_file())

    def test_queued_transcript_that_no_longer_exists_fails_and_is_removed(self):
        gone = self.tmp / "gone" / f"{SID2}.jsonl"
        item = self.queue(SID2, {"session_id": SID2, "transcript_path": str(gone)})
        self.assertEqual(self.collect(), {"failed": 1, "measured": 0, "queue_left": 0, "skipped": 0})
        self.assertFalse(item.exists())
        self.assertEqual(self.aggregate()["failures"], [{"reason": "transcript missing", "session_id": SID2}])

    def test_queue_item_with_an_empty_path_is_served_by_the_sweep(self):
        self.write_transcript()
        item = self.queue(SID, {"session_id": SID, "transcript_path": ""})
        self.assertEqual(self.collect(), {"failed": 0, "measured": 1, "queue_left": 0, "skipped": 0})
        self.assertFalse(item.exists())
        self.assertEqual(self.aggregate()["failures"], [])

    def test_unreadable_queue_item_fails_and_is_removed(self):
        item = self.queue("broken", "{not json")
        self.assertEqual(self.collect(), {"failed": 1, "measured": 0, "queue_left": 0, "skipped": 0})
        self.assertFalse(item.exists())
        self.assertEqual(self.aggregate()["failures"], [{"reason": "bad queue item", "session_id": "broken"}])

    def test_a_transcript_that_cannot_be_analyzed_is_counted_and_the_rest_is_measured(self):
        self.write_transcript()
        (self.project_dir / f"{SID2}.jsonl").mkdir()
        proc = self.bench("collect", str(self.repo))
        self.assertEqual(json.loads(proc.stdout), {"failed": 1, "measured": 1, "queue_left": 0, "skipped": 0})
        agg = self.aggregate()
        self.assertEqual([s["session_id"] for s in agg["sessions"]], [SID])
        self.assertEqual([(f["reason"], f["session_id"]) for f in agg["failures"]], [("analysis failed", SID2)])
        self.assert_no_absolute_paths(json.dumps(agg))

    def test_a_held_lock_is_reported_and_exits_zero(self):
        self.write_transcript()
        self.out.mkdir(parents=True)
        with open(self.out / ".lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            proc = self.bench("collect", str(self.repo))
        self.assertEqual(proc.stdout, '{"locked": true}\n')
        self.assertFalse((self.out / "sessions").exists())
        self.assertFalse((self.out / "data").exists())

    def test_two_collects_leave_byte_identical_files(self):
        self.write_transcript()
        self.write_transcript(SID2, kit=False)
        self.collect()
        first = self.tree_bytes()
        self.assertEqual(sorted(first), [".lock", "data/sessions.json", f"sessions/{SID}.json", f"sessions/{SID2}.json"])
        self.collect()
        self.assertEqual(self.tree_bytes(), first)
        shutil.rmtree(self.out / "sessions")
        self.collect()
        self.assertEqual(self.tree_bytes(), first)

    def test_no_prompt_or_reply_text_and_no_absolute_path_in_output_or_files(self):
        self.write_transcript()
        elsewhere = self.write_transcript(SID2, kit=False, where=self.tmp / "other-dir")
        self.queue(SID2, {"session_id": SID2, "transcript_path": str(elsewhere)})
        proc = self.bench("collect", str(self.repo))
        self.assertEqual(json.loads(proc.stdout)["measured"], 2)
        self.assert_no_absolute_paths(proc.stdout + proc.stderr)
        files = self.tree_bytes()
        self.assertIn(f"sessions/{SID2}.json", files)
        for name, raw in files.items():
            text = raw.decode("utf-8")
            self.assertNotIn("zebra", text, name)
            self.assert_no_absolute_paths(text, name)

    def test_instance_resolves_from_metodo_tools(self):
        self.write_transcript()
        proc = subprocess.run(["bash", str(BENCH_SH), "collect", str(self.repo)],
                              capture_output=True, text=True, env=self.env(METODO_TOOLS=str(self.instance)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["measured"], 1)
        self.assertTrue((self.out / "sessions" / f"{SID}.json").is_file())

    def test_instance_defaults_to_the_parent_of_the_script(self):
        self.write_transcript()
        for src in (BENCH_SH, COLLECTOR):
            dst = self.instance / src.parent.name / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        proc = subprocess.run(["bash", str(self.instance / "bin" / "bench.sh"), "collect", str(self.repo)],
                              capture_output=True, text=True, env=self.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["measured"], 1)
        self.assertTrue((self.out / "sessions" / f"{SID}.json").is_file())

    def test_missing_bench_lib_fails_with_exit_2(self):
        shutil.rmtree(self.instance / "bench")
        proc = self.bench("collect", str(self.repo), check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("bench/lib", proc.stderr)
        self.assertIn("sync-instance.sh", proc.stderr)
        self.assert_no_absolute_paths(proc.stdout + proc.stderr)


class AdoptStatusTests(BenchTestCase):
    def test_adopt_records_once_then_keeps(self):
        self.assertEqual(self.bench("adopt", str(self.repo)).stdout, "recorded\n")
        path = self.out / "adoption.json"
        first = path.read_bytes()
        record = json.loads(first)
        self.assertEqual(sorted(record), ["installed_at", "label", "repo"])
        self.assertEqual(record["repo"], "my_repo")
        self.assertEqual(record["label"], "Measured")
        self.assertRegex(record["installed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        parsed = datetime.datetime.fromisoformat(record["installed_at"].replace("Z", "+00:00"))
        self.assertLess(abs((datetime.datetime.now(datetime.timezone.utc) - parsed).total_seconds()), 120)
        self.assertEqual(self.bench("adopt", str(self.repo)).stdout, "kept\n")
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["adoption.json"])

    def test_adopt_names_the_repo_by_its_resolved_path(self):
        link = self.tmp / "link"
        link.symlink_to(self.repo)
        self.bench("adopt", str(link))
        self.assertEqual(json.loads((self.out / "adoption.json").read_text(encoding="utf-8"))["repo"], "my_repo")

    def test_status_before_anything_ran(self):
        status = json.loads(self.bench("status", str(self.repo)).stdout)
        self.assertEqual(status, {"adoption": None, "enabled": True, "kit_sessions": 0, "last_collect": None,
                                  "queue_left": 0, "sessions_measured": 0})
        self.assertFalse(self.out.exists())

    def test_status_after_adopt_and_collect(self):
        self.write_transcript()
        self.write_transcript(SID2, kit=False)
        self.bench("adopt", str(self.repo))
        self.collect()
        self.queue("pending", "{}")
        before = self.tree_bytes()
        proc = self.bench("status", str(self.repo))
        status = json.loads(proc.stdout)
        self.assertEqual(sorted(status), ["adoption", "enabled", "kit_sessions", "last_collect", "queue_left",
                                          "sessions_measured"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["adoption"], json.loads(before["adoption.json"]))
        self.assertEqual(status["sessions_measured"], 2)
        self.assertEqual(status["kit_sessions"], 1)
        self.assertEqual(status["queue_left"], 1)
        self.assertRegex(status["last_collect"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assert_no_absolute_paths(proc.stdout)
        self.assertEqual(self.tree_bytes(), before)

    def test_status_reads_bench_enabled_from_the_instance_config(self):
        config = self.instance / "config" / "project.json"
        config.write_text(json.dumps({"bench": {"enabled": False}}), encoding="utf-8")
        self.assertFalse(json.loads(self.bench("status", str(self.repo)).stdout)["enabled"])
        config.write_text(json.dumps({"review": {"enabled": True}}), encoding="utf-8")
        self.assertTrue(json.loads(self.bench("status", str(self.repo)).stdout)["enabled"])

    def test_status_reads_the_config_file_the_hooks_read(self):
        elsewhere = self.tmp / "elsewhere.json"
        elsewhere.write_text(json.dumps({"bench": {"enabled": False}}), encoding="utf-8")
        proc = subprocess.run(["bash", str(BENCH_SH), "status", str(self.repo), "--tools", str(self.instance)],
                              capture_output=True, text=True, env=self.env(METODO_PROJECT_CONFIG=str(elsewhere)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)["enabled"])


class ReportTests(BenchTestCase):
    def init_git(self):
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(git + ["init", "-q"], check=True, env=self.env())
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "feat: first"], check=True, env=self.env())

    def test_report_writes_the_phase1_report_and_prints_its_path(self):
        self.init_git()
        self.write_transcript()
        self.bench("adopt", str(self.repo))
        proc = self.bench("report", str(self.repo))
        md = self.out / "report" / "phase1-baseline.md"
        self.assertTrue(md.is_file())
        printed = proc.stdout.splitlines()
        self.assertEqual(len(printed), 1, proc.stdout)
        self.assertEqual(os.path.realpath(printed[0]), os.path.realpath(md))
        for name in ("sessions", "git", "kit", "adoption"):
            self.assertTrue((self.out / "data" / f"{name}.json").is_file(), name)
        self.assertEqual((self.out / "data" / "adoption.json").read_bytes(), (self.out / "adoption.json").read_bytes())
        report = json.loads((self.out / "report" / "phase1-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(report["sessions_total"], 1)
        self.assertEqual(report["inputs"]["adoption"]["status"], "ok")
        self.assertEqual(report["adoption"]["my_repo"]["label"], "Measured")
        self.assertEqual(report["adoption"]["my_repo"]["first_marker"], "install")
        self.assertEqual([r for r in report["git"]], ["my_repo"])
        text = md.read_text(encoding="utf-8")
        self.assertIn("| my_repo |", text)
        self.assertIn("| install |", text)
        self.assertNotIn("zebra", text)
        # the only absolute path printed is the report path itself
        self.assert_no_absolute_paths(proc.stdout.replace(printed[0], "") + proc.stderr)

    def test_report_without_an_adoption_record_keeps_the_inferred_boundary(self):
        self.init_git()
        self.write_transcript()
        (self.out / "data").mkdir(parents=True)
        (self.out / "data" / "adoption.json").write_text('{"installed_at": "2026-01-01T00:00:00.000Z", "repo": "my_repo"}')
        self.bench("report", str(self.repo))
        self.assertFalse((self.out / "data" / "adoption.json").exists())
        report = json.loads((self.out / "report" / "phase1-baseline.json").read_text(encoding="utf-8"))
        self.assertNotIn("adoption", report["inputs"])
        self.assertEqual(report["adoption"]["my_repo"]["label"], "Inferred")

    def test_report_exits_1_when_the_phase1_report_fails(self):
        self.init_git()
        self.write_transcript()
        (self.instance / "bench" / "lib" / "phase1_report.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        proc = self.bench("report", str(self.repo), check=False)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertIn("phase1_report failed", proc.stderr)


class AbAndUsageTests(BenchTestCase):
    def stub_cli(self):
        (self.instance / "bench" / "lib" / "bench_cli.py").write_text(CLI_STUB, encoding="utf-8")

    def test_ab_forwards_run_judge_and_report_to_the_instance_cli(self):
        self.stub_cli()
        cases = (
            (("run", "--config", "ab.json", "--dry-run"), ["ab", "--config", "ab.json", "--dry-run"]),
            (("judge", "--run", "runs/x"), ["judge", "--run", "runs/x"]),
            (("report", "--run", "runs/x", "--out", "o"), ["report", "--run", "runs/x", "--out", "o"]),
        )
        for args, forwarded in cases:
            proc = self.bench("ab", str(self.repo), *args, check=False)
            self.assertEqual(proc.returncode, 7, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout), forwarded)

    def test_ab_with_an_unknown_or_missing_word_is_a_usage_error(self):
        self.stub_cli()
        for args in (("session",), ("collect",), ()):
            proc = self.bench("ab", str(self.repo), *args, check=False)
            self.assertEqual(proc.returncode, 2, args)
            self.assertIn("usage", proc.stderr)
            self.assertEqual(proc.stdout, "")

    def test_ab_without_the_instance_cli_fails_with_exit_2(self):
        (self.instance / "bench" / "lib" / "bench_cli.py").unlink()
        proc = self.bench("ab", str(self.repo), "run", "--config", "ab.json", check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("bench/lib/bench_cli.py", proc.stderr)
        self.assertIn("sync-instance.sh", proc.stderr)

    def test_unknown_subcommand_missing_repo_or_bad_repo_is_a_usage_error(self):
        for args in (("nope", str(self.repo)), ("collect",), ("collect", str(self.repo), "extra"),
                     ("collect", str(self.tmp / "no-such-repo")), ("ab", str(self.tmp / "no-such-repo"), "run"),
                     ("collect", str(self.repo), "--tools")):
            proc = self.bench(*args, check=False, tools=args[-1] != "--tools")
            self.assertEqual(proc.returncode, 2, args)
            self.assertEqual(proc.stdout, "", args)
            self.assert_no_absolute_paths(proc.stderr)
        self.assertIn("usage", self.bench("collect", check=False).stderr)
        self.assertFalse(self.out.exists())

    def test_help_prints_the_usage_and_exits_zero(self):
        proc = self.bench("--help", tools=False)
        self.assertIn("usage: bench.sh collect|report|status|adopt <repo>", proc.stdout)
        self.assertIn("bench.sh ab <repo> <run|judge|report>", proc.stdout)


if __name__ == "__main__":
    unittest.main()
