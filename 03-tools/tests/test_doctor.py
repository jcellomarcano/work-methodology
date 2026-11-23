"""lib/doctor.py and bin/doctor.sh: the wiring doctor (kit-init T6, S5/S8/S10).

One throwaway git repo gets the whole kit (bin/install.sh --runtime all) in
setUpClass; every breakage works on its own copy of it, so each test proves
that exactly one missing piece turns its own check FAIL with a fix.

Non-git directory: the doctor does not refuse it as usage. It reports
repo.git FAIL (exit 1) and still emits the JSON, so the benchmark gets
evidence instead of a bare error. Exit 2 is reserved for a path that does
not exist or a bad flag.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import doctor as doctor_lib

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = TOOLS_ROOT / "lib" / "doctor.py"
DOCTOR_SH = TOOLS_ROOT / "bin" / "doctor.sh"
INSTALL = TOOLS_ROOT / "bin" / "install.sh"
ENV = dict(os.environ, METODO_MEMORY="off")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: the instance does not carry 01-roles/")
class DoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="doctor-"))
        cls.fixture = cls.tmp / "fixture"
        cls.fixture.mkdir()
        _git(cls.fixture, "init", "-q")
        (cls.fixture / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(cls.fixture, "add", "README.md")
        _git(cls.fixture, "commit", "-q", "-m", "init")
        proc = subprocess.run(["bash", str(INSTALL), str(cls.fixture), "--runtime", "all", "--tools", str(TOOLS_ROOT)],
                              capture_output=True, text=True, env=ENV)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout + proc.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # helpers
    def run_doctor(self, repo: Path, *extra: str):
        proc = subprocess.run(["python3", str(DOCTOR), str(repo), *extra], capture_output=True, text=True, env=ENV)
        report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
        return proc, report

    def copy_fixture(self, name: str) -> Path:
        """Copies the installed fixture and repoints the absolute repo path the
        installers baked in (.mcp.json, the pi extension), so the copy is as
        wired as the original and only the planted breakage differs."""
        dst = self.tmp / name
        shutil.copytree(self.fixture, dst, symlinks=True)
        old, new = str(self.fixture), str(dst)
        for rel in (".mcp.json", ".pi/extensions/metodo-hooks.ts"):
            path = dst / rel
            path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        return dst

    def check(self, report: dict, check_id: str) -> dict:
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertIn(check_id, by_id, sorted(by_id))
        return by_id[check_id]

    def assert_breaks(self, repo: Path, check_id: str):
        proc, report = self.run_doctor(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["kit_installed"])
        found = self.check(report, check_id)
        self.assertEqual(found["status"], "FAIL", found)
        self.assertTrue(found["fix"], found)
        return report

    # the happy path
    def test_fully_installed_repo_passes(self):
        proc, report = self.run_doctor(self.fixture)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(report["verdict"], "PASS")
        self.assertTrue(report["kit_installed"])
        self.assertEqual(report["runtime"], "all")
        ids = [c["id"] for c in report["checks"]]
        self.assertEqual(ids, sorted(ids))
        for expected in ("repo.git", "tools.layout", "tools.is_kit", "config.project", "config.base_ref",
                         "claude.agents", "claude.skills", "claude.mcp", "claude.hooks", "hooks.fire",
                         "git.exclude", "pi.agents", "pi.skills", "pi.mcp", "pi.extension", "memory.engram",
                         "vendor.tools", "baseline.latest", "personal.absent", "router.catalog",
                         "bench.wired", "bench.used"):
            self.assertIn(expected, ids)
        # benchmark-port S8: informative, never required, so a fresh install never fails on them
        self.assertNotIn("bench.wired", report["required"])
        self.assertNotIn("bench.used", report["required"])
        self.assertEqual(self.check(report, "bench.wired")["status"], "PASS")
        for c in report["checks"]:
            extra = {"counts"} if c["id"] == "bench.used" else set()
            self.assertEqual(set(c), {"id", "status", "detail", "fix"} | extra)
            self.assertIn(c["status"], {"PASS", "WARN", "FAIL", "SKIP"})
            if c["status"] == "PASS":
                self.assertIsNone(c["fix"], c)
        for key in ("schema_version", "tool_sha", "repo_sha", "repo_dirty"):
            self.assertIn(key, report)
        self.assertEqual(report["repo_sha"], _git(self.fixture, "rev-parse", "HEAD"))
        self.assertFalse(report["repo_dirty"])
        # the kit's own 03-tools carries the shared template, not an instance
        self.assertEqual(self.check(report, "tools.is_kit")["status"], "WARN")
        self.assertEqual(self.check(report, "memory.engram")["status"], "SKIP")
        self.assertEqual(self.check(report, "router.catalog")["status"], "PASS")

    def test_runtime_filter(self):
        _, claude = self.run_doctor(self.fixture, "--runtime", "claude")
        self.assertFalse([c for c in claude["checks"] if c["id"].startswith("pi.")])
        self.assertTrue(claude["kit_installed"])
        _, pi = self.run_doctor(self.fixture, "--runtime", "pi")
        self.assertFalse([c for c in pi["checks"] if c["id"].startswith("claude.")])
        self.assertTrue(pi["kit_installed"])
        self.assertEqual(pi["runtime"], "pi")

    # one breakage per rule
    def test_missing_agent_fails_claude_agents(self):
        repo = self.copy_fixture("no-agent")
        (repo / ".claude" / "agents" / "generic-judge.md").unlink()
        report = self.assert_breaks(repo, "claude.agents")
        self.assertIn("generic-judge.md", self.check(report, "claude.agents")["detail"])

    def test_unrendered_agent_token_fails_claude_agents(self):
        repo = self.copy_fixture("token-agent")
        agent = repo / ".claude" / "agents" / "generic-proposer.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\n__TOOLS_DEFAULT__/hooks\n", encoding="utf-8")
        self.assert_breaks(repo, "claude.agents")

    def test_missing_skill_fails_claude_skills(self):
        repo = self.copy_fixture("no-skill")
        shutil.rmtree(repo / ".claude" / "skills" / "cartography")
        report = self.assert_breaks(repo, "claude.skills")
        self.assertIn("cartography", self.check(report, "claude.skills")["detail"])

    def test_missing_pi_skill_fails_pi_skills(self):
        repo = self.copy_fixture("no-pi-skill")
        shutil.rmtree(repo / ".pi" / "skills" / "post-review-comment")
        self.assert_breaks(repo, "pi.skills")

    def test_missing_metodo_server_fails_mcp(self):
        repo = self.copy_fixture("no-mcp")
        mcp = repo / ".mcp.json"
        data = json.loads(mcp.read_text(encoding="utf-8"))
        del data["mcpServers"]["metodo"]
        mcp.write_text(json.dumps(data), encoding="utf-8")
        self.assert_breaks(repo, "claude.mcp")
        _, pi = self.run_doctor(repo, "--runtime", "pi")
        self.assertEqual(self.check(pi, "pi.mcp")["status"], "FAIL")

    def test_pi_mcp_passes_on_the_full_entry_and_warns_on_the_old_override_alone(self):
        _, pi = self.run_doctor(self.fixture, "--runtime", "pi")
        check = self.check(pi, "pi.mcp")
        self.assertEqual(check["status"], "PASS")
        self.assertIn("pi mcp list", check["detail"])
        repo = self.copy_fixture("pi-old-override")
        (repo / ".pi" / "mcp.json").write_text(json.dumps({"mcpServers": {"metodo": {"toolPrefix": "mcp"}}}), encoding="utf-8")
        _, old = self.run_doctor(repo, "--runtime", "pi")
        check = self.check(old, "pi.mcp")
        self.assertEqual(check["status"], "WARN")
        self.assertIn("built-in MCP", check["detail"])
        self.assertIn("--runtime pi", check["fix"])
        self.assertTrue(old["kit_installed"])

    def test_pi_mcp_fails_when_the_pi_copy_runs_another_server_path(self):
        repo = self.copy_fixture("pi-other-server")
        path = repo / ".pi" / "mcp.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["mcpServers"]["metodo"]["args"] = ["/nonexistent/old-instance/mcp/server.py"]
        path.write_text(json.dumps(data), encoding="utf-8")
        _, pi = self.run_doctor(repo, "--runtime", "pi")
        check = self.check(pi, "pi.mcp")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("another server path", check["detail"])

    def test_pi_extension_detail_says_when_pi_loads_it(self):
        _, pi = self.run_doctor(self.fixture, "--runtime", "pi")
        self.assertIn("--approve", self.check(pi, "pi.extension")["detail"])

    def test_moved_repo_without_reinstall_fails_mcp(self):
        # METODO_REPO still names the original repo: the server would serve the wrong one
        repo = self.tmp / "moved"
        shutil.copytree(self.fixture, repo, symlinks=True)
        self.assert_breaks(repo, "claude.mcp")

    def test_missing_marked_hook_fails_claude_hooks(self):
        repo = self.copy_fixture("no-hook")
        settings_path = repo / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        del settings["hooks"]["SessionStart"]
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        report = self.assert_breaks(repo, "claude.hooks")
        self.assertIn("SessionStart", self.check(report, "claude.hooks")["detail"])

    def test_missing_pi_extension_fails(self):
        repo = self.copy_fixture("no-ext")
        (repo / ".pi" / "extensions" / "metodo-hooks.ts").unlink()
        self.assert_breaks(repo, "pi.extension")

    def test_edited_pi_extension_fails(self):
        repo = self.copy_fixture("edited-ext")
        ext = repo / ".pi" / "extensions" / "metodo-hooks.ts"
        ext.write_text(ext.read_text(encoding="utf-8") + "\n// edited\n", encoding="utf-8")
        self.assert_breaks(repo, "pi.extension")

    def test_missing_mcp_exclude_fails(self):
        repo = self.copy_fixture("no-exclude")
        exclude = repo / ".git" / "info" / "exclude"
        exclude.write_text("".join(l for l in exclude.read_text(encoding="utf-8").splitlines(True)
                                   if l.strip() != ".mcp.json"), encoding="utf-8")
        self.assert_breaks(repo, "git.exclude")

    def test_personal_asset_fails(self):
        repo = self.copy_fixture("personal")
        (repo / ".claude" / "skills" / "personal").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "skills" / "personal" / "language.md").write_text("x\n", encoding="utf-8")
        (repo / ".pi" / "output-lint.personal.json").write_text("[]\n", encoding="utf-8")
        (repo / ".claude" / "skills" / "personal-notes.md").write_text("x\n", encoding="utf-8")
        report = self.assert_breaks(repo, "personal.absent")
        detail = self.check(report, "personal.absent")["detail"]
        self.assertIn(".claude/skills/personal", detail)
        self.assertNotIn(".claude/skills/personal/language.md", detail, "the outermost match covers its contents")
        self.assertIn(".pi/output-lint.personal.json", detail)
        # negative control: the word alone, outside the convention, is not personal
        self.assertNotIn("personal-notes.md", detail)

    # benchmark-port S8: bench.wired, bench.used, and claude.hooks leaving bench_queue.py to bench.wired
    def ctx(self, repo: Path, tools: Path, runtime: str = "all"):
        from lib import doctor
        return doctor, doctor.Ctx(repo, tools, runtime)

    def bench_tools(self, name: str, config: dict | None = None) -> Path:
        """A tools root with only what the bench checks read: the kit's hooks.settings.json
        (SessionEnd entry included) and, when given, a config/project.json."""
        tools = self.tmp / name
        (tools / "hooks").mkdir(parents=True)
        shutil.copyfile(TOOLS_ROOT / "hooks" / "hooks.settings.json", tools / "hooks" / "hooks.settings.json")
        if config is not None:
            (tools / "config").mkdir()
            (tools / "config" / "project.json").write_text(json.dumps(config), encoding="utf-8")
        return tools

    @staticmethod
    def kit_entries() -> list[dict]:
        hooks = json.loads((TOOLS_ROOT / "hooks" / "hooks.settings.json").read_text(encoding="utf-8"))["hooks"]
        return [entry for event in sorted(hooks) for entry in hooks[event]]

    @staticmethod
    def drop_session_end(repo: Path) -> Path:
        path = repo / ".claude" / "settings.local.json"
        settings = json.loads(path.read_text(encoding="utf-8"))
        del settings["hooks"]["SessionEnd"]
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path

    def test_claude_hooks_passes_without_the_bench_entry_and_bench_wired_warns(self):
        # a repo installed before the SessionEnd hook existed: wired for everything else
        repo = self.copy_fixture("no-bench-hook")
        self.drop_session_end(repo)
        doctor, ctx = self.ctx(repo, self.bench_tools("tools-bench-hook"))
        bench_entries = [e for e in self.kit_entries() if "bench_queue.py" in json.dumps(e)]
        self.assertEqual(len(bench_entries), 1)
        hooks = doctor.check_claude_hooks(ctx)
        self.assertEqual((hooks["status"], hooks["detail"]),
                         ("PASS", f"{len(self.kit_entries()) - 1} kit-marked hooks in .claude/settings.local.json"))
        for runtime in ("all", "claude"):
            wired = doctor.check_bench_wired(doctor.Ctx(repo, ctx.tools, runtime))
            self.assertEqual(wired["status"], "WARN", wired)
            self.assertIn("SessionEnd", wired["detail"])
            self.assertTrue(wired["fix"].startswith("re-run init: bin/init.sh <repo>"), wired)
        # never a required failure: the whole report still passes and the kit counts as installed
        proc, report = self.run_doctor(repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((report["verdict"], report["kit_installed"]), ("PASS", True))
        self.assertEqual(self.check(report, "claude.hooks")["status"], "PASS")
        self.assertEqual(self.check(report, "bench.wired")["status"], "WARN")

    def test_claude_hooks_reports_the_same_count_with_the_bench_entry_installed(self):
        doctor, ctx = self.ctx(self.fixture, TOOLS_ROOT)
        self.assertEqual(doctor.check_claude_hooks(ctx)["detail"],
                         f"{len(self.kit_entries()) - 1} kit-marked hooks in .claude/settings.local.json")

    def test_claude_hooks_still_fails_on_a_missing_kit_hook_next_to_the_bench_skip(self):
        repo = self.copy_fixture("no-stop-hook")
        path = self.drop_session_end(repo)
        settings = json.loads(path.read_text(encoding="utf-8"))
        del settings["hooks"]["Stop"]
        path.write_text(json.dumps(settings), encoding="utf-8")
        doctor, ctx = self.ctx(repo, self.bench_tools("tools-bench-stop"))
        result = doctor.check_claude_hooks(ctx)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("Stop", result["detail"])
        self.assertNotIn("SessionEnd", result["detail"])

    def test_bench_wired_passes_only_with_the_kit_marked_session_end_entry(self):
        repo = self.copy_fixture("bench-hook")
        doctor, ctx = self.ctx(repo, self.bench_tools("tools-bench-wired"))
        wired = doctor.check_bench_wired(ctx)
        self.assertEqual((wired["id"], wired["status"], wired["fix"]), ("bench.wired", "PASS", None), wired)
        self.assertIn("bench_queue.py", wired["detail"])
        path = repo / ".claude" / "settings.local.json"
        settings = json.loads(path.read_text(encoding="utf-8"))
        settings["hooks"]["SessionEnd"] = [{"matcher": "", "hooks": [{"type": "command", "command":
                                                                     'python3 "/t/hooks/bench_queue.py"'}]}]
        path.write_text(json.dumps(settings), encoding="utf-8")
        self.assertEqual(doctor.check_bench_wired(ctx)["status"], "WARN", "an unmarked hook is the owner's, not the kit's")

    def test_bench_wired_is_skipped_on_pi_and_agy_whatever_the_claude_settings_say(self):
        doctor, _ = self.ctx(self.fixture, TOOLS_ROOT)
        bare = self.copy_fixture("bench-bare")
        self.drop_session_end(bare)
        for runtime in ("pi", "agy"):
            for repo in (self.fixture, bare):
                wired = doctor.check_bench_wired(doctor.Ctx(repo, TOOLS_ROOT, runtime))
                self.assertEqual((wired["status"], wired["fix"]), ("SKIP", None), wired)
                self.assertIn(f"{runtime} sessions are not measured", wired["detail"])
        _, pi = self.run_doctor(self.fixture, "--runtime", "pi")
        self.assertEqual(self.check(pi, "bench.wired")["status"], "SKIP")
        self.assertEqual(self.check(pi, "bench.used")["status"], "SKIP")
        self.assertNotIn("bench.wired", pi["required"])
        self.assertNotIn("bench.used", pi["required"])

    def test_bench_wired_is_skipped_when_bench_is_disabled_in_the_config(self):
        tools = self.bench_tools("tools-bench-off", config={"bench": {"enabled": False}})
        doctor, ctx = self.ctx(self.fixture, tools)
        wired = doctor.check_bench_wired(ctx)
        self.assertEqual((wired["status"], wired["fix"]), ("SKIP", None), wired)
        self.assertIn("bench.enabled is false", wired["detail"])
        # when the runtime skip applies too, the runtime reason wins
        for runtime in ("pi", "agy"):
            for check in (doctor.check_bench_wired, doctor.check_bench_used):
                found = check(doctor.Ctx(self.fixture, tools, runtime))
                self.assertEqual((found["status"], found["detail"], found["fix"]),
                                 ("SKIP", f"Claude Code only: {runtime} sessions are not measured", None), found)

    def collector_enabled(self, tools: Path, config_override: Path | None = None) -> bool:
        """What the collector itself answers, asked the only way the kit reaches it: bin/bench.sh."""
        env = {k: v for k, v in ENV.items() if k not in ("METODO_PROJECT_CONFIG", "METODO_TOOLS")}
        if config_override is not None:
            env["METODO_PROJECT_CONFIG"] = str(config_override)
        proc = subprocess.run(["bash", str(TOOLS_ROOT / "bin" / "bench.sh"), "status", str(self.fixture), "--tools",
                               str(tools)], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["enabled"]

    def test_bench_enabled_is_read_the_way_the_collector_reads_it(self):
        cases = [None, {}, {"bench": {}}, {"bench": {"enabled": False}}, {"bench": {"enabled": True}},
                 {"bench": {"enabled": 0}}, {"bench": {"enabled": "no"}}, {"bench": False}, ["not", "an", "object"]]
        for index, config in enumerate(cases):
            tools = self.bench_tools(f"tools-enabled-{index}", config=config)
            doctor, ctx = self.ctx(self.fixture, tools)
            with mock.patch.dict(os.environ):
                os.environ.pop("METODO_PROJECT_CONFIG", None)
                self.assertIs(doctor.bench_enabled(ctx), self.collector_enabled(tools), config)
        (tools / "config" / "project.json").write_text("{not json", encoding="utf-8")
        with mock.patch.dict(os.environ):
            os.environ.pop("METODO_PROJECT_CONFIG", None)
            self.assertIs(doctor.bench_enabled(ctx), self.collector_enabled(tools))
        # the override every hook honors wins over the tools root's own file
        off = self.tmp / "override-off.json"
        off.write_text(json.dumps({"bench": {"enabled": False}}), encoding="utf-8")
        on_tools = self.bench_tools("tools-enabled-on", config={})
        doctor, ctx = self.ctx(self.fixture, on_tools)
        self.assertFalse(self.collector_enabled(on_tools, off))
        with mock.patch.dict(os.environ, {"METODO_PROJECT_CONFIG": str(off)}):
            self.assertFalse(doctor.bench_enabled(ctx))

    def test_bench_used_counts_each_module_for_this_repo_only(self):
        tools = self.bench_tools("tools-bench-used")
        rows = tools / "out" / "bench" / "sessions"
        rows.mkdir(parents=True)

        def row(sid, project, markers, weak, recall, save):
            record = {"session_id": sid, "project": project, "kit": {"markers": markers, "weak_markers": weak},
                      "engram": {"recall_calls": recall, "save_calls": save}, "first_prompt": "the secret word zebra"}
            (rows / f"{sid}.json").write_text(json.dumps(record), encoding="utf-8")

        row("s1", "fixture", ["hook:metodo", "mcp:metodo"], [], 1, 0)
        row("s2", "fixture", ["subagent:generic-judge"], ["skill:cartography"], 0, 0)
        row("s3", "fixture", [], [], 0, 2)
        row("s4", "other-repo", ["hook:metodo", "mcp:metodo", "subagent:generic-judge"], ["skill:x"], 3, 3)
        (rows / "broken.json").write_text("{not json", encoding="utf-8")
        (rows / "list.json").write_text("[]", encoding="utf-8")
        doctor, ctx = self.ctx(self.fixture, tools)
        used = doctor.check_bench_used(ctx)
        self.assertEqual(set(used), {"id", "status", "detail", "fix", "counts"})
        self.assertEqual((used["id"], used["status"], used["fix"]), ("bench.used", "PASS", None), used)
        self.assertEqual(used["counts"], {"sessions": 3, "hooks": 1, "agents": 1, "mcp": 1, "skills": 1, "engram": 2})
        for needle in ("3 sessions", "hooks 1", "agents 1", "mcp 1", "skills 1", "engram 2"):
            self.assertIn(needle, used["detail"])
        # counts only: nothing a row carries besides its markers reaches the report
        self.assertNotIn("zebra", json.dumps(used))
        self.assertNotIn(str(self.tmp), json.dumps(used))
        self.assertEqual(doctor.check_bench_used(doctor.Ctx(self.fixture, tools, "claude")), used)
        # pi and agy have no Claude Code install: SKIP whatever the rows say, and no warning nothing could clear
        zero = dict.fromkeys(("sessions", "hooks", "agents", "mcp", "skills", "engram"), 0)
        for runtime in ("pi", "agy"):
            for root in (tools, self.bench_tools(f"tools-bench-used-none-{runtime}")):
                self.assertEqual(doctor.check_bench_used(doctor.Ctx(self.fixture, root, runtime)),
                                 {"id": "bench.used", "status": "SKIP", "fix": None, "counts": zero,
                                  "detail": f"Claude Code only: {runtime} sessions are not measured"}, runtime)

    def test_bench_used_warns_with_the_collect_fix_when_nothing_is_measured(self):
        doctor, ctx = self.ctx(self.fixture, self.bench_tools("tools-bench-empty"))
        used = doctor.check_bench_used(ctx)
        self.assertEqual(used["status"], "WARN", used)
        self.assertEqual(used["fix"], "<tools>/bin/bench.sh collect <repo>")
        self.assertEqual(used["counts"], {"sessions": 0, "hooks": 0, "agents": 0, "mcp": 0, "skills": 0, "engram": 0})

    def test_bench_used_is_skipped_when_bench_is_off_and_no_row_of_this_repo_is_stored(self):
        zero = {"sessions": 0, "hooks": 0, "agents": 0, "mcp": 0, "skills": 0, "engram": 0}
        off = self.bench_tools("tools-bench-used-off", config={"bench": {"enabled": False}})
        rows = off / "out" / "bench" / "sessions"
        rows.mkdir(parents=True)
        other = {"session_id": "s9", "project": "other-repo", "kit": {"markers": ["hook:metodo"]}}
        (rows / "s9.json").write_text(json.dumps(other), encoding="utf-8")
        doctor, ctx = self.ctx(self.fixture, off)
        # nothing is measured and no command could clear a warning: SKIP, with no fix
        self.assertEqual(doctor.check_bench_used(ctx),
                         {"id": "bench.used", "status": "SKIP", "fix": None, "counts": zero,
                          "detail": "bench.enabled is false in <tools>/config/project.json: sessions are not measured, "
                                    "and no session of this repo is stored under <tools>/out/bench/sessions/"})
        # rows measured before the benchmark was turned off are still reported, as with the benchmark on
        mine = {"session_id": "s1", "project": "fixture", "kit": {"markers": ["hook:metodo"]}}
        (rows / "s1.json").write_text(json.dumps(mine), encoding="utf-8")
        on = self.bench_tools("tools-bench-used-on")
        shutil.copytree(rows, on / "out" / "bench" / "sessions")
        used = doctor.check_bench_used(ctx)
        self.assertEqual((used["status"], used["counts"]), ("PASS", dict(zero, sessions=1, hooks=1)), used)
        self.assertEqual(used, doctor.check_bench_used(doctor.Ctx(self.fixture, on, "all")))

    # non-git, usage
    def test_non_git_dir_reports_repo_git_fail(self):
        plain = self.tmp / "plain"
        plain.mkdir(exist_ok=True)
        proc, report = self.run_doctor(plain)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        repo_git = self.check(report, "repo.git")
        self.assertEqual(repo_git["status"], "FAIL")
        self.assertTrue(repo_git["fix"])
        self.assertIsNone(report["repo_sha"])
        self.assertFalse(report["kit_installed"])

    def test_usage_errors_exit_2(self):
        proc, _ = self.run_doctor(self.tmp / "does-not-exist")
        self.assertEqual(proc.returncode, 2)
        proc, _ = self.run_doctor(self.fixture, "--runtime", "vscode")
        self.assertEqual(proc.returncode, 2)

    # determinism and privacy of the evidence
    def test_two_runs_are_byte_identical(self):
        a, b = self.tmp / "a.json", self.tmp / "b.json"
        first, _ = self.run_doctor(self.fixture, "--out", str(a))
        second, _ = self.run_doctor(self.fixture, "--out", str(b))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(first.stdout, second.stdout)
        text = a.read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n")

    def test_no_absolute_paths_in_output(self):
        broken = self.copy_fixture("abs-check")
        (broken / ".claude" / "agents" / "generic-judge.md").unlink()
        for repo in (self.fixture, broken, self.tmp):
            proc, report = self.run_doctor(repo)
            text = proc.stdout
            for needle in (str(self.tmp), str(self.tmp.resolve()), str(TOOLS_ROOT), str(Path.home())):
                self.assertNotIn(needle, text)
            for s in _strings(report):
                self.assertFalse(s.startswith("/"), s)

    # tools root variants
    def test_tools_copy_without_git_and_broken_hook(self):
        tools = self.tmp / "tools-copy"
        shutil.copytree(TOOLS_ROOT, tools, ignore=shutil.ignore_patterns("out", "vendor", "baselines", "__pycache__", "*.pyc"))
        (tools / "hooks" / "guard_gates.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        config = json.loads((tools / "config" / "project.json").read_text(encoding="utf-8"))
        del config["property_order"]
        (tools / "config" / "project.json").write_text(json.dumps(config), encoding="utf-8")
        proc = subprocess.run(["bash", str(tools / "bin" / "doctor.sh"), str(self.fixture)],
                              capture_output=True, text=True, env=ENV)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("hooks.fire", proc.stdout)  # the human table
        default_out = tools / "out" / "doctor" / f"{_git(self.fixture, 'rev-parse', 'HEAD')}.json"
        self.assertTrue(default_out.exists(), proc.stdout + proc.stderr)
        report = json.loads(default_out.read_text(encoding="utf-8"))
        if subprocess.run(["git", "-C", str(tools), "rev-parse", "HEAD"], capture_output=True).returncode != 0:
            self.assertIsNone(report["tool_sha"])
            self.assertEqual(self.check(report, "tools.git")["status"], "WARN")
        self.assertEqual(self.check(report, "hooks.fire")["status"], "FAIL")
        self.assertEqual(self.check(report, "config.project")["status"], "FAIL")
        self.assertIn("property_order", self.check(report, "config.project")["detail"])
        self.assertEqual(self.check(report, "tools.is_kit")["status"], "PASS")
        for needle in (str(self.tmp), str(TOOLS_ROOT)):
            self.assertNotIn(needle, default_out.read_text(encoding="utf-8"))


class RouterCatalogCheckTests(unittest.TestCase):
    """router.catalog (model-router R9): the catalog parses, carries a version,
    every admitted model has a price at the catalog's own date (no clock), and
    the router returns ok for a canonical B5 review. In-process, no install."""

    def setUp(self):
        from lib import doctor
        self.doctor = doctor
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-router-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.catalog = json.loads((TOOLS_ROOT / "config" / "model-tiers.json").read_text(encoding="utf-8"))

    def _check(self, catalog_text: str | None) -> dict:
        tools = self.tmp / f"tools-{len(list(self.tmp.iterdir()))}"
        (tools / "config").mkdir(parents=True)
        if catalog_text is not None:
            (tools / "config" / "model-tiers.json").write_text(catalog_text, encoding="utf-8")
        return self.doctor.check_router_catalog(self.doctor.Ctx(self.tmp, tools, "all"))

    def test_kit_catalog_passes(self):
        found = self.doctor.check_router_catalog(self.doctor.Ctx(self.tmp, TOOLS_ROOT, "all"))
        self.assertEqual(found["status"], "PASS", found)
        self.assertIsNone(found["fix"])
        self.assertIn(self.catalog["version"], found["detail"])
        self.assertIn("B5", found["detail"])

    def test_broken_catalog_fails_with_a_fix(self):
        no_version = dict(self.catalog)
        del no_version["version"]
        no_price = json.loads(json.dumps(self.catalog))
        for entry in no_price["tiers"]["medium"]["candidates"]:
            if entry["status"] == "admitted":
                entry["price_schedule"] = [{"from": "2099-01-01", "usd_in": 1.0, "usd_out": 1.0}]
        no_admitted = json.loads(json.dumps(self.catalog))
        for entry in no_admitted["tiers"]["medium"]["candidates"]:
            entry["status"] = "candidate"
        cases = {"missing": None, "unparseable": "{not json", "no version": json.dumps(no_version),
                 "no price at the catalog date": json.dumps(no_price), "router not ok": json.dumps(no_admitted)}
        for name, text in cases.items():
            with self.subTest(case=name):
                found = self._check(text)
                self.assertEqual(found["status"], "FAIL", found)
                self.assertTrue(found["fix"])
                self.assertNotIn(str(self.tmp), found["detail"])
        # negative control: the same copy, unbroken, passes
        self.assertEqual(self._check(json.dumps(self.catalog))["status"], "PASS")


class DoctorRuntimeDetectionTests(unittest.TestCase):
    """Live probe 2026-11-13 (F5): `doctor.sh <repo> --tools <instance>`, the check
    AGENTS.md gives, read FAIL on four pi.* checks in a repo installed for Claude
    Code only. Without --runtime the doctor now checks what is installed."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="doctor-rt-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _repo(self, name: str, *runtimes: str) -> Path:
        repo = self.tmp / name
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-q", "-m", "init")
        for runtime in runtimes:
            proc = subprocess.run(["bash", str(INSTALL), str(repo), "--runtime", runtime, "--tools", str(TOOLS_ROOT)],
                                  capture_output=True, text=True, env=ENV)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return repo

    def _doctor(self, repo: Path, *extra: str):
        proc = subprocess.run(["python3", str(DOCTOR), str(repo), *extra], capture_output=True, text=True, env=ENV)
        return proc, json.loads(proc.stdout)

    def _prefixes(self, report: dict) -> set:
        return {c["id"].split(".")[0] for c in report["checks"]} & {"claude", "pi", "agy"}

    def test_a_claude_only_install_is_checked_as_claude(self):
        repo = self._repo("claude-only", "claude")
        proc, report = self._doctor(repo)
        self.assertEqual((report["runtime"], report["runtime_source"], report["also_installed"]), ("claude", "detected", []))
        self.assertEqual(self._prefixes(report), {"claude"})
        self.assertEqual([c["id"] for c in report["checks"] if c["status"] == "FAIL"], [])
        self.assertEqual(proc.returncode, 0)
        # the flag still decides when it is given: asking for all reads the missing pi wiring
        forced, all_report = self._doctor(repo, "--runtime", "all")
        self.assertEqual((all_report["runtime"], all_report["runtime_source"]), ("all", "flag"))
        self.assertIn("pi.extension", [c["id"] for c in all_report["checks"] if c["status"] == "FAIL"])
        self.assertEqual(forced.returncode, 1)

    def test_a_pi_only_install_is_checked_as_pi(self):
        _, report = self._doctor(self._repo("pi-only", "pi"))
        self.assertEqual((report["runtime"], report["runtime_source"]), ("pi", "detected"))
        self.assertEqual(self._prefixes(report), {"pi"})

    def test_claude_and_pi_together_are_checked_as_all(self):
        _, report = self._doctor(self._repo("both", "all"))
        self.assertEqual((report["runtime"], report["runtime_source"], report["also_installed"]), ("all", "detected", []))
        self.assertEqual(self._prefixes(report), {"claude", "pi"})

    def test_an_agy_only_install_is_checked_as_agy(self):
        _, report = self._doctor(self._repo("agy-only", "agy"))
        self.assertEqual((report["runtime"], report["runtime_source"]), ("agy", "detected"))
        self.assertEqual(self._prefixes(report), {"agy"})

    def test_agy_beside_claude_is_named_and_not_checked(self):
        repo = self._repo("claude-agy", "claude", "agy")
        _, report = self._doctor(repo)
        self.assertEqual((report["runtime"], report["also_installed"]), ("claude", ["agy"]))
        self.assertEqual(self._prefixes(report), {"claude"})
        table = subprocess.run(["python3", str(DOCTOR), str(repo), "--table"], capture_output=True, text=True, env=ENV).stdout
        self.assertIn("also installed, not checked here: agy (run again with --runtime agy)", table)

    def test_broken_claude_wiring_beside_pi_is_still_checked_and_fails(self):
        # verifier B2, 2026-11-13: a settings file that does not parse read as "claude not
        # installed", so the default doctor answered PASS for runtime pi
        for name, damage in (("broken-settings", lambda f: f.write_text('{"hooks": {"PreToolUse": [ BROKEN', encoding="utf-8")),
                             ("no-settings", lambda f: f.unlink()),
                             ("no-kit-hooks", lambda f: f.write_text("{}", encoding="utf-8"))):
            with self.subTest(name):
                repo = self._repo(name, "all")
                damage(repo / ".claude" / "settings.local.json")
                proc, report = self._doctor(repo)
                self.assertEqual((report["runtime"], report["runtime_source"]), ("all", "detected"))
                self.assertIn("claude.hooks", [c["id"] for c in report["checks"] if c["status"] == "FAIL"])
                self.assertEqual(proc.returncode, 1)

    def test_broken_pi_wiring_beside_claude_is_still_checked_and_fails(self):
        repo = self._repo("pi-unwired", "all")
        (repo / ".pi" / "extensions" / "metodo-hooks.ts").unlink()
        (repo / ".pi" / "mcp.json").unlink()
        proc, report = self._doctor(repo)
        self.assertEqual(report["runtime"], "all")
        self.assertIn("pi.extension", [c["id"] for c in report["checks"] if c["status"] == "FAIL"])
        self.assertEqual(proc.returncode, 1)

    def test_nothing_installed_still_checks_all_and_fails(self):
        proc, report = self._doctor(self._repo("empty"))
        self.assertEqual((report["runtime"], report["runtime_source"], report["also_installed"]), ("all", "default", []))
        self.assertEqual(self._prefixes(report), {"claude", "pi"})
        self.assertFalse(report["kit_installed"])
        self.assertEqual(proc.returncode, 1)


class AbsentSkillFilesTests(unittest.TestCase):
    """`--absent` looks for what the installers put in a repo; a skill's BUILD.json is never installed."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="doctor-absent-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.installed = self.repo / ".claude" / "skills" / "change-card"
        self.installed.mkdir(parents=True)

    def check(self) -> dict:
        return doctor_lib._absent_skills(self.repo, "claude.skills", ".claude/skills", "claude")

    def test_an_owners_build_file_is_not_a_kit_file_left_behind(self):
        self.assertTrue((TOOLS_ROOT.parent / "02-skills" / "change-card" / "BUILD.json").is_file())
        (self.installed / "BUILD.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.check()["status"], "PASS", self.check())

    def test_an_installed_skill_file_is_still_reported(self):  # previous behavior of --absent
        (self.installed / "BUILD.json").write_text("{}\n", encoding="utf-8")
        (self.installed / "SKILL.md").write_text("left behind\n", encoding="utf-8")
        check = self.check()
        self.assertEqual(check["status"], "FAIL", check)
        self.assertIn(".claude/skills/change-card/SKILL.md", check["detail"])
        self.assertNotIn("BUILD.json", check["detail"])


if __name__ == "__main__":
    unittest.main()
