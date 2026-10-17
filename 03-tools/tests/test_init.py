"""bin/init.sh and lib/init_kit.py: one command from zero to a working kit
instance (kit-init T8, S1, S3, S8, S9, S10).

One throwaway target repo is initialized twice in setUpClass (a fake HOME,
an isolated git config, --no-fetch, METODO_MEMORY=off): the first run is the
fixture every test reads, the second proves idempotency. Cases that need a
different state work on their own copy or on a cheap preflight path.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
INIT_SH = TOOLS_ROOT / "bin" / "init.sh"
APP_KT = "package a\n\nfun answer(x: Int): Int {\n    val y = x + 1\n    return y\n}\n"

sys.path.insert(0, str(TOOLS_ROOT))

from lib.doctor import is_personal_path  # noqa: E402


def _git(cwd: Path, *args: str, env=None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


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


def tree_digest(root: Path, skip_top=("out",)) -> dict:
    """path -> sha256 (or symlink target) of every file under root, .git
    internals reduced to HEAD and refs, out/ and __pycache__ skipped."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in skip_top]
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for name in filenames:
            path = Path(dirpath) / name
            rel = (rel_dir / name).as_posix()
            if path.is_symlink():
                result[rel] = "-> " + os.readlink(path)
            else:
                result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def repo_state(repo: Path, env) -> dict:
    return {
        "head": _git(repo, "rev-parse", "HEAD", env=env),
        "status": _git(repo, "status", "--porcelain", "--untracked-files=all", env=env),
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", env=env),
        "index": _git(repo, "ls-files", "-s", env=env),
        "tree": tree_digest(repo, skip_top=()),
    }


