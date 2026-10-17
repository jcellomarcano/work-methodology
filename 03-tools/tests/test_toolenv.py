import tempfile
import unittest
from pathlib import Path

from lib import baseline, toolenv


class ToolVersionsTests(unittest.TestCase):
    def test_reports_unavailable_when_no_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            versions = toolenv.tool_versions(root)
            self.assertEqual(versions["pmd"], "unavailable")
            self.assertEqual(versions["detekt"], "unavailable")
            self.assertEqual(versions["ktlint"], "unavailable")
            self.assertTrue(versions["python"])
            self.assertTrue(versions["java"])

    def test_reads_versions_from_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline.write_json(root / "config" / "tools.lock.json", {
                "pmd": {"status": "ok", "version": "7.27.0"},
                "detekt": {"status": "unavailable", "version": "1.23.8"},
            })
            versions = toolenv.tool_versions(root)
            self.assertEqual(versions["pmd"], "7.27.0")
            # negative control: status "unavailable" must never report the version as if it were ok
            self.assertEqual(versions["detekt"], "unavailable")
            self.assertEqual(versions["ktlint"], "unavailable")

    def test_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline.write_json(root / "config" / "tools.lock.json", {"pmd": {"status": "ok", "version": "1"}})
            first = toolenv.tool_versions(root)
            second = toolenv.tool_versions(root)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
