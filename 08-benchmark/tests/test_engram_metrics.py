"""Tests for engram_metrics over a synthetic `engram export` JSON file."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import engram_metrics as em  # noqa: E402

EXPORT = {
    "version": 1,
    "exported_at": "2026-10-13T16:00:00Z",
    "sessions": [
        {"id": "s1", "project": "alpha", "directory": "/x/alpha", "started_at": "2026-09-01 10:00:00", "ownership_mode": "project_owned"},
        {"id": "s2", "project": "alpha", "directory": "/x/alpha", "started_at": "2026-09-02 10:00:00", "ownership_mode": "shared"},
        {"id": "s3", "project": "beta", "directory": "/x/beta", "started_at": "2026-09-03 10:00:00", "ownership_mode": "project_owned"},
    ],
    "observations": [
        {"id": 1, "session_id": "s1", "project": "alpha", "type": "decision", "title": "pick X", "content": "secret text",
         "topic_key": "arch/x", "revision_count": 3, "pinned": 0, "scope": "project", "created_at": "2026-09-01 10:05:00"},
        {"id": 2, "session_id": "s1", "project": "alpha", "type": "session_summary", "title": "sum", "content": "secret",
         "topic_key": None, "revision_count": 1, "pinned": 0, "scope": "project", "created_at": "2026-09-01 11:00:00"},
        {"id": 3, "session_id": "s3", "project": "beta", "type": "bugfix", "title": "fix Y", "content": "secret",
         "topic_key": None, "revision_count": 1, "pinned": 1, "scope": "project", "created_at": "2026-09-03 10:30:00"},
    ],
    "prompts": [
        {"id": 1, "session_id": "s1", "project": "alpha", "content": "do X", "created_at": "2026-09-01 10:00:01"},
        {"id": 2, "session_id": "s2", "project": "alpha", "content": "do Z", "created_at": "2026-09-02 10:00:01"},
        {"id": 3, "session_id": "s3", "project": "beta", "content": "fix Y", "created_at": "2026-09-03 10:00:01"},
    ],
    "relations": [
        {"source_id": "o1", "target_id": "o2", "relation": "related", "judgment_status": "judged", "created_at": "2026-09-01 10:06:00"},
    ],
}


class EngramMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "export.json"
        self.path.write_text(json.dumps(EXPORT))
        self.result = em.analyze_export(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_projects(self):
        p = self.result["projects"]
        self.assertEqual(p["alpha"]["sessions"], 2)
        self.assertEqual(p["alpha"]["sessions_with_observations"], 1)
        self.assertEqual(p["alpha"]["observations"], 2)
        self.assertEqual(p["alpha"]["by_type"], {"decision": 1, "session_summary": 1})
        self.assertEqual(p["alpha"]["with_topic_key"], 1)
        self.assertEqual(p["alpha"]["upserted"], 1)
        self.assertEqual(p["alpha"]["prompts"], 2)
        self.assertEqual(p["alpha"]["first_session"], "2026-09-01")
        self.assertEqual(p["beta"]["pinned"], 1)

    def test_sessions_joinable(self):
        s = {x["session_id"]: x for x in self.result["sessions"]}
        self.assertEqual(s["s1"]["observations"], 2)
        self.assertEqual(s["s2"]["observations"], 0)
        self.assertEqual(s["s3"]["by_type"], {"bugfix": 1})
        self.assertEqual(s["s1"]["prompts"], 1)

    def test_totals_and_privacy(self):
        t = self.result["totals"]
        self.assertEqual(t["sessions"], 3)
        self.assertEqual(t["sessions_with_zero_observations"], 1)
        self.assertEqual(t["relations_by_relation"], {"related": 1})
        dump = json.dumps(self.result)
        self.assertNotIn("secret", dump)
        self.assertNotIn("do X", dump)
        self.assertNotIn("/x/alpha", dump)

    def test_cli_is_deterministic(self):
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                out = pathlib.Path(od) / "e.json"
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "engram_metrics.py"),
                                "--export", str(self.path), "--out", str(out)], check=True, capture_output=True)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        self.assertNotIn("exported_at", json.loads(outs[0]))


if __name__ == "__main__":
    unittest.main()
