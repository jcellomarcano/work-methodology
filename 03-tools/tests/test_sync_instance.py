"""bin/sync-instance.sh and personal assets (kit-init T8, S8, Log L12).

The sync copies code and every missing config file into an instance, but a
personal asset (by convention: a path component named `personal` or matching
`*.personal.*`) is never copied; an instance that already holds one keeps it
byte for byte.

The benchmark has one source, the kit's 08-benchmark/: its lib/ bin/ protocols/
reach <instance>/bench/ under the same rules (benchmark-port S3)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.doctor import is_personal_path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
BENCH_ROOT = TOOLS_ROOT.parent / "08-benchmark"
SYNC = TOOLS_ROOT / "bin" / "sync-instance.sh"
PERSONAL = "config/output-lint.personal.json"


def personal_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if is_personal_path(p.relative_to(root).as_posix()))


class SyncInstancePersonalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-instance-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def sync(self, instance: Path) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(SYNC), str(instance)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def test_new_instance_never_receives_the_personal_lint_file(self):
        instance = self.tmp / "inst"
        instance.mkdir()
        self.sync(instance)
        self.assertTrue((instance / "config" / "project.json").is_file())
        self.assertTrue((instance / "config" / "output-lint.json").is_file())
        self.assertFalse((instance / PERSONAL).exists())

    def test_no_personal_asset_anywhere_in_a_new_instance(self):
        instance = self.tmp / "inst"
        instance.mkdir()
        self.sync(instance)
        self.assertEqual(personal_files(instance), [])

    def test_existing_personal_file_in_the_instance_is_left_untouched(self):
        instance = self.tmp / "inst"
        (instance / "config").mkdir(parents=True)
        mine = b'{"terms": ["owner-only"]}\n'
        (instance / PERSONAL).write_bytes(mine)
        self.sync(instance)
        self.assertEqual((instance / PERSONAL).read_bytes(), mine)

    def test_convention_excludes_every_personal_path_of_a_fake_kit(self):
        kit = self.tmp / "kit"
        (kit / "bin").mkdir(parents=True)
        shutil.copy2(SYNC, kit / "bin" / "sync-instance.sh")
        planted = {
            "config/project.json": False,
            "config/notes.personal.json": True,
            "config/personal/terms.json": True,
            "lib/tool.py": False,
            "lib/helper.personal.py": True,
            "lib/personal/scratch.py": True,
            # negative controls: the word alone, outside the convention, is synced
            "config/personal-notes.json": False,
            "lib/impersonal.py": False,
        }
        for rel in planted:
            (kit / rel).parent.mkdir(parents=True, exist_ok=True)
            (kit / rel).write_text("x\n", encoding="utf-8")
        instance = self.tmp / "inst"
        instance.mkdir()
        proc = subprocess.run(["bash", str(kit / "bin" / "sync-instance.sh"), str(instance)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for rel, personal in planted.items():
            self.assertEqual((instance / rel).exists(), not personal, rel)
        self.assertEqual(personal_files(instance), [])

    def test_second_sync_is_a_no_op_and_still_excludes_it(self):
        instance = self.tmp / "inst"
        instance.mkdir()
        self.sync(instance)
        proc = self.sync(instance)
        self.assertIn("0 copied/updated", proc.stdout)
        self.assertIn("0 config files added", proc.stdout)
        self.assertFalse((instance / PERSONAL).exists())


class SyncInstanceBenchTests(unittest.TestCase):
    """benchmark-port S3: 08-benchmark/{lib,bin,protocols} reach <instance>/bench/."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-instance-bench-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.instance = self.tmp / "inst"
        self.instance.mkdir()

    def sync(self) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(SYNC), str(self.instance)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def test_bench_dirs_are_copied_byte_for_byte(self):
        proc = self.sync()
        for sub in ("lib", "bin", "protocols"):
            for src in (BENCH_ROOT / sub).rglob("*"):
                rel = src.relative_to(BENCH_ROOT / sub)
                if not src.is_file() or "__pycache__" in rel.parts or src.suffix == ".pyc":
                    continue
                dst = self.instance / "bench" / sub / rel
                self.assertTrue(dst.is_file(), f"missing bench/{sub}/{rel}")
                self.assertEqual(dst.read_bytes(), src.read_bytes())
        self.assertTrue((self.instance / "bench" / "lib" / "transcript_metrics.py").is_file())
        self.assertTrue((self.instance / "bench" / "protocols" / "pr-review-ab.md").is_file())
        self.assertIn("  + bench/lib/bench_cli.py\n", proc.stdout)
        self.assertEqual([p.name for p in (self.instance / "bench").iterdir() if p.name not in ("lib", "bin", "protocols")], [])

    def test_bench_files_keep_their_mode(self):
        self.sync()
        for rel in ("bin/pr-review-ab.sh", "lib/transcript_metrics.py"):
            self.assertEqual(os.stat(self.instance / "bench" / rel).st_mode, os.stat(BENCH_ROOT / rel).st_mode, rel)
        self.assertTrue(os.access(self.instance / "bench" / "bin" / "pr-review-ab.sh", os.X_OK))

    def test_bench_sync_skips_bytecode_overwrites_changes_and_never_deletes(self):
        self.sync()
        target = self.instance / "bench" / "lib" / "phase1_report.py"
        target.write_text("# stale\n", encoding="utf-8")
        own = self.instance / "bench" / "lib" / "my_module.py"
        own.write_text("# instance-only\n", encoding="utf-8")
        proc = self.sync()
        self.assertEqual(target.read_bytes(), (BENCH_ROOT / "lib" / "phase1_report.py").read_bytes())
        self.assertIn("  ~ bench/lib/phase1_report.py\n", proc.stdout)
        self.assertEqual(own.read_text(encoding="utf-8"), "# instance-only\n")
        self.assertEqual(list((self.instance / "bench").rglob("__pycache__")), [])
        self.assertEqual(list((self.instance / "bench").rglob("*.pyc")), [])

    def test_a_file_only_in_the_instance_bench_is_listed_as_kept(self):
        self.sync()
        (self.instance / "bench" / "protocols" / "mine.md").write_text("# mine\n", encoding="utf-8")
        kept = self.sync().stdout.split("only in the instance (kept as is):\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(kept.splitlines(), ["  bench/protocols/mine.md"])

    def test_tools_dirs_still_sync_as_before(self):
        proc = self.sync()
        for rel in ("lib/doctor.py", "bin/sync-instance.sh", "hooks/_common.py", "tests/test_sync_instance.py",
                    "schemas/findings.schema.json", "mcp/server.py"):
            self.assertEqual((self.instance / rel).read_bytes(), (TOOLS_ROOT / rel).read_bytes(), rel)
            self.assertEqual(os.stat(self.instance / rel).st_mode, os.stat(TOOLS_ROOT / rel).st_mode, rel)
            self.assertIn(f"  + {rel}\n", proc.stdout)
        self.assertFalse((self.instance / "08-benchmark").exists())
        own = self.instance / "lib" / "my_module.py"
        own.write_text("# instance-only\n", encoding="utf-8")
        (self.instance / "lib" / "doctor.py").write_text("# stale\n", encoding="utf-8")
        again = self.sync()
        self.assertIn("  ~ lib/doctor.py\n", again.stdout)
        self.assertEqual((self.instance / "lib" / "doctor.py").read_bytes(), (TOOLS_ROOT / "lib" / "doctor.py").read_bytes())
        self.assertIn("only in the instance (kept as is):\n  lib/my_module.py\n", again.stdout)
        self.assertRegex(again.stdout, r"\nsummary: \d+ copied/updated, \d+ unchanged, 0 config files added\. Next: \(cd ")


if __name__ == "__main__":
    unittest.main()
