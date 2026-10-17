"""bin/sync-instance.sh and personal assets (kit-init T8, S8, Log L12).

The sync copies code and every missing config file into an instance, but a
personal asset (by convention: a path component named `personal` or matching
`*.personal.*`) is never copied; an instance that already holds one keeps it
byte for byte."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.doctor import is_personal_path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
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


if __name__ == "__main__":
    unittest.main()
