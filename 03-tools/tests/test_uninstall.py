"""Unplug on demand (kit-init T13, S13, S8, S9): bin/install.sh --uninstall,
install-claude.sh / install-pi.sh --uninstall, lib/doctor.py --absent and
bin/init.sh --uninstall [--purge] [--dry-run].

Every case works on throwaway repos under a temporary HOME with an isolated
git config and METODO_MEMORY=off. The installers remove only what is
byte-identical to what this kit renders for the repo; anything else (a
modified kit file, the owner's own hook, server, agent, skill, permission or
exclude line) stays, and the doctor's absence mode says what is left.
"""
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
KIT_ROOT = TOOLS_ROOT.parent
INSTALL = TOOLS_ROOT / "bin" / "install.sh"
INIT_SH = TOOLS_ROOT / "bin" / "init.sh"
DOCTOR = TOOLS_ROOT / "lib" / "doctor.py"
DOCTOR_SH = TOOLS_ROOT / "bin" / "doctor.sh"
PERSONAL = (".personal.", "/personal/", "bench/tmp")
ITEM_RE = re.compile(r"^  ([-!.=]) (\S+) \((removed|not found|kept: [^)]+)\)$")

OWNER_HOOK = {"matcher": "Edit", "hooks": [{"type": "command", "command": "./my-own-hook.sh"}]}
OWNER_SETTINGS = {"permissions": {"allow": ["Bash(git status)", "Read(//x/**)"], "deny": []},
                  "hooks": {"PreToolUse": [OWNER_HOOK]}}
OWNER_MCP = {"mcpServers": {"github": {"type": "http", "url": "https://example.invalid/mcp"}}}
OWNER_PI_MCP = {"mcpServers": {"github": {"toolPrefix": "gh"}}, "settings": {"x": 1}}
OWNER_FILES = {
    ".claude/settings.local.json": json.dumps(OWNER_SETTINGS, indent=2) + "\n",
    ".mcp.json": json.dumps(OWNER_MCP, indent=2) + "\n",
    ".claude/agents/owner-agent.md": "---\nname: owner-agent\n---\nmine\n",
    # generic-* but not one of the kit's: never touched
    ".claude/agents/generic-owner.md": "---\nname: generic-owner\n---\nmine too\n",
    ".claude/skills/owner-skill/SKILL.md": "---\nname: owner-skill\n---\nmine\n",
    ".pi/agents/owner-pi.md": "---\nname: owner-pi\n---\nmine\n",
    ".pi/skills/owner-skill/SKILL.md": "---\nname: owner-skill\n---\nmine\n",
    ".pi/mcp.json": json.dumps(OWNER_PI_MCP, indent=2) + "\n",
}
OWNER_EXCLUDE_LINES = ["*.log", ".idea/"]


