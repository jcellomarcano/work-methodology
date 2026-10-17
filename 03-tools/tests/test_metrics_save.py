"""bin/metrics.sh --save: the first baseline, and the delta against it.

Every test runs the real script over a throwaway copy of the tools tree
(bin/, lib/, the two config files the run reads) committed in its own git
repo, so the tool_sha is stable and the real out/ and baselines/ are never
touched. There is no vendor/ in the copy, so duplication_cpd takes its
documented fallback (fallback-linehash) and no PMD jar is needed.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import baseline

REAL_TOOLS_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILES = ("cpd.json", "style-guide-map.json")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")


def _commit_all(path: Path, message: str) -> str:
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


class _Fixture:
    def __init__(self, tmp: Path):
        self.tools = tmp / "tools"
        self.repo = tmp / "repo"
        self._build_tools()
        self._build_repo()

    def _build_tools(self) -> None:
        self.tools.mkdir()
        for name in ("bin", "lib"):
            shutil.copytree(
                REAL_TOOLS_ROOT / name,
                self.tools / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        (self.tools / "config").mkdir()
        for name in CONFIG_FILES:
            shutil.copy2(REAL_TOOLS_ROOT / "config" / name, self.tools / "config" / name)
        (self.tools / ".gitignore").write_text("out/\nbaselines/\n__pycache__/\n", encoding="utf-8")
        _init_repo(self.tools)
        _commit_all(self.tools, "tools")

    def _build_repo(self) -> None:
        _init_repo(self.repo)
        (self.repo / "settings.gradle").write_text("include ':app'\n", encoding="utf-8")
        self.write_kotlin(3)
        self.sha1 = _commit_all(self.repo, "one")

    def write_kotlin(self, functions: int) -> None:
        src = self.repo / "app" / "src" / "main" / "kotlin" / "A.kt"
        src.parent.mkdir(parents=True, exist_ok=True)
        body = ["package a", ""]
        for i in range(functions):
            body += [f"fun f{i}(x: Int): Int {{", "    val y = x + 1", "    return y", "}", ""]
        src.write_text("\n".join(body), encoding="utf-8")

    @property
    def baselines(self) -> Path:
        return self.tools / "baselines"

    @property
    def latest(self) -> Path:
        return self.baselines / "latest"

    def out(self, sha: str) -> Path:
        return self.tools / "out" / sha

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, METODO_MEMORY="off")
        return subprocess.run(
            ["bash", str(self.tools / "bin" / "metrics.sh"), *args],
            capture_output=True,
            text=True,
            env=env,
        )


class MetricsSaveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = _Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _ok(self, proc: subprocess.CompletedProcess) -> None:
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")

    def test_without_save_writes_no_baseline(self):
        # regression: a plain run stays read-only towards baselines/
        proc = self.fx.run(str(self.fx.repo))
        self._ok(proc)
        self.assertTrue((self.fx.out(self.fx.sha1) / "metrics.json").exists())
        self.assertFalse(self.fx.baselines.exists())
        self.assertFalse((self.fx.out(self.fx.sha1) / "delta.json").exists())

    def test_save_on_clean_tree_writes_baseline_and_latest(self):
        proc = self.fx.run(str(self.fx.repo), "--save")
        self._ok(proc)
        saved = self.fx.baselines / f"{self.fx.sha1}.json"
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), (self.fx.out(self.fx.sha1) / "metrics.json").read_bytes())
        self.assertTrue(self.fx.latest.is_symlink())
        self.assertEqual(os.readlink(self.fx.latest), saved.name)
        self.assertEqual(self.fx.latest.resolve(), saved.resolve())
        self.assertIn("baseline saved", proc.stderr)

    def test_save_flag_may_come_first(self):
        proc = self.fx.run("--save", str(self.fx.repo))
        self._ok(proc)
        self.assertTrue((self.fx.baselines / f"{self.fx.sha1}.json").exists())

    def test_save_on_dirty_tree_refuses_and_writes_nothing(self):
        (self.fx.repo / "settings.gradle").write_text("include ':app'\n// wip\n", encoding="utf-8")
        proc = self.fx.run(str(self.fx.repo), "--save")
        # negative control: a dirty tree is never a reference point
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("uncommitted changes", proc.stderr)
        self.assertFalse(self.fx.baselines.exists())
        self.assertFalse(self.fx.out(self.fx.sha1).exists())

    def test_second_run_on_new_sha_produces_delta_against_latest(self):
        self._ok(self.fx.run(str(self.fx.repo), "--save"))
        self.fx.write_kotlin(5)
        sha2 = _commit_all(self.fx.repo, "two")
        proc = self.fx.run(str(self.fx.repo))
        self._ok(proc)
        delta = baseline.load_json(self.fx.out(sha2) / "delta.json")
        self.assertNotIn("verdict", delta)
        self.assertTrue(delta["changed"], "growing A.kt must change at least one metric")
        self.assertTrue((self.fx.out(sha2) / "delta.md").exists())
        self.assertIn("delta vs", proc.stderr)
        # the plain run did not move the reference point
        self.assertEqual(os.readlink(self.fx.latest), f"{self.fx.sha1}.json")
        self.assertFalse((self.fx.baselines / f"{sha2}.json").exists())

    def test_save_on_new_sha_repoints_latest(self):
        self._ok(self.fx.run(str(self.fx.repo), "--save"))
        self.fx.write_kotlin(5)
        sha2 = _commit_all(self.fx.repo, "two")
        self._ok(self.fx.run(str(self.fx.repo), "--save"))
        # the delta is computed against the previous baseline, before latest moves
        delta = baseline.load_json(self.fx.out(sha2) / "delta.json")
        self.assertTrue(delta["changed"])
        self.assertTrue((self.fx.baselines / f"{self.fx.sha1}.json").exists())
        self.assertEqual(os.readlink(self.fx.latest), f"{sha2}.json")

    def test_same_sha_rerun_is_byte_identical(self):
        self._ok(self.fx.run(str(self.fx.repo), "--save"))
        out = self.fx.out(self.fx.sha1)
        saved = self.fx.baselines / f"{self.fx.sha1}.json"
        first = {name: (out / name).read_bytes() for name in ("metrics.json", "metrics.md", "duplication.json")}
        first_baseline = saved.read_bytes()

        self._ok(self.fx.run(str(self.fx.repo)))
        first_delta = (out / "delta.json").read_bytes()
        rerun = self.fx.run(str(self.fx.repo), "--save")
        # an identical re-save is idempotent, not an overwrite error
        self._ok(rerun)
        for name, data in first.items():
            self.assertEqual((out / name).read_bytes(), data, name)
        self.assertEqual((out / "delta.json").read_bytes(), first_delta)
        self.assertEqual(saved.read_bytes(), first_baseline)
        self.assertEqual(os.readlink(self.fx.latest), saved.name)

    def test_tool_drift_stays_void_and_saves_nothing(self):
        self._ok(self.fx.run(str(self.fx.repo), "--save"))
        (self.fx.tools / "lib" / "drift_marker.txt").write_text("new tool version\n", encoding="utf-8")
        _commit_all(self.fx.tools, "tool change")
        self.fx.write_kotlin(5)
        sha2 = _commit_all(self.fx.repo, "two")

        proc = self.fx.run(str(self.fx.repo), "--save")
        self.assertEqual(proc.returncode, 2, f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertEqual(baseline.load_json(self.fx.out(sha2) / "delta.json")["verdict"], "VOID: tool drift")
        # negative control: a drifted run is never silently promoted to the reference point
        self.assertFalse((self.fx.baselines / f"{sha2}.json").exists())
        self.assertEqual(os.readlink(self.fx.latest), f"{self.fx.sha1}.json")

    def test_usage_mentions_save(self):
        proc = self.fx.run()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--save", proc.stderr)

    def test_unknown_flag_is_rejected(self):
        proc = self.fx.run(str(self.fx.repo), "--saev")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--saev", proc.stderr)
        self.assertFalse(self.fx.out(self.fx.sha1).exists())


if __name__ == "__main__":
    unittest.main()
