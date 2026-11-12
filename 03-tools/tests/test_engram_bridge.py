"""lib/engram_bridge.py: no binary, memory disabled, a success, and where the
project name comes from. The engram subprocess is mocked throughout: this
test never writes to the real ~/.engram/engram.db."""
import io
import json
import os
import sys
import shutil
import subprocess
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
        self.addCleanup(shutil.rmtree, self.tmp, True)
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


SEARCH_OUTPUT = """Found 2 memories:

[1] #395 (decision) \u2014 Benchmark: PR review A/B runner ready
    **What**: body line that must not travel
    2026-10-13 17:13:13 | project: from-config | scope: project

[2] #2555 (discovery) \u2014 Receipt abc123 approved
    body
    2026-11-11 20:42:38 | project: from-config | scope: project

Update available: 3.4.0 -> 3.7.1
"""


class EngramRecallTests(unittest.TestCase):
    """The bridge reads memory back by reference: ids, kinds and titles,
    never bodies. Same silent degradation as save."""

    setUp = EngramBridgeTests.setUp
    tearDown = EngramBridgeTests.tearDown
    _write = EngramBridgeTests._write
    _restore_memory_switch = EngramBridgeTests._restore_memory_switch

    def _found(self, stdout=SEARCH_OUTPUT, returncode=0):
        proc = _Proc(returncode)
        proc.stdout = stdout
        return proc

    def test_recall_returns_ids_kinds_and_titles_never_bodies(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=self._found()) as run:
            found = engram_bridge.recall("receipt", limit=3)
        self.assertEqual(found, [{"id": 395, "kind": "decision", "title": "Benchmark: PR review A/B runner ready"},
                                 {"id": 2555, "kind": "discovery", "title": "Receipt abc123 approved"}])
        self.assertEqual(run.call_args[0][0], ["/usr/bin/engram", "search", "receipt", "--project", "from-config",
                                              "--limit", "3", "--match", "any"])
        # the limit holds even when engram prints more than it was asked for
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=self._found()):
            self.assertEqual([m["id"] for m in engram_bridge.recall("receipt", limit=1)], [395])

    def test_recall_is_empty_without_a_binary_when_disabled_or_on_failure(self):
        with mock.patch("shutil.which", return_value=None), mock.patch("subprocess.run") as run:
            self.assertEqual(engram_bridge.recall("receipt"), [])
            run.assert_not_called()
        self._write({"memory": {"enabled": False}})
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertEqual(engram_bridge.recall("receipt"), [])
            run.assert_not_called()
        self._write({"memory": {"enabled": True, "engram_project": "from-config"}})
        with mock.patch.dict(os.environ, {"METODO_MEMORY": "off"}, clear=False), \
             mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertEqual(engram_bridge.recall("receipt"), [])
            run.assert_not_called()
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=self._found(returncode=1)):
            self.assertEqual(engram_bridge.recall("receipt"), [])
        for failure in (OSError("boom"), subprocess.TimeoutExpired("engram", 3), ValueError("undecodable output")):
            with self.subTest(failure=type(failure).__name__), \
                 mock.patch("shutil.which", return_value="/usr/bin/engram"), \
                 mock.patch("subprocess.run", side_effect=failure):
                self.assertEqual(engram_bridge.recall("receipt"), [])
        # output that is not engram's list (or no output at all) is no pointer, never a raise
        for stdout in ("No memories found for: \"receipt\"\n", None):
            with self.subTest(stdout=stdout), mock.patch("shutil.which", return_value="/usr/bin/engram"), \
                 mock.patch("subprocess.run", return_value=self._found(stdout=stdout)):
                self.assertEqual(engram_bridge.recall("receipt"), [])

    def test_an_empty_query_or_a_limit_below_one_never_reaches_engram(self):
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), mock.patch("subprocess.run") as run:
            self.assertEqual(engram_bridge.recall("  "), [])
            self.assertEqual(engram_bridge.recall(None), [])
            self.assertEqual(engram_bridge.recall("receipt", limit=0), [])
            self.assertEqual(engram_bridge.recall("receipt", limit=-2), [])
            run.assert_not_called()

    def test_the_cli_recalls_as_sorted_json_and_still_saves(self):
        for argv in (["--recall", "receipt"], ["--recall=receipt", "--limit", "2", "--project", "other"]):
            with self.subTest(argv=argv), mock.patch("shutil.which", return_value="/usr/bin/engram"), \
                 mock.patch("subprocess.run", return_value=self._found()) as run, \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(engram_bridge.main(argv), 0)
            self.assertEqual([m["id"] for m in json.loads(out.getvalue())["recalled"]], [395, 2555])
            self.assertEqual(run.call_args[0][0][1:3], ["search", "receipt"])
        self.assertEqual(run.call_args[0][0][3:], ["--project", "other", "--limit", "2", "--match", "any"])
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=_Proc(0)) as run, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(engram_bridge.main(["--title", "t", "--body", "b"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"saved": True})
        self.assertEqual(run.call_args[0][0][:4], ["/usr/bin/engram", "save", "t", "b"])

    def test_a_recall_option_in_save_mode_is_still_a_usage_error(self):
        # `--limit` was refused before recall existed; adding recall must not make save accept it
        with mock.patch("shutil.which", return_value="/usr/bin/engram"), \
             mock.patch("subprocess.run", return_value=_Proc(0)) as run, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:
                engram_bridge.main(["--title", "t", "--body", "b", "--limit", "3"])
        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
