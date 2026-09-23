"""lib/engram_bridge.py: no binary, memory disabled, a success, and where the
project name comes from. The engram subprocess is mocked throughout: this
test never writes to the real ~/.engram/engram.db."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import engram_bridge  # noqa: E402


class _Proc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class EngramBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engram-bridge-"))
        self.config = self.tmp / "project.json"
        self._write({"memory": {"enabled": True, "engram_project": "from-config"}})
        self.env = mock.patch.dict(os.environ, {"METODO_PROJECT_CONFIG": str(self.config)}, clear=False)
        self.env.start()
        os.environ.pop("ENGRAM_PROJECT", None)
        # tests/__init__.py sets METODO_MEMORY=off for the whole suite; these
        # tests are the ones that need it on, with the binary mocked away.
        self.memory_off = os.environ.pop("METODO_MEMORY", None)

    def _restore_memory_switch(self):
        if self.memory_off is not None:
            os.environ["METODO_MEMORY"] = self.memory_off

    def tearDown(self):
        self._restore_memory_switch()
        self.env.stop()

    def _write(self, data):
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def test_no_binary_on_path_is_a_silent_false(self):
        with mock.patch("shutil.which", return_value=None), mock.patch("subprocess.run") as run:
            self.assertFalse(engram_bridge.save("t", "b"))
            run.assert_not_called()

    def test_memory_disabled_is_a_silent_false(self):
        self._write({"memory": {"enabled": False}})
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertFalse(engram_bridge.save("t", "b"))
            run.assert_not_called()

    def test_missing_memory_block_is_a_silent_false(self):
        self._write({})
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertFalse(engram_bridge.save("t", "b"))
            run.assert_not_called()

    def test_success_builds_the_expected_command(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=_Proc(0)) as run:
            self.assertTrue(engram_bridge.save("receipt abc123 approved", "body",
                                               kind="decision", topic_key="metodo/receipt/abc123"))
        argv = run.call_args[0][0]
        self.assertEqual(argv[:4], ["/usr/bin/engram", "save", "receipt abc123 approved", "body"])
        self.assertEqual(argv[argv.index("--type") + 1], "decision")
        self.assertEqual(argv[argv.index("--project") + 1], "from-config")
        self.assertEqual(argv[argv.index("--topic") + 1], "metodo/receipt/abc123")

    def test_no_topic_key_omits_the_flag(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=_Proc(0)) as run:
            self.assertTrue(engram_bridge.save("t", "b"))
        self.assertNotIn("--topic", run.call_args[0][0])

    def test_a_non_zero_exit_is_false(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=_Proc(1)):
            self.assertFalse(engram_bridge.save("t", "b"))

    def test_a_subprocess_failure_never_raises(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", side_effect=OSError("boom")):
            self.assertFalse(engram_bridge.save("t", "b"))

    def test_project_falls_back_to_the_env_then_to_the_repo_name(self):
        self._write({"memory": {"enabled": True, "engram_project": ""}})
        with mock.patch.dict(os.environ, {"ENGRAM_PROJECT": "from-env"}, clear=False):
            self.assertEqual(engram_bridge.resolve_project(), "from-env")
        os.environ.pop("ENGRAM_PROJECT", None)
        repo = self.tmp / "my-repo"
        repo.mkdir()
        self.assertEqual(engram_bridge.resolve_project(repo=repo), "my-repo")

    def test_the_off_switch_beats_an_enabled_config(self):
        os.environ["METODO_MEMORY"] = "off"
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertFalse(engram_bridge.save("t", "b"))
            run.assert_not_called()

    def test_an_explicit_project_wins_over_the_config(self):
        self.assertEqual(engram_bridge.resolve_project("explicit"), "explicit")


if __name__ == "__main__":
    unittest.main()
