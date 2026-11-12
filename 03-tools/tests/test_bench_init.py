"""bin/init.sh step `bench`, the flag --no-bench and the uninstall that keeps
<instance>/out/bench/ (benchmark-port S8, S10).

setUpClass initializes three throwaway Gradle/Kotlin repos, one per runtime
(claude twice, then unplugged; pi and agy once), with a fake HOME, stripped
METODO_* / GIT_* env, METODO_MEMORY=off, --no-fetch and --no-smoke. The
transcript root (CLAUDE_PROJECTS_DIR) is a folder of the fixture and holds one
synthetic Claude Code transcript, for the claude repo only. The step's other
states (no transcripts, --no-bench, bench.enabled false, a failing adopt, a
failing collect, a held lock, a session that cannot be measured) run
lib/init_kit.py's step on a copy of the claude instance, without a whole init.

The *_BEFORE tables pin what the init steps and the doctor checks reported
before the bench step and the bench checks existed, per runtime, with commit
ids and numbers normalized (they follow the kit's inventory, not this change).
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_bench_collect import SECRET_PROMPT, project_dir_name, transcript_records
from tests.test_init import InitBase, _git, _strings, tree_digest

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SID = "33333333-4444-5555-6666-777777777777"
RUNTIMES = ("claude", "pi", "agy")
STEP_ORDER = ["preflight", "instance", "adapt", "scaffolds", "fetch", "calibrate", "install", "baseline", "bench",
              "map", "doctor", "smoke", "suggestions"]
DONE_DETAIL = "adoption on file; history collected"
ADOPT_FIX = "<instance>/bin/bench.sh adopt <repo>"
# pi and agy have no Claude Code install: nothing to record, nothing a later command could measure
RUNTIME_SKIP = "runtime {runtime}: the measurement is Claude Code only, so no adoption timestamp is recorded and no " \
               "session is measured"
DOCTOR_RUNTIME_SKIP = "Claude Code only: {runtime} sessions are not measured"
COLLECT_FIX = "<instance>/bin/bench.sh collect <repo>"
# a failed subcommand that left no `bench: ...` line of its own: the exit code is all the detail keeps
NO_REASON = "exit {code} without a one-line reason"
# the collector's own line for a bench home it cannot write
FS_ERROR = "bench: {sub} stopped on a file system error (PermissionError); <instance>/out/bench must be a writable " \
           "directory"

# ---- what init and the doctor reported before this change (commit ids -> <sha>, digit runs -> N) ----

SMOKE_COMMAND = "METODO_PROJECT_CONFIG=<instance>/config/project.json python3 <kit>/lib/smoke_loop.py <repo>"
INSTALL_FILES = {"claude": ".claude/, .pi/, .mcp.json", "pi": ".claude/, .pi/, .mcp.json",
                 "agy": ".agents/plugins/metodo/"}
# (step, status, detail, fix); None marks the two details that depend on the machine or on the doctor's counts
STEPS_BEFORE = (
    ("preflight", None, None, None),
    ("instance", "done", "synced from <kit>; git repository with a HEAD (tool_sha is set); personal assets are "
                         "never synced", None),
    ("adapt", "done", "<instance>/config/project.json adapted to <repo> from detection; docs_root <audit>; "
                      "N decisions left to the owner", None),
    ("scaffolds", "done", "invariants.md, CONTEXT-PACK.md and CONVENTIONS.md.template present in <audit> (never "
                          "overwritten; CONVENTIONS template points to N-languages/kotlin.md)", None),
    ("fetch", "skipped", "--no-fetch; detekt not fetched, ktlint not fetched, pmd not fetched",
     "<instance>/bin/fetch-tools.sh"),
    ("calibrate", "skipped", "config/cpd.json is still the kit's uncalibrated copy: PMD is not fetched; no candidate "
                             "files in config/duplication-targets.json",
     "python3 <instance>/lib/duplication_cpd.py <repo> --calibrate"),
    ("install", "done", "kit installed in <repo> for runtime {runtime} with tools <instance> (local files only: "
                        "{files}, .git/info/exclude)", None),
    ("baseline", "done", "baseline for the repo HEAD saved under <instance>/baselines/ (latest points at a saved one)",
     None),
    ("map", "done", "first map at <instance>/out/<sha>/cartography.md; review by hand the boundary config it proposes",
     None),
    ("doctor", "done", None, None),
    ("smoke", "skipped", "--no-smoke: the loop was not proven", SMOKE_COMMAND),
    ("suggestions", "done", "N present, N missing, N unknown (nothing installed; global configs not read)", None),
)
PREFLIGHT_BEFORE = re.compile(r"^(done\|git repository at <sha>; pythonN and git present; optional tools present"
                              r"|warn\|optional tools missing: .+)$")
# the doctor step's counts before the two bench checks: PASS, WARN, FAIL, SKIP
DOCTOR_COUNTS_BEFORE = {"claude": (15, 1, 0, 1), "pi": (15, 1, 0, 1), "agy": (16, 1, 0, 1)}
MCP_DETAIL = "metodo server <tools>/mcp/server.py, selftest ok (N tools)"
CHECKS_BEFORE_COMMON = {
    "baseline.latest": ("PASS", "<tools>/baselines/latest present", None),
    "config.base_ref": ("PASS", "base_ref main resolves", None),
    "config.project": ("PASS", "required keys present", None),
    "hooks.fire": ("PASS", "guard_gates.py denied a synthetic git push --force", None),
    "memory.engram": ("SKIP", "memory disabled (METODO_MEMORY=off)", None),
    "repo.git": ("PASS", "git repository at <sha>", None),
    "router.catalog": ("PASS", "catalog N-N-N.rN as of N-N-N: BN probe ok (N roles)", None),
    "tools.git": ("PASS", "tools root at <sha>", None),
    "tools.is_kit": ("PASS", "tools root is a project instance", None),
    "tools.layout": ("PASS", "lib/, mcp/server.py, hooks/, schemas/, config/project.json present", None),
    "vendor.tools": ("WARN", "detekt file missing; ktlint file missing; pmd file missing", "bin/fetch-tools.sh"),
}
CHECKS_BEFORE = {
    "claude": {
        "claude.agents": ("PASS", "N agent files under .claude/agents/", None),
        "claude.hooks": ("PASS", "N kit-marked hooks in .claude/settings.local.json", None),
        "claude.mcp": ("PASS", MCP_DETAIL, None),
        "claude.skills": ("PASS", "N skills under .claude/skills/", None),
        "git.exclude": ("PASS", ".mcp.json is in info/exclude", None),
        "personal.absent": ("PASS", "no personal asset under .claude/ or .pi/", None),
    },
    "pi": {
        "git.exclude": ("PASS", ".mcp.json is in info/exclude", None),
        "personal.absent": ("PASS", "no personal asset under .claude/ or .pi/", None),
        "pi.agents": ("PASS", "N agent files under .pi/agents/", None),
        "pi.extension": ("PASS", ".pi/extensions/metodo-hooks.ts matches <tools>/hooks/pi/metodo-hooks.ts", None),
        "pi.mcp": ("PASS", MCP_DETAIL + ', toolPrefix "mcp"', None),
        "pi.skills": ("PASS", "N skills under .pi/skills/", None),
    },
    "agy": {
        "agy.agents": ("PASS", "N agent files under .agents/plugins/metodo/agents/", None),
        "agy.contracts": ("PASS", "N role contracts under .agents/plugins/metodo/contracts/ match the kit's", None),
        "agy.hooks": ("PASS", ".agents/plugins/metodo/hooks.json matches <tools>/hooks/agy/hooks.json", None),
        "agy.mcp": ("PASS", MCP_DETAIL + " (from .agents/plugins/metodo/mcp_config.json)", None),
        "agy.skills": ("PASS", "N skills under .agents/plugins/metodo/skills/", None),
        "git.exclude": ("PASS", ".agents/plugins/metodo is in info/exclude", None),
        "personal.absent": ("PASS", "no personal asset under .claude/, .pi/ or .agents/", None),
    },
}
REQUIRED_ALWAYS = ["config.project", "git.exclude", "hooks.fire", "personal.absent", "repo.git", "tools.layout"]
REQUIRED_BEFORE = {
    "claude": ["claude.agents", "claude.hooks", "claude.mcp", "claude.skills"],
    "pi": ["pi.agents", "pi.extension", "pi.mcp", "pi.skills"],
    "agy": ["agy.agents", "agy.contracts", "agy.hooks", "agy.mcp", "agy.skills"],
}


def norm(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"\d+", "N", re.sub(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{12}\b", "<sha>", value))


def kit_hook_entries_without_bench() -> int:
    hooks = json.loads((TOOLS_ROOT / "hooks" / "hooks.settings.json").read_text(encoding="utf-8"))["hooks"]
    entries = [entry for event in hooks.values() for entry in event]
    return len([e for e in entries if "bench_queue.py" not in json.dumps(e)])


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: init runs from the kit")
class BenchInitRunTests(InitBase):
    """Three initialized repos, one per runtime; only the claude one has a transcript."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="bench-init-"))
        cls.env = cls.make_env(cls.tmp)
        cls.transcripts = cls.tmp / "projects"
        cls.env.update(CLAUDE_PROJECTS_DIR=str(cls.transcripts), METODO_BENCH_NO_SPAWN="1")
        cls.repos, cls.instances, cls.audits, cls.procs, cls.reports, cls.doctors, cls.shas = {}, {}, {}, {}, {}, {}, {}
        for runtime in RUNTIMES:
            cls.repos[runtime] = cls.make_repo(cls.tmp / f"work-{runtime}" / "fixture", cls.env)
            cls.instances[runtime] = cls.tmp / f"inst-{runtime}"
            cls.audits[runtime] = cls.tmp / f"audit-{runtime}"
            cls.shas[runtime] = _git(cls.repos[runtime], "rev-parse", "HEAD", env=cls.env)
        cls.repo, cls.instance, cls.sha = cls.repos["claude"], cls.instances["claude"], cls.shas["claude"]
        tdir = cls.transcripts / project_dir_name(cls.repo)
        tdir.mkdir(parents=True)
        lines = [json.dumps(r) for r in transcript_records(SID, os.path.realpath(cls.repo), True)]
        (tdir / f"{SID}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        cls.transcripts_before = tree_digest(cls.transcripts, skip_top=())
        for runtime in RUNTIMES:
            cls.procs[runtime] = cls.init(runtime)
            cls.reports[runtime] = cls.read_json(cls.instances[runtime] / "out" / "init" / f"{cls.shas[runtime]}.json")
            cls.doctors[runtime] = cls.read_json(cls.instances[runtime] / "out" / "doctor" / f"{cls.shas[runtime]}.json")
        report_path = cls.instance / "out" / "init" / f"{cls.sha}.json"
        cls.report_bytes1 = report_path.read_bytes() if report_path.exists() else b""
        cls.adoption = cls.instance / "out" / "bench" / "adoption.json"
        cls.row = cls.instance / "out" / "bench" / "sessions" / f"{SID}.json"
        cls.adoption1 = cls.adoption.read_bytes() if cls.adoption.exists() else b""
        cls.row_exists1 = cls.row.is_file()
        cls.proc2 = cls.init("claude")
        cls.report_bytes2 = report_path.read_bytes() if report_path.exists() else b""
        cls.adoption2 = cls.adoption.read_bytes() if cls.adoption.exists() else b""
        # snapshot for the step-level tests, before the uninstall below
        cls.snapshot = cls.tmp / "snapshot"
        shutil.copytree(cls.instance, cls.snapshot, symlinks=True,
                        ignore=shutil.ignore_patterns("out", "baselines", "vendor", ".git"))
        bench_home = cls.instance / "out" / "bench"
        cls.bench_before_uninstall = tree_digest(bench_home, skip_top=()) if bench_home.is_dir() else {}
        cls.proc_un = cls.init("claude", "--uninstall", no_smoke=False)
        cls.bench_after_uninstall = tree_digest(bench_home, skip_top=()) if bench_home.is_dir() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def init(cls, runtime: str, *extra: str, no_smoke: bool = True) -> subprocess.CompletedProcess:
        flags = ("--no-smoke",) if no_smoke else ()
        return cls.run_init(cls.repos[runtime], cls.instances[runtime], cls.audits[runtime], cls.env,
                            "--runtime", runtime, *flags, *extra)

    @staticmethod
    def read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"steps": [], "checks": []}

    def step(self, runtime: str, name: str) -> dict:
        by_name = {s["step"]: s for s in self.reports[runtime]["steps"]}
        self.assertIn(name, by_name, sorted(by_name))
        return by_name[name]

    def doctor_check(self, runtime: str, check_id: str) -> dict:
        by_id = {c["id"]: c for c in self.doctors[runtime]["checks"]}
        self.assertIn(check_id, by_id, sorted(by_id))
        return by_id[check_id]

    def test_bench_step_runs_right_after_baseline_on_every_runtime(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                self.assertEqual([s["step"] for s in self.reports[runtime]["steps"]], STEP_ORDER)

    def test_bench_step_is_done_with_a_deterministic_detail(self):
        self.assertEqual(self.step("claude", "bench"),
                         {"step": "bench", "status": "done", "detail": DONE_DETAIL, "fix": None})
        self.assertTrue(self.row_exists1, "collect measured the existing transcript")

    def test_report_is_byte_identical_across_two_runs(self):
        self.assertTrue(self.report_bytes1)
        self.assertEqual(self.report_bytes1, self.report_bytes2)
        self.assertIn("bench adopt: recorded", self.procs["claude"].stderr)
        self.assertIn("bench adopt: kept", self.proc2.stderr)

    def test_adoption_is_recorded_once_and_kept_on_rerun(self):
        self.assertTrue(self.adoption1)
        adoption = json.loads(self.adoption1)
        self.assertEqual(adoption["label"], "Measured")
        self.assertEqual(adoption["repo"], "fixture")
        self.assertEqual(self.adoption1, self.adoption2)

    def test_exit_code_and_ready_rule_are_what_the_doctor_and_the_smoke_decide(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                proc, report = self.procs[runtime], self.reports[runtime]
                self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
                self.assertEqual(report["doctor"]["verdict"], "PASS")
                self.assertTrue(report["doctor"]["kit_installed"])
                # --no-smoke: the loop did not run, so the report is not ready whatever the bench step did
                self.assertFalse(report["ready_for_benchmark"])

    def test_pi_and_agy_skip_the_step_and_both_bench_checks(self):
        for runtime in ("pi", "agy"):
            with self.subTest(runtime=runtime):
                self.assertEqual(self.step(runtime, "bench"), {"step": "bench", "status": "skipped", "fix": None,
                                                               "detail": RUNTIME_SKIP.format(runtime=runtime)})
                self.assertFalse((self.instances[runtime] / "out" / "bench").exists(), "no adopt, no collect")
                for check_id in ("bench.wired", "bench.used"):
                    check = self.doctor_check(runtime, check_id)
                    self.assertEqual((check["status"], check["detail"], check["fix"]),
                                     ("SKIP", DOCTOR_RUNTIME_SKIP.format(runtime=runtime), None), check)
                self.assertNotIn("warn", {s["status"] for s in self.reports[runtime]["steps"] if s["step"] == "bench"})

    def test_claude_doctor_reports_the_hook_wired_and_the_session_used(self):
        self.assertEqual(self.doctor_check("claude", "bench.wired")["status"], "PASS")
        used = self.doctor_check("claude", "bench.used")
        self.assertEqual(used["status"], "PASS", used)
        self.assertEqual(used["counts"], {"sessions": 1, "hooks": 0, "agents": 0, "mcp": 1, "skills": 0, "engram": 0})

    def test_init_writes_nothing_outside_the_instance_and_the_audit(self):
        self.assertEqual(sorted(p.name for p in Path(self.env["HOME"]).iterdir()), [])
        self.assertEqual(tree_digest(self.transcripts, skip_top=()), self.transcripts_before)
        for runtime in RUNTIMES:
            for s in _strings(self.reports[runtime]):
                self.assertNotIn(str(self.tmp), s)
                self.assertNotIn(SECRET_PROMPT, s)

    def test_uninstall_keeps_out_bench(self):
        self.assertEqual(self.proc_un.returncode, 0, self.proc_un.stdout[-2000:] + self.proc_un.stderr[-2000:])
        self.assertFalse((self.repo / ".claude").exists())
        self.assertTrue(self.bench_before_uninstall)
        self.assertEqual(self.bench_after_uninstall, self.bench_before_uninstall)
        self.assertEqual(self.adoption.read_bytes(), self.adoption1)
        self.assertTrue(self.row.is_file())

    # ---- the step's other states, on a copy of the claude instance ----

    def copy_instance(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="step-", dir=self.tmp))
        shutil.copytree(self.snapshot, root / "inst", symlinks=True)
        return root / "inst"

    def run_step(self, instance: Path, *flags: str, transcripts: Path | None = None) -> dict:
        from lib import init_kit
        args = init_kit.build_parser().parse_args([str(self.repo), "--instance", str(instance), *flags])
        init = init_kit.Init(args)
        init.repo, init.instance, init.repo_sha = Path(os.path.realpath(self.repo)), instance, self.sha
        env = {"CLAUDE_PROJECTS_DIR": str(transcripts or (instance.parent / "no-transcripts")),
               "HOME": self.env["HOME"], "METODO_BENCH_NO_SPAWN": "1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(init_kit, "say", lambda *a, **k: None):
            init.step_bench()
        self.assertEqual(len(init.steps), 1, init.steps)
        self.assertEqual(init.steps[0]["step"], "bench")
        return init.steps[0]

    def test_warn_when_no_transcripts_exist_yet(self):
        instance = self.copy_instance()
        entry = self.run_step(instance)
        self.assertEqual((entry["status"], entry["fix"]), ("warn", COLLECT_FIX), entry)
        self.assertIn("no Claude Code transcripts for <repo>", entry["detail"])
        self.assertTrue((instance / "out" / "bench" / "adoption.json").is_file())
        self.assertEqual(self.run_step(instance), entry)

    def test_done_on_a_copy_with_transcripts_and_the_same_detail_on_a_second_run(self):
        instance = self.copy_instance()
        outside = tree_digest(self.repo, skip_top=())
        entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["detail"], entry["fix"]), ("done", DONE_DETAIL, None))
        self.assertEqual(self.run_step(instance, transcripts=self.transcripts), entry)
        # only <instance>/out/bench/ is written: not the repo, not the transcripts, nothing else in the instance
        self.assertEqual(tree_digest(self.repo, skip_top=()), outside)
        self.assertEqual(tree_digest(self.transcripts, skip_top=()), self.transcripts_before)
        added = set(tree_digest(instance, skip_top=())) - set(tree_digest(self.snapshot, skip_top=()))
        self.assertTrue(added)
        self.assertEqual({p for p in added if not p.startswith("out/bench/")}, set())

    def test_no_bench_flag_skips_the_step(self):
        instance = self.copy_instance()
        entry = self.run_step(instance, "--no-bench", transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("skipped", ADOPT_FIX), entry)
        self.assertIn("--no-bench", entry["detail"])
        self.assertFalse((instance / "out").exists(), "no adoption timestamp, nothing collected")

    def test_the_runtime_skip_wins_over_no_bench_and_over_bench_disabled(self):
        for runtime in ("pi", "agy"):
            expected = {"step": "bench", "status": "skipped", "detail": RUNTIME_SKIP.format(runtime=runtime), "fix": None}
            with self.subTest(runtime=runtime):
                instance = self.copy_instance()
                self.assertEqual(self.run_step(instance, "--runtime", runtime, transcripts=self.transcripts), expected)
                self.assertEqual(self.run_step(instance, "--runtime", runtime, "--no-bench",
                                               transcripts=self.transcripts), expected)
                path = instance / "config" / "project.json"
                config = json.loads(path.read_text(encoding="utf-8"))
                config["bench"] = {"enabled": False}
                path.write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(self.run_step(instance, "--runtime", runtime, transcripts=self.transcripts), expected)
                self.assertFalse((instance / "out").exists(), "no adopt and no collect ran")

    def test_bench_disabled_in_the_config_skips_the_step(self):
        instance = self.copy_instance()
        path = instance / "config" / "project.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["bench"] = {"enabled": False}
        path.write_text(json.dumps(config), encoding="utf-8")
        entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("skipped", None), entry)
        self.assertIn("bench.enabled is false", entry["detail"])
        self.assertFalse((instance / "out" / "bench").exists())

    def test_fail_only_when_the_adoption_cannot_be_recorded(self):
        instance = self.copy_instance()
        (instance / "out").write_text("not a directory\n", encoding="utf-8")
        entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("fail", ADOPT_FIX), entry)
        self.assertIn("bench.sh adopt failed: ", entry["detail"])

    def stub_bench(self, instance: Path, failing: str) -> None:
        """Replace the copy's bin/bench.sh with one whose `failing` subcommand dies the way an uncaught
        error does: a traceback whose last line names a temp file after the process id."""
        script = ("#!/usr/bin/env bash\n"
                  'case "$1" in\n'
                  "  status) echo '{\"enabled\": true}'; exit 0 ;;\n"
                  f'  {failing}) echo "Traceback (most recent call last):" >&2\n'
                  '    echo "PermissionError: [Errno 13] Permission denied: \'/abs/out/bench/.adoption.$$.tmp\'" >&2\n'
                  "    exit 1 ;;\n"
                  "  adopt) echo kept; exit 0 ;;\n"
                  "esac\n")
        (instance / "bin" / "bench.sh").write_text(script, encoding="utf-8")

    def unwritable_bench_home(self, instance: Path, adoption: bool = False) -> None:
        home = instance / "out" / "bench"
        home.mkdir(parents=True)
        if adoption:
            (home / "adoption.json").write_text("{}\n", encoding="utf-8")
        home.chmod(0o555)
        self.addCleanup(home.chmod, 0o755)  # so the fixture can be removed

    def assert_stable_detail(self, detail: str):
        for needle in (str(self.tmp), os.path.realpath(self.tmp), ".tmp", "Errno", "Traceback"):
            self.assertNotIn(needle, detail)

    def test_a_failure_detail_is_the_same_bytes_whatever_the_failed_command_printed(self):
        expected = {"adopt": ("fail", ADOPT_FIX, "bench.sh adopt failed: " + NO_REASON.format(code=1)),
                    "collect": ("warn", COLLECT_FIX, "adoption on file; bench.sh collect failed: "
                                + NO_REASON.format(code=1))}
        for sub in ("adopt", "collect"):
            with self.subTest(sub=sub):
                instance = self.copy_instance()
                self.stub_bench(instance, sub)
                first = self.run_step(instance, transcripts=self.transcripts)
                self.assertEqual((first["status"], first["fix"], first["detail"]), expected[sub])
                self.assertEqual(self.run_step(instance, transcripts=self.transcripts), first)

    @unittest.skipIf(os.geteuid() == 0, "root writes through a read-only directory")
    def test_an_unwritable_bench_home_is_the_same_fail_detail_on_every_run(self):
        instance = self.copy_instance()
        self.unwritable_bench_home(instance)
        first = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((first["status"], first["fix"]), ("fail", ADOPT_FIX), first)
        self.assertEqual(first["detail"], "bench.sh adopt failed: " + FS_ERROR.format(sub="adopt"))
        self.assert_stable_detail(first["detail"])
        self.assertEqual(self.run_step(instance, transcripts=self.transcripts), first)

    @unittest.skipIf(os.geteuid() == 0, "root writes through a read-only directory")
    def test_an_unwritable_bench_home_is_the_same_warn_detail_on_every_run(self):
        instance = self.copy_instance()
        self.unwritable_bench_home(instance, adoption=True)
        first = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((first["status"], first["fix"]), ("warn", COLLECT_FIX), first)
        self.assertEqual(first["detail"], "adoption on file; bench.sh collect failed: " + FS_ERROR.format(sub="collect"))
        self.assert_stable_detail(first["detail"])
        self.assertEqual(self.run_step(instance, transcripts=self.transcripts), first)

    def test_a_collector_error_is_a_warn_that_names_the_reason(self):
        instance = self.copy_instance()
        (instance / "bench" / "lib" / "transcript_metrics.py").unlink()
        entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("warn", COLLECT_FIX), entry)
        self.assertIn("adoption on file; bench.sh collect failed: ", entry["detail"])
        self.assertIn("bench/lib/transcript_metrics.py", entry["detail"])
        self.assertTrue((instance / "out" / "bench" / "adoption.json").is_file())

    def test_a_held_lock_is_a_warn(self):
        instance = self.copy_instance()
        (instance / "out" / "bench").mkdir(parents=True)
        with open(instance / "out" / "bench" / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("warn", COLLECT_FIX), entry)
        self.assertIn("another collect held the lock", entry["detail"])

    def test_a_session_that_cannot_be_measured_is_a_warn_without_a_count(self):
        instance = self.copy_instance()
        queue = instance / "out" / "bench" / "queue"
        queue.mkdir(parents=True)
        (queue / "broken.json").write_text("{not json", encoding="utf-8")
        entry = self.run_step(instance, transcripts=self.transcripts)
        self.assertEqual((entry["status"], entry["fix"]), ("warn", COLLECT_FIX), entry)
        self.assertIn("could not be measured", entry["detail"])
        self.assertIsNone(re.search(r"\d", entry["detail"]), entry["detail"])


    # ---- every init step and doctor check that existed before keeps its id, order, status, detail and fix ----

    def test_existing_init_steps_keep_id_order_status_detail_and_fix(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                steps = [s for s in self.reports[runtime]["steps"] if s["step"] != "bench"]
                self.assertEqual([s["step"] for s in steps], [s[0] for s in STEPS_BEFORE])
                for step, (name, status, detail, fix) in zip(steps, STEPS_BEFORE):
                    if name == "preflight":  # depends on the machine's PATH (java, node, the runtime's CLI)
                        self.assertRegex(f"{step['status']}|{norm(step['detail'])}", PREFLIGHT_BEFORE)
                        continue
                    if name == "doctor":  # the counts, checked below against the report they summarize
                        self.assertEqual((step["status"], step["fix"]), (status, fix), step)
                        continue
                    detail = detail.format(runtime=runtime, files=INSTALL_FILES[runtime])
                    self.assertEqual((step["status"], norm(step["detail"]), norm(step["fix"])),
                                     (status, norm(detail), norm(fix)), name)

    def test_the_doctor_step_counts_grow_only_by_the_two_bench_checks(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                match = re.fullmatch(r"verdict PASS, kit_installed true \(PASS (\d+), WARN (\d+), FAIL (\d+), SKIP (\d+)\)",
                                     self.step(runtime, "doctor")["detail"])
                self.assertIsNotNone(match, self.step(runtime, "doctor"))
                counts = dict(zip(("PASS", "WARN", "FAIL", "SKIP"), map(int, match.groups())))
                for check_id in ("bench.wired", "bench.used"):
                    counts[self.doctor_check(runtime, check_id)["status"]] -= 1
                self.assertEqual(tuple(counts[s] for s in ("PASS", "WARN", "FAIL", "SKIP")), DOCTOR_COUNTS_BEFORE[runtime])

    def test_existing_doctor_checks_keep_id_order_status_detail_and_fix(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                report = self.doctors[runtime]
                before = dict(CHECKS_BEFORE_COMMON, **CHECKS_BEFORE[runtime])
                existing = [c for c in report["checks"] if not c["id"].startswith("bench.")]
                self.assertEqual([c["id"] for c in existing], sorted(before))
                for check in existing:
                    self.assertEqual(set(check), {"id", "status", "detail", "fix"}, check)
                    status, detail, fix = before[check["id"]]
                    self.assertEqual((check["status"], norm(check["detail"]), norm(check["fix"])),
                                     (status, norm(detail), norm(fix)), check["id"])
                self.assertEqual(report["required"], sorted(REQUIRED_ALWAYS + REQUIRED_BEFORE[runtime]))
                self.assertEqual(report["verdict"], "PASS")
                self.assertEqual([c["id"] for c in report["checks"] if c["id"].startswith("bench.")],
                                 ["bench.used", "bench.wired"])

    def test_claude_hooks_counts_the_entries_the_kit_had_before_the_bench_hook(self):
        expected = f"{kit_hook_entries_without_bench()} kit-marked hooks in .claude/settings.local.json"
        self.assertEqual(self.doctor_check("claude", "claude.hooks")["detail"], expected)


class BenchInitPlanTests(InitBase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-init-plan-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = self.make_env(self.tmp)

    def test_dry_run_lists_the_bench_step_and_no_bench_skips_it(self):
        repo = self.make_repo(self.tmp / "repo", self.env)
        proc = self.run_init(repo, self.tmp / "inst", self.tmp / "audit", self.env, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        names = [re.match(r"\s+\d+\. (\w+):", line).group(1) for line in lines if re.match(r"\s+\d+\. \w+:", line)]
        self.assertEqual(names, STEP_ORDER + ["report"])
        bench = next(line for line in lines if re.match(r"\s+\d+\. bench:", line))
        self.assertIn("bin/bench.sh adopt", bench)
        self.assertIn("bin/bench.sh collect", bench)
        proc = self.run_init(repo, self.tmp / "inst", self.tmp / "audit", self.env, "--dry-run", "--no-bench")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        bench = next(line for line in proc.stdout.splitlines() if re.match(r"\s+\d+\. bench:", line))
        self.assertIn("skipped (--no-bench)", bench)
        for runtime in ("pi", "agy"):
            for flags in ((), ("--no-bench",)):
                proc = self.run_init(repo, self.tmp / "inst", self.tmp / "audit", self.env, "--dry-run", "--runtime",
                                     runtime, *flags)
                bench = next(line for line in proc.stdout.splitlines() if re.match(r"\s+\d+\. bench:", line))
                self.assertTrue(bench.endswith(f"bench: skipped (runtime {runtime}: Claude Code only)"), bench)
        self.assertFalse((self.tmp / "inst").exists())

    def test_usage_text_names_the_flag(self):
        proc = subprocess.run(["bash", str(TOOLS_ROOT / "bin" / "init.sh")], capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--no-bench", proc.stderr)

    @unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: init runs from the kit")
    def test_a_bench_step_that_fails_never_fails_the_init(self):
        repo = self.make_repo(self.tmp / "repo", self.env)
        instance = self.tmp / "inst"
        (instance / "out").mkdir(parents=True)
        (instance / "out" / "bench").write_text("in the way\n", encoding="utf-8")
        proc = self.run_init(repo, instance, self.tmp / "audit", self.env, "--runtime", "claude", "--no-smoke")
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        report = json.loads(proc.stdout)
        steps = {s["step"]: s for s in report["steps"]}
        self.assertEqual([s["step"] for s in report["steps"]], STEP_ORDER)
        self.assertEqual((steps["bench"]["status"], steps["bench"]["fix"]), ("fail", ADOPT_FIX), steps["bench"])
        self.assertEqual(steps["doctor"]["status"], "done", steps["doctor"])
        self.assertEqual(report["doctor"]["verdict"], "PASS")
        for s in _strings(report):
            self.assertNotIn(str(self.tmp), s)


if __name__ == "__main__":
    unittest.main()