def make_env(root: Path) -> dict:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    gitconfig = root / "gitconfig"
    gitconfig.write_text("[user]\n\temail = t@example.com\n\tname = t\n[commit]\n\tgpgsign = false\n"
                         "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("METODO_", "GIT_"))}
    env.update(HOME=str(home), METODO_MEMORY="off", GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
    return env


def git(cwd: Path, env, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def make_repo(path: Path, env, gradle: bool = False) -> Path:
    path.mkdir(parents=True)
    git(path, env, "init", "-q", "-b", "main")
    if gradle:
        (path / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(path, env, "add", "-A")
    git(path, env, "commit", "-q", "-m", "initial")
    return path


def add_owner_assets(repo: Path) -> None:
    for rel, text in OWNER_FILES.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    exclude = repo / ".git" / "info" / "exclude"
    with open(exclude, "a", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in OWNER_EXCLUDE_LINES))


def snapshot(root: Path) -> dict:
    """rel path -> sha256 for every file and 'dir' for every directory under
    root; .git reduced to info/exclude and HEAD."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d != ".git"]
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for d in dirnames:
            result[(rel_dir / d).as_posix() + "/"] = "dir"
        for name in filenames:
            path = Path(dirpath) / name
            result[(rel_dir / name).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for rel in ("info/exclude", "HEAD"):
        path = root / ".git" / rel
        if path.is_file():
            result[".git/" + rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def items(stdout: str) -> dict:
    """status letter -> list of paths the uninstall printed."""
    found = {"-": [], "!": [], ".": [], "=": []}
    for line in stdout.splitlines():
        match = ITEM_RE.match(line)
        if match:
            found[match.group(1)].append(match.group(2))
    return found


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uninstall-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = make_env(self.tmp)

    def install(self, repo: Path, *extra: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(INSTALL), str(repo), *extra], capture_output=True, text=True,
                              env=self.env, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
        return proc

    def uninstall(self, repo: Path, *extra: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(INSTALL), str(repo), "--uninstall", *extra], capture_output=True,
                              text=True, env=self.env, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
        return proc

    def absent(self, repo: Path, *extra: str):
        proc = subprocess.run(["python3", str(DOCTOR), str(repo), "--absent", *extra], capture_output=True,
                              text=True, env=self.env, timeout=300)
        report = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
        return proc, report

    def check(self, report: dict, check_id: str) -> dict:
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertIn(check_id, by_id, sorted(by_id))
        return by_id[check_id]


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only: the installers render from 01-roles/")
class InstallerUninstallTests(Base):
    def test_full_uninstall_leaves_no_kit_artifact_and_doctor_absent_passes(self):
        repo = make_repo(self.tmp / "bare", self.env)
        before = snapshot(repo)
        self.install(repo, "--runtime", "all")
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertFalse(report["kit_absent"])
        gone = self.uninstall(repo)
        self.assertEqual(snapshot(repo), before)
        removed = items(gone.stdout)["-"]
        for rel in (".claude/agents/generic-judge.md", ".claude/agents/generic-judge.contract.json",
                    ".claude/skills/init-kit/SKILL.md", ".pi/agents/generic-judge.md",
                    ".pi/skills/init-kit/SKILL.md", ".pi/extensions/metodo-hooks.ts",
                    ".mcp.json#mcpServers.metodo", ".pi/mcp.json#mcpServers.metodo"):
            self.assertIn(rel, removed, gone.stdout[-3000:])
        self.assertEqual(items(gone.stdout)["!"], [])
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(report["verdict"], "PASS")
        self.assertTrue(report["kit_absent"])
        self.assertEqual(report["mode"], "absent")

    def test_owner_assets_survive_byte_identical(self):
        repo = make_repo(self.tmp / "owned", self.env)
        add_owner_assets(repo)
        exclude = repo / ".git" / "info" / "exclude"
        exclude_before = exclude.read_text(encoding="utf-8")
        self.install(repo, "--runtime", "all")
        self.uninstall(repo)
        for rel, text in OWNER_FILES.items():
            self.assertEqual((repo / rel).read_text(encoding="utf-8"), text, rel)
        after = exclude.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(exclude_before), after)
        # the kit's own extension is gone, so is its exclude line; .mcp.json still has the owner's server
        self.assertNotIn(".pi/extensions/metodo-hooks.ts", after.splitlines())
        self.assertFalse((repo / ".pi" / "extensions").exists())
        self.assertFalse((repo / ".claude" / "agents" / "generic-judge.md").exists())
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(report["kit_absent"])

    def test_modified_kit_files_are_kept_and_reported(self):
        repo = make_repo(self.tmp / "mod", self.env)
        self.install(repo, "--runtime", "all")
        agent = repo / ".claude" / "agents" / "generic-judge.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\nmy tweak\n", encoding="utf-8")
        skill = repo / ".pi" / "skills" / "init-kit" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nmy tweak\n", encoding="utf-8")
        gone = self.uninstall(repo)
        kept = items(gone.stdout)["!"]
        self.assertIn(".claude/agents/generic-judge.md", kept)
        self.assertIn(".pi/skills/init-kit/SKILL.md", kept)
        self.assertIn("(kept: modified)", gone.stdout)
        self.assertTrue(agent.read_text(encoding="utf-8").endswith("my tweak\n"))
        self.assertTrue(skill.read_text(encoding="utf-8").endswith("my tweak\n"))
        # negative control: the untouched sibling is removed
        self.assertFalse((repo / ".claude" / "agents" / "generic-judge.contract.json").exists())
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertFalse(report["kit_absent"])
        self.assertEqual(self.check(report, "claude.agents")["status"], "FAIL")
        self.assertIn("generic-judge.md", self.check(report, "claude.agents")["detail"])
        self.assertEqual(self.check(report, "pi.skills")["status"], "FAIL")
        self.assertTrue(self.check(report, "pi.skills")["fix"])

    def test_second_uninstall_is_a_no_op(self):
        repo = make_repo(self.tmp / "twice", self.env)
        add_owner_assets(repo)
        self.install(repo, "--runtime", "all")
        self.uninstall(repo)
        once = snapshot(repo)
        again = self.uninstall(repo)
        self.assertEqual(snapshot(repo), once)
        self.assertEqual(items(again.stdout)["-"], [], again.stdout)
        self.assertEqual(items(again.stdout)["!"], [], again.stdout)

    def test_install_uninstall_install_round_trips(self):
        repo = make_repo(self.tmp / "round", self.env)
        self.install(repo, "--runtime", "all")
        single = snapshot(repo)
        self.uninstall(repo)
        self.install(repo, "--runtime", "all")
        self.assertEqual(snapshot(repo), single)

    def test_round_trip_with_owner_assets_differs_at_most_in_exclude_line_order(self):
        repo = make_repo(self.tmp / "round-owned", self.env)
        add_owner_assets(repo)
        exclude = repo / ".git" / "info" / "exclude"
        self.install(repo, "--runtime", "all")
        single, single_lines = snapshot(repo), exclude.read_text(encoding="utf-8").splitlines()
        self.uninstall(repo)
        self.install(repo, "--runtime", "all")
        again = snapshot(repo)
        single.pop(".git/info/exclude")
        again.pop(".git/info/exclude")
        self.assertEqual(again, single)
        # a kept line stays where it was, a removed one comes back at the end
        self.assertEqual(sorted(exclude.read_text(encoding="utf-8").splitlines()), sorted(single_lines))

    def test_single_runtime_uninstall_keeps_the_shared_server_for_the_other(self):
        repo = make_repo(self.tmp / "split", self.env)
        self.install(repo, "--runtime", "all")
        gone = self.uninstall(repo, "--runtime", "claude")
        self.assertIn(".mcp.json#mcpServers.metodo", items(gone.stdout)["="], gone.stdout)
        self.assertIn("metodo", json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"])
        self.assertTrue((repo / ".pi" / "extensions" / "metodo-hooks.ts").is_file())
        self.assertFalse((repo / ".claude" / "agents").exists())
        proc, report = self.absent(repo, "--runtime", "claude")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(report["kit_absent"])
        # the pi side is still there, so an all-runtime absence check fails
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.uninstall(repo, "--runtime", "pi")
        self.assertFalse((repo / ".mcp.json").exists())
        proc, report = self.absent(repo)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_doctor_absent_envelope_is_deterministic(self):
        repo = make_repo(self.tmp / "env", self.env)
        self.install(repo, "--runtime", "all")
        proc, report = self.absent(repo)
        text = proc.stdout
        self.assertEqual(text, json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        for bad in {str(self.tmp), os.path.realpath(self.tmp), self.env["HOME"], str(TOOLS_ROOT)}:
            self.assertNotIn(bad, text)
        self.assertNotRegex(text, r"\d{4}-\d{2}-\d{2}T")
        for c in report["checks"]:
            self.assertEqual(set(c), {"id", "status", "detail", "fix"})
            if c["status"] == "FAIL":
                self.assertTrue(c["fix"], c)
        ids = {c["id"] for c in report["checks"]}
        self.assertTrue({"claude.agents", "claude.skills", "claude.hooks", "claude.mcp", "pi.agents", "pi.skills",
                         "pi.extension", "pi.mcp"} <= ids, ids)
        # the shell wrapper prints the absence table
        sh = subprocess.run(["bash", str(DOCTOR_SH), str(repo), "--absent", "--out", str(self.tmp / "a.json")],
                            capture_output=True, text=True, env=self.env, timeout=300)
        self.assertEqual(sh.returncode, 1, sh.stdout + sh.stderr)
        self.assertIn("kit_absent: false", sh.stdout)

    def test_doctor_normal_mode_has_no_absence_fields(self):
        repo = make_repo(self.tmp / "normal", self.env)
        proc = subprocess.run(["python3", str(DOCTOR), str(repo)], capture_output=True, text=True, env=self.env,
                              timeout=300)
        report = json.loads(proc.stdout)
        self.assertNotIn("kit_absent", report)
        self.assertNotIn("mode", report)
        self.assertIn("kit_installed", report)


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only: init runs from the kit")
class InitUninstallTests(Base):
    def setUp(self):
        super().setUp()
        home = Path(self.env["HOME"])
        self.repo = make_repo(self.tmp / "work" / "fixture", self.env, gradle=True)
        self.instance = home / "fixture-tools"
        self.audit = home / "fixture-audit"
        proc = self.init("--no-smoke")
        self.assertIn(proc.returncode, (0, 1), proc.stdout[-2000:] + proc.stderr[-3000:])
        self.assertTrue((self.repo / ".claude" / "agents" / "generic-judge.md").is_file(), proc.stderr[-3000:])
        self.sha = git(self.repo, self.env, "rev-parse", "HEAD")

    def init(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(INIT_SH), str(self.repo), "--instance", str(self.instance), "--audit",
                               str(self.audit), "--no-fetch", *extra], capture_output=True, text=True, env=self.env,
                              timeout=900)

    def report_of(self, proc) -> dict:
        self.assertTrue(proc.stdout.strip().startswith("{"), proc.stdout[-2000:] + proc.stderr[-2000:])
        return json.loads(proc.stdout)

    def test_uninstall_keeps_instance_and_audit_and_writes_the_report(self):
        inst_before, audit_before = snapshot(self.instance), snapshot(self.audit)
        proc = self.init("--uninstall")
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-3000:])
        report = self.report_of(proc)
        path = self.instance / "out" / "uninstall" / f"{self.sha}.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding="utf-8"), proc.stdout)
        self.assertTrue(report["kit_absent"])
        for key in ("removed", "kept_modified", "not_found", "kit_absent", "instance", "audit", "runtime"):
            self.assertIn(key, report)
        self.assertIn(".claude/agents/generic-judge.md", report["removed"])
        self.assertEqual(report["kept_modified"], [])
        self.assertEqual(report["instance"]["action"], "kept")
        self.assertEqual(report["audit"]["action"], "kept")
        self.assertEqual({k: v for k, v in snapshot(self.instance).items() if not k.startswith("out/")},
                         {k: v for k, v in inst_before.items() if not k.startswith("out/")})
        self.assertEqual(snapshot(self.audit), audit_before)
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / ".pi").exists())
        text = proc.stdout
        for bad in {str(self.tmp), os.path.realpath(self.tmp), self.env["HOME"], str(TOOLS_ROOT)}:
            self.assertNotIn(bad, text)
        self.assertEqual(text, json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        # S8: personal assets are never involved
        for s in strings(report):
            self.assertFalse(any(p in s for p in PERSONAL), s)

    def test_modified_kit_agent_is_kept_and_exit_is_1(self):
        agent = self.repo / ".claude" / "agents" / "generic-judge.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\nowner edit\n", encoding="utf-8")
        proc = self.init("--uninstall")
        self.assertEqual(proc.returncode, 1, proc.stderr[-3000:])
        report = self.report_of(proc)
        self.assertIn(".claude/agents/generic-judge.md", report["kept_modified"])
        self.assertFalse(report["kit_absent"])
        self.assertTrue(agent.is_file())

    def test_dry_run_changes_nothing(self):
        before = (snapshot(self.repo), snapshot(self.instance), snapshot(self.audit))
        proc = self.init("--uninstall", "--purge", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        self.assertIn("dry-run", proc.stdout)
        self.assertIn("--uninstall", proc.stdout)
        self.assertEqual((snapshot(self.repo), snapshot(self.instance), snapshot(self.audit)), before)

    def test_purge_deletes_an_untouched_instance_and_audit(self):
        proc = self.init("--uninstall", "--purge")
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-3000:])
        report = self.report_of(proc)
        self.assertEqual(report["instance"]["action"], "purged", report["instance"])
        self.assertEqual(report["audit"]["action"], "purged", report["audit"])
        self.assertFalse(self.instance.exists())
        self.assertFalse(self.audit.exists())
        self.assertTrue(report["kit_absent"])
        self.assertTrue(self.repo.is_dir())
        self.assertEqual(git(self.repo, self.env, "rev-parse", "HEAD"), self.sha)

    def test_purge_refuses_an_instance_with_more_history_and_an_audit_with_owner_edits(self):
        (self.instance / "notes.md").write_text("owner notes\n", encoding="utf-8")
        git(self.instance, self.env, "add", "notes.md")
        git(self.instance, self.env, "commit", "-q", "-m", "owner: notes")
        inv = self.audit / "invariants.md"
        inv.write_text(inv.read_text(encoding="utf-8") + "| INV-09 | mine |\n", encoding="utf-8")
        (self.audit / "card-001.md").write_text("owner card\n", encoding="utf-8")
        proc = self.init("--uninstall", "--purge")
        self.assertEqual(proc.returncode, 1, proc.stderr[-3000:])
        report = self.report_of(proc)
        self.assertEqual(report["instance"]["action"], "refused", report["instance"])
        self.assertTrue(any("commit" in r for r in report["instance"]["reasons"]), report["instance"])
        self.assertEqual(report["audit"]["action"], "refused", report["audit"])
        reasons = " ".join(report["audit"]["reasons"])
        self.assertIn("invariants.md", reasons)
        self.assertIn("card-001.md", reasons)
        self.assertNotIn("CONTEXT-PACK.md", reasons)
        self.assertTrue((self.instance / "notes.md").is_file())
        self.assertTrue(inv.is_file())
        # the repo side still unplugged
        self.assertTrue(report["kit_absent"])

    def test_purge_refuses_an_instance_with_uncommitted_owner_work(self):
        config = self.instance / "config" / "project.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["critical_properties"] = ["owner-decided"]
        config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        proc = self.init("--uninstall", "--purge")
        self.assertEqual(proc.returncode, 1, proc.stderr[-3000:])
        report = self.report_of(proc)
        self.assertEqual(report["instance"]["action"], "refused", report["instance"])
        self.assertIn("config/project.json", " ".join(report["instance"]["reasons"]))
        self.assertTrue(config.is_file())

    def test_purge_keeps_the_instance_while_kit_files_still_point_at_it(self):
        agent = self.repo / ".claude" / "agents" / "generic-judge.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "\nowner edit\n", encoding="utf-8")
        proc = self.init("--uninstall", "--purge")
        self.assertEqual(proc.returncode, 1, proc.stderr[-3000:])
        report = self.report_of(proc)
        self.assertEqual(report["instance"]["action"], "refused", report["instance"])
        self.assertIn("kit_absent", " ".join(report["instance"]["reasons"]))
        self.assertTrue(self.instance.is_dir())
        # the audit folder holds no pointer the repo needs: untouched scaffolds still go
        self.assertEqual(report["audit"]["action"], "purged", report["audit"])

    def test_purge_without_uninstall_is_usage(self):
        proc = self.init("--purge")
        self.assertEqual(proc.returncode, 2, proc.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
