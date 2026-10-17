"""Tests for git_metrics on a synthetic repository built in a temp dir."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import git_metrics as gm  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")


def git(repo, *args, date=None):
    env = dict(ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, files: dict, msg: str, date: str):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, date=date)


def build_repo(root: pathlib.Path) -> pathlib.Path:
    repo = root / "sample"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"src/A.kt": "class A\n"}, "feat: add A", "2026-08-01T10:00:00Z")
    commit(repo, {"src/A.kt": "class A { fun a() {} }\n", "src/test/ATest.kt": "class ATest\n"},
           "fix(core): a with test", "2026-08-02T10:00:00Z")
    git(repo, "switch", "-q", "-c", "feat/b")
    commit(repo, {"src/B.kt": "class B\n"}, "feat(b): add B", "2026-08-03T10:00:00Z")
    commit(repo, {"README.md": "docs\n"}, "update readme", "2026-08-04T10:00:00Z")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feat/b", "feat/b", date="2026-08-06T10:00:00Z")
    return repo


class GitMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = build_repo(pathlib.Path(self.tmp.name))
        self.result = gm.analyze_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_shape(self):
        commits = self.result["commits"]
        self.assertEqual(len(commits), 5)
        by_subject = {c["subject"]: c for c in commits}
        self.assertTrue(by_subject["feat: add A"]["conventional"])
        self.assertFalse(by_subject["update readme"]["conventional"])
        fix = by_subject["fix(core): a with test"]
        self.assertTrue(fix["touches_tests"])
        self.assertTrue(fix["touches_code"])
        self.assertEqual(fix["files"], 2)
        self.assertEqual(by_subject["update readme"]["touches_code"], False)
        self.assertEqual(by_subject["update readme"]["touches_docs"], True)
        self.assertTrue(by_subject["Merge feat/b"]["is_merge"])
        self.assertNotIn("author", json.dumps(commits))

    def test_summary_rates(self):
        s = self.result["summary"]
        self.assertEqual(s["commits"], 4)  # merges excluded
        self.assertEqual(s["conventional_rate"], 0.75)
        self.assertEqual(s["code_commits_with_tests_rate"], round(1 / 3, 6))
        self.assertEqual(s["first_date"], "2026-08-01")
        self.assertEqual(s["last_date"], "2026-08-06")

    def test_merge_lead_time(self):
        merges = self.result["merges"]
        self.assertEqual(len(merges), 1)
        m = merges[0]
        self.assertEqual(m["commits"], 2)
        self.assertEqual(m["lead_time_days"], 3.0)
        self.assertEqual(m["date"], "2026-08-06")

    def test_cli_is_deterministic(self):
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as od:
                out = pathlib.Path(od) / "g.json"
                subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "git_metrics.py"),
                                "--repo", str(self.repo), "--out", str(out)],
                               check=True, capture_output=True, env=ENV)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])
        payload = json.loads(outs[0])
        self.assertEqual(payload["repos"][0]["name"], "sample")
        self.assertNotIn(self.tmp.name, outs[0].decode())


if __name__ == "__main__":
    unittest.main()
