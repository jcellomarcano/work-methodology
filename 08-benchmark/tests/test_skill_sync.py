"""The harness-benchmark skill ships copies of 08-benchmark/lib; they must never drift."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "08-benchmark" / "bin" / "sync-skill.sh"
SKILL = REPO / "02-skills" / "harness-benchmark"
# source in 08-benchmark/lib -> top-level copy in the skill folder
PAIRS = {
    "transcript_metrics.py": "transcript_metrics.py",
    "bench_session.py": "bench_session.py",
    "bench_ab.py": "bench_ab.py",
    "bench_cli.py": "bench.py",
}


def _check(repo: pathlib.Path):
    return subprocess.run(["bash", str(repo / "08-benchmark" / "bin" / "sync-skill.sh"), "--check"],
                          capture_output=True, text=True)


class RealRepoSyncTests(unittest.TestCase):
    def test_skill_copies_equal_their_sources(self):
        for src_name, dst_name in PAIRS.items():
            src = REPO / "08-benchmark" / "lib" / src_name
            if not src.is_file():
                continue
            dst = SKILL / dst_name
            with self.subTest(copy=dst_name):
                self.assertTrue(dst.is_file(), f"missing copy: 02-skills/harness-benchmark/{dst_name} "
                                               f"(run 08-benchmark/bin/sync-skill.sh)")
                self.assertTrue(src.read_bytes() == dst.read_bytes(),
                                f"drifted copy: 02-skills/harness-benchmark/{dst_name} differs from "
                                f"08-benchmark/lib/{src_name} (run 08-benchmark/bin/sync-skill.sh)")

    def test_check_mode_passes_on_the_real_repo(self):
        r = _check(REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class SyncScriptTests(unittest.TestCase):
    """The script itself, on a throwaway copy of the folders it touches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(os.path.realpath(self.tmp.name))
        (self.repo / "08-benchmark" / "bin").mkdir(parents=True)
        (self.repo / "08-benchmark" / "lib").mkdir()
        (self.repo / "02-skills" / "harness-benchmark").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / "08-benchmark" / "bin" / "sync-skill.sh")
        for name in ("transcript_metrics.py", "bench_session.py", "bench_cli.py"):
            (self.repo / "08-benchmark" / "lib" / name).write_text(f"# {name}\n")
        (self.repo / "02-skills" / "harness-benchmark" / "SKILL.md").write_text("skill\n")
        self.skill = self.repo / "02-skills" / "harness-benchmark"

    def tearDown(self):
        self.tmp.cleanup()

    def _sync(self, *args):
        return subprocess.run(["bash", str(self.repo / "08-benchmark" / "bin" / "sync-skill.sh"), *args],
                              capture_output=True, text=True)

    def test_sync_copies_and_renames_and_skips_missing_sources(self):
        r = self._sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.skill / "bench.py").read_text(), "# bench_cli.py\n")
        self.assertEqual((self.skill / "bench_session.py").read_text(), "# bench_session.py\n")
        self.assertFalse((self.skill / "bench_cli.py").exists())
        self.assertFalse((self.skill / "bench_ab.py").exists())
        self.assertIn("bench_ab.py", r.stdout + r.stderr)
        self.assertEqual(_check(self.repo).returncode, 0)

    def test_check_names_drifted_and_missing_copies_without_writing(self):
        self._sync()
        (self.skill / "bench_session.py").write_text("edited by hand\n")
        (self.skill / "bench.py").unlink()
        r = _check(self.repo)
        self.assertEqual(r.returncode, 1)
        out = r.stdout + r.stderr
        self.assertIn("drift", out)
        self.assertIn("bench_session.py", out)
        self.assertIn("missing", out)
        self.assertIn("bench.py", out)
        self.assertNotIn("transcript_metrics.py", out.replace("bench_ab.py", ""))
        self.assertEqual((self.skill / "bench_session.py").read_text(), "edited by hand\n")
        self.assertFalse((self.skill / "bench.py").exists())

    def test_usage_error_exits_2(self):
        self.assertEqual(self._sync("--bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()


class NoBytecodeInSkillFolderTests(unittest.TestCase):
    """The kit installer copies every entry of a skill folder with plain cp, so a __pycache__
    directory left by running bench.py in place would break the next install (2026-10-20)."""

    def test_running_bench_in_a_skill_folder_writes_no_bytecode(self):
        import shutil, subprocess, sys, tempfile
        lib = pathlib.Path(__file__).resolve().parents[1] / "lib"
        with tempfile.TemporaryDirectory() as d:
            skill = pathlib.Path(d) / "harness-benchmark"
            skill.mkdir()
            for name in ("transcript_metrics.py", "bench_session.py", "bench_ab.py"):
                shutil.copy(lib / name, skill / name)
            shutil.copy(lib / "bench_cli.py", skill / "bench.py")
            env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
            subprocess.run([sys.executable, str(skill / "bench.py"), "report", "--run", str(pathlib.Path(d) / "nope")],
                           capture_output=True, env=env)
            self.assertFalse((skill / "__pycache__").exists(), sorted(p.name for p in skill.iterdir()))