class InitBase(unittest.TestCase):
    @classmethod
    def make_env(cls, root: Path) -> dict:
        home = root / "home"
        home.mkdir(parents=True, exist_ok=True)
        gitconfig = root / "gitconfig"
        gitconfig.write_text("[user]\n\temail = t@example.com\n\tname = t\n[commit]\n\tgpgsign = false\n"
                             "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("METODO_", "GIT_"))}
        env.update(HOME=str(home), METODO_MEMORY="off", GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
        return env

    @staticmethod
    def make_repo(path: Path, env) -> Path:
        """A small Gradle/Kotlin repo: metrics.sh and cartography.sh are Gradle-oriented."""
        path.mkdir(parents=True)
        _git(path, "init", "-q", "-b", "main", env=env)
        (path / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
        main = path / "app" / "src" / "main" / "kotlin" / "A.kt"
        main.parent.mkdir(parents=True)
        main.write_text(APP_KT, encoding="utf-8")
        test = path / "app" / "src" / "test" / "kotlin" / "ATest.kt"
        test.parent.mkdir(parents=True)
        test.write_text("package a\n\nfun testAnswer() = check(answer(1) == 2)\n", encoding="utf-8")
        (path / "README.md").write_text("# fixture\n", encoding="utf-8")
        _git(path, "add", "-A", env=env)
        _git(path, "commit", "-q", "-m", "initial", env=env)
        return path

    @staticmethod
    def run_init(repo: Path, instance: Path, audit: Path, env, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(INIT_SH), str(repo), "--instance", str(instance), "--audit", str(audit),
                               "--no-fetch", *extra], capture_output=True, text=True, env=env, timeout=900)


@unittest.skipUnless((TOOLS_ROOT.parent / "01-roles").is_dir(), "kit only: init runs from the kit")
class InitFullRunTests(InitBase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="init-kit-"))
        cls.env = cls.make_env(cls.tmp)
        home = Path(cls.env["HOME"])
        cls.repo = cls.make_repo(cls.tmp / "work" / "fixture", cls.env)
        cls.instance = home / "fixture-tools"
        cls.audit = home / "fixture-audit"
        cls.repo_before = repo_state(cls.repo, cls.env)
        cls.proc1 = cls.run_init(cls.repo, cls.instance, cls.audit, cls.env)
        cls.sha = _git(cls.repo, "rev-parse", "HEAD", env=cls.env)
        cls.report_path = cls.instance / "out" / "init" / f"{cls.sha}.json"
        cls.report_bytes1 = cls.report_path.read_bytes() if cls.report_path.exists() else b""
        cls.report = json.loads(cls.report_bytes1) if cls.report_bytes1 else {}
        cls.repo_after1 = repo_state(cls.repo, cls.env)
        cls.instance_after1 = tree_digest(cls.instance) if cls.instance.exists() else {}
        cls.audit_after1 = tree_digest(cls.audit) if cls.audit.exists() else {}
        cls.instance_log1 = (_git(cls.instance, "log", "--format=%H %s", env=cls.env)
                             if (cls.instance / ".git").exists() else "")
        cls.proc2 = cls.run_init(cls.repo, cls.instance, cls.audit, cls.env)
        cls.report_bytes2 = cls.report_path.read_bytes() if cls.report_path.exists() else b""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def step(self, name: str) -> dict:
        by_name = {s["step"]: s for s in self.report["steps"]}
        self.assertIn(name, by_name, sorted(by_name))
        return by_name[name]

    # S1 / S10: one command, a working instance, evidence for the benchmark
    def test_full_init_exits_zero_and_is_ready_for_benchmark(self):
        self.assertEqual(self.proc1.returncode, 0, self.proc1.stdout[-3000:] + self.proc1.stderr[-3000:])
        self.assertEqual(self.report["doctor"]["verdict"], "PASS")
        self.assertTrue(self.report["doctor"]["kit_installed"])
        self.assertEqual(self.report["smoke"]["verdict"], "PASS")
        self.assertTrue(self.report["smoke"]["loop_ran"])
        self.assertTrue(self.report["ready_for_benchmark"])

    def test_every_step_is_recorded_in_order(self):
        names = [s["step"] for s in self.report["steps"]]
        self.assertEqual(names, ["preflight", "instance", "adapt", "scaffolds", "fetch", "calibrate", "install",
                                 "baseline", "map", "doctor", "smoke", "suggestions"])
        for s in self.report["steps"]:
            self.assertEqual(set(s), {"step", "status", "detail", "fix"}, s)
            self.assertIn(s["status"], {"done", "skipped", "warn", "fail"}, s)
        self.assertEqual(self.step("fetch")["status"], "skipped")
        self.assertEqual(self.step("install")["status"], "done")
        self.assertEqual(self.step("baseline")["status"], "done")
        self.assertTrue((self.instance / "baselines" / "latest").exists())
        self.assertTrue((self.instance / "out" / "doctor" / f"{self.sha}.json").is_file())
        self.assertTrue((self.instance / "out" / "smoke" / f"{self.sha}.json").is_file())

    def test_new_instance_is_a_git_repo_with_one_initial_commit(self):
        lines = self.instance_log1.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0].split(" ", 1)[1], r"^chore: kit instance from [0-9a-f]{7,40}$")
        tracked = _git(self.instance, "ls-files", env=self.env).splitlines()
        self.assertIn("config/project.json", tracked)
        self.assertFalse(any(t.startswith(("out/", "baselines/", "vendor/")) for t in tracked))

    def test_adapt_wrote_the_instance_config(self):
        config = json.loads((self.instance / "config" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(config["docs_root"], "~/fixture-audit")
        self.assertEqual(config["language"], "kotlin")

    # S1: nothing left out
    def test_pending_human_steps_name_their_file_and_cover_the_checklist(self):
        pending = self.report["pending_human_steps"]
        self.assertTrue(pending)
        for item in pending:
            self.assertEqual(set(item), {"section", "step", "file"}, item)
            self.assertTrue(item["file"], item)
        sections = [item["section"] for item in pending]
        self.assertEqual(sections, sorted(sections))
        keys = [(i["step"], i["file"]) for i in pending]
        self.assertEqual(len(keys), len(set(keys)))
        text = "\n".join(f"{i['step']} -> {i['file']}" for i in pending)
        for needle in ("property hierarchy", "critical_properties", "critical_paths", "invariants.md", "<repo>/CONVENTIONS.md",
                       "dep-boundaries.json", "Owner", "emergency lane", "unavailable", "custody",
                       "real environment", "change card", "duplication"):
            self.assertIn(needle, text)

    def test_scaffolds_are_in_the_audit_folder_only(self):
        for name in ("invariants.md", "CONTEXT-PACK.md", "CONVENTIONS.md.template"):
            self.assertTrue((self.audit / name).is_file(), name)
            self.assertFalse((self.repo / name).exists(), name)
        self.assertIn("INV-01", (self.audit / "invariants.md").read_text(encoding="utf-8"))
        self.assertIn("How this applies here", (self.audit / "CONTEXT-PACK.md").read_text(encoding="utf-8"))
        self.assertIn("06-languages/kotlin.md", (self.audit / "CONVENTIONS.md.template").read_text(encoding="utf-8"))

    def test_target_repo_tracked_files_are_untouched(self):
        for key in ("head", "refs", "index"):
            self.assertEqual(self.repo_before[key], self.repo_after1[key], key)
        changed = {p for p in set(self.repo_before["tree"]) | set(self.repo_after1["tree"])
                   if self.repo_before["tree"].get(p) != self.repo_after1["tree"].get(p)}
        tracked = set(self.repo_before["index"] and [l.split("\t", 1)[1] for l in self.repo_before["index"].splitlines()])
        self.assertEqual(changed & tracked, set())
        # every installed file is git-excluded or under .claude/: the tree reads clean
        from lib import baseline
        self.assertFalse(baseline.is_repo_dirty(self.repo))

    # S8
    def test_no_personal_asset_in_repo_instance_or_audit(self):
        for root in (self.repo, self.instance, self.audit):
            for path in root.rglob("*"):
                rel = path.relative_to(root).as_posix()
                self.assertFalse(is_personal_path(rel), f"{root}: {rel}")

    # S3
    def test_report_carries_the_suggestions(self):
        ids = {s["id"] for s in self.report["suggestions"]}
        self.assertTrue({"engram", "context7", "gentle-ai", "gh", "java", "node"} <= ids, ids)
        for s in self.report["suggestions"]:
            self.assertEqual(set(s), {"id", "status", "why", "command"})

    # S9 + determinism contract
    def test_report_has_no_absolute_paths_and_sorted_keys(self):
        text = self.report_bytes1.decode("utf-8")
        for bad in {str(self.tmp), os.path.realpath(self.tmp), self.env["HOME"], str(Path.home()),
                    str(TOOLS_ROOT), os.path.realpath(TOOLS_ROOT)}:
            self.assertNotIn(bad, text)
        for s in _strings(self.report):
            self.assertIsNone(re.search(r"(?<![\w.<>~-])/(Users|home|private|var|tmp|opt|Library)/", s), s)
        self.assertEqual(text, json.dumps(self.report, sort_keys=True, indent=2, ensure_ascii=False) + "\n")

    # idempotency
    def test_second_run_is_idempotent(self):
        self.assertEqual(self.proc2.returncode, 0, self.proc2.stderr[-3000:])
        self.assertEqual(self.report_bytes1, self.report_bytes2)
        self.assertEqual(self.instance_log1, _git(self.instance, "log", "--format=%H %s", env=self.env))
        self.assertEqual(self.instance_after1, tree_digest(self.instance))
        self.assertEqual(self.audit_after1, tree_digest(self.audit))
        after2 = repo_state(self.repo, self.env)
        for key in ("head", "refs", "index", "status", "tree"):
            self.assertEqual(self.repo_after1[key], after2[key], key)
        install_lines = [l for l in self.proc2.stderr.splitlines() if l.startswith("  + ") or l.startswith("  ~ ")]
        self.assertEqual(install_lines, [])

    def test_baseline_skipped_on_a_dirty_repo_is_a_pending_step(self):
        root = self.tmp / "dirty"
        shutil.copytree(self.tmp / "work", root / "work", symlinks=True)
        shutil.copytree(self.instance, root / "inst", symlinks=True)
        repo = root / "work" / "fixture"
        app = repo / "app" / "src" / "main" / "kotlin" / "A.kt"
        app.write_text(APP_KT + "\nfun second() = 2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "second", env=self.env)
        app.write_text(APP_KT + "\nfun third() = 3\n", encoding="utf-8")
        proc = self.run_init(repo, root / "inst", root / "audit", self.env, "--no-smoke")
        sha = _git(repo, "rev-parse", "HEAD", env=self.env)
        report = json.loads((root / "inst" / "out" / "init" / f"{sha}.json").read_text(encoding="utf-8"))
        steps = {s["step"]: s for s in report["steps"]}
        self.assertEqual(steps["baseline"]["status"], "warn", steps["baseline"])
        self.assertIn("<instance>/bin/metrics.sh <repo> --save", steps["baseline"]["fix"])
        self.assertTrue(any("metrics.sh <repo> --save" in p["step"] or "metrics.sh <repo> --save" in p["file"]
                            for p in report["pending_human_steps"]), report["pending_human_steps"])
        self.assertEqual(steps["smoke"]["status"], "skipped")
        self.assertFalse(report["ready_for_benchmark"])
        self.assertIn(proc.returncode, (0, 1), proc.stderr[-2000:])
        self.assertEqual(app.read_text(encoding="utf-8"), APP_KT + "\nfun third() = 3\n")


class InitCheapTests(InitBase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="init-kit-cheap-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = self.make_env(self.tmp)

    def test_non_git_target_exits_2_and_creates_nothing(self):
        target = self.tmp / "plain"
        target.mkdir()
        proc = self.run_init(target, self.tmp / "inst", self.tmp / "audit", self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertFalse((self.tmp / "inst").exists())
        self.assertFalse((self.tmp / "audit").exists())

    def test_repo_without_commits_exits_2(self):
        target = self.tmp / "empty"
        target.mkdir()
        _git(target, "init", "-q", env=self.env)
        proc = self.run_init(target, self.tmp / "inst", self.tmp / "audit", self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertFalse((self.tmp / "inst").exists())

    def test_the_kit_itself_as_target_is_refused(self):
        # T10 advisory 7: init must never adapt or install into the kit checkout
        proc = self.run_init(TOOLS_ROOT.parent, self.tmp / "inst", self.tmp / "audit", self.env, "--dry-run")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("is the kit", proc.stderr)
        self.assertFalse((self.tmp / "inst").exists())

    def test_non_gradle_repo_baseline_pending_step_names_the_real_cause(self):
        # T10 advisory 1: the pending step must not blame a dirty tree when the cause is no settings.gradle
        repo = self.tmp / "py"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main", env=self.env)
        (repo / "pkg").mkdir()
        (repo / "pkg" / "__init__.py").write_text("ANSWER = 42\n", encoding="utf-8")
        _git(repo, "add", "-A", env=self.env)
        _git(repo, "commit", "-q", "-m", "initial", env=self.env)
        proc = self.run_init(repo, self.tmp / "inst", self.tmp / "audit", self.env, "--no-smoke")
        sha = _git(repo, "rev-parse", "HEAD", env=self.env)
        report = json.loads((self.tmp / "inst" / "out" / "init" / f"{sha}.json").read_text(encoding="utf-8"))
        steps = {s["step"]: s for s in report["steps"]}
        self.assertEqual(steps["baseline"]["status"], "warn", steps["baseline"])
        self.assertIn("settings.gradle", steps["baseline"]["detail"])
        baseline_pending = [p for p in report["pending_human_steps"] if p["file"] == "<instance>/baselines/latest"]
        self.assertEqual(len(baseline_pending), 1, report["pending_human_steps"])
        self.assertIn("settings.gradle", baseline_pending[0]["step"])
        self.assertNotIn("clean tree", baseline_pending[0]["step"])
        self.assertIn(proc.returncode, (0, 1), proc.stderr[-2000:])

    def test_audit_or_instance_inside_the_repo_is_refused(self):
        repo = self.make_repo(self.tmp / "repo", self.env)
        proc = self.run_init(repo, self.tmp / "inst", repo / "audit", self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        proc = self.run_init(repo, repo / "tools", self.tmp / "audit", self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_git(repo, "status", "--porcelain", env=self.env), "")

    def test_dry_run_prints_the_plan_and_writes_nothing(self):
        repo = self.make_repo(self.tmp / "repo", self.env)
        before = tree_digest(self.tmp, skip_top=())
        proc = self.run_init(repo, self.tmp / "inst", self.tmp / "audit", self.env, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ("preflight", "instance", "adapt", "scaffolds", "fetch", "calibrate", "install", "baseline",
                     "map", "doctor", "smoke", "suggestions", "report"):
            self.assertIn(name, proc.stdout)
        self.assertEqual(before, tree_digest(self.tmp, skip_top=()))
        self.assertFalse((self.tmp / "inst").exists())

    def test_scaffolds_never_overwrite(self):
        from lib import init_kit
        audit = self.tmp / "audit"
        audit.mkdir()
        mine = "# my invariants\n"
        (audit / "invariants.md").write_text(mine, encoding="utf-8")
        written = init_kit.write_scaffolds(audit, TOOLS_ROOT, "python", "INV")
        self.assertEqual((audit / "invariants.md").read_text(encoding="utf-8"), mine)
        self.assertNotIn("invariants.md", written)
        self.assertIn("CONTEXT-PACK.md", written)
        second = init_kit.write_scaffolds(audit, TOOLS_ROOT, "python", "INV")
        self.assertEqual(second, [])

    def test_conventions_template_without_a_digest_points_to_the_folder(self):
        from lib import init_kit
        audit = self.tmp / "audit"
        audit.mkdir()
        init_kit.write_scaffolds(audit, TOOLS_ROOT, "cobol", "INV")
        text = (audit / "CONVENTIONS.md.template").read_text(encoding="utf-8")
        self.assertIn("06-languages/", text)
        self.assertNotIn("06-languages/cobol.md", text.replace("no 06-languages/cobol.md", ""))


if __name__ == "__main__":
    unittest.main()
