import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import baseline


class WriteJsonTests(unittest.TestCase):
    def test_sorts_keys_and_appends_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            baseline.write_json(path, {"b": 1, "a": 2, "c": {"z": 1, "y": 2}})
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertFalse(text.endswith("\n\n"))
            # negative control: if keys were not sorted, 'a' would not appear before 'b'
            self.assertLess(text.index('"a"'), text.index('"b"'))
            self.assertLess(text.index('"y"'), text.index('"z"'))
            self.assertEqual(json.loads(text), {"b": 1, "a": 2, "c": {"z": 1, "y": 2}})

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "out.json"
            baseline.write_json(path, {"x": 1})
            self.assertTrue(path.exists())

    def test_determinism_byte_identical_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Path(tmp) / "a.json", Path(tmp) / "b.json"
            payload = {"totals": {"loc": 10, "files": 3}, "name": "x"}
            baseline.write_json(p1, payload)
            baseline.write_json(p2, payload)
            self.assertEqual(p1.read_bytes(), p2.read_bytes())

    def test_no_ascii_escaping_for_spanish_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            baseline.write_json(path, {"campo": "Qué arriesga"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("Qué arriesga", text)
            self.assertNotIn("\\u", text)


class LoadJsonTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            payload = {"a": [1, 2, 3], "b": {"c": True}}
            baseline.write_json(path, payload)
            self.assertEqual(baseline.load_json(path), payload)


class GitHeadShaTests(unittest.TestCase):
    def test_matches_git_rev_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
            (Path(tmp) / "f.txt").write_text("x")
            subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)
            expected = subprocess.run(
                ["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            self.assertEqual(baseline.git_head_sha(tmp), expected)

    def test_raises_when_no_commits_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            # negative control: with no commits there is no deterministic HEAD to return
            with self.assertRaises(subprocess.CalledProcessError):
                baseline.git_head_sha(tmp)


class SaveBaselineTests(unittest.TestCase):
    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline.save_baseline(tmp, "deadbeef", {"x": 1})
            # negative control: the second write without --force must fail
            with self.assertRaises(FileExistsError):
                baseline.save_baseline(tmp, "deadbeef", {"x": 2})
            self.assertEqual(baseline.load_json(Path(tmp) / "deadbeef.json"), {"x": 1})

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline.save_baseline(tmp, "deadbeef", {"x": 1})
            baseline.save_baseline(tmp, "deadbeef", {"x": 2}, force=True)
            self.assertEqual(baseline.load_json(Path(tmp) / "deadbeef.json"), {"x": 2})


class DeltaTests(unittest.TestCase):
    def test_added_removed_changed(self):
        before = {"totals": {"loc": 100, "vars": 5}}
        after = {"totals": {"loc": 120, "vars": 5, "bangbang": 2}}
        result = baseline.delta(before, after)
        self.assertEqual(result["added"], ["totals.bangbang"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["changed"], {"totals.loc": {"before": 100, "after": 120, "delta": 20}})

    def test_ignores_unchanged_numeric_leaves(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 2}
        result = baseline.delta(before, after)
        self.assertEqual(result, {"added": [], "removed": [], "changed": {}})

    def test_ignores_booleans_as_non_numeric(self):
        before = {"flag": True}
        after = {"flag": False}
        # negative control: a bool must not be treated as a numeric metric
        result = baseline.delta(before, after)
        self.assertEqual(result, {"added": [], "removed": [], "changed": {}})

    def test_removed_key(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1}
        result = baseline.delta(before, after)
        self.assertEqual(result["removed"], ["b"])


class BaseEnvelopeTests(unittest.TestCase):
    def test_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
            (Path(tmp) / "f.txt").write_text("x")
            subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)
            envelope = baseline.base_envelope(tmp, "repo123", {"python": "3.11.9"}, repo_dirty=False)
            self.assertEqual(
                set(envelope),
                {"schema_version", "tool_sha", "tool_versions", "repo_sha", "repo_dirty"},
            )
            self.assertEqual(envelope["repo_sha"], "repo123")
            self.assertIs(envelope["repo_dirty"], False)


class _GitRepo:
    """Test helper: a real, initialized git repo in a tmpdir."""

    def __init__(self, path: Path):
        self.path = path
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
        (path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


class IsRepoDirtyTests(unittest.TestCase):
    def test_clean_repo_is_not_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            _GitRepo(Path(tmp))
            self.assertFalse(baseline.is_repo_dirty(tmp))

    def test_modified_tracked_file_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _GitRepo(Path(tmp))
            (repo.path / "f.txt").write_text("changed")
            self.assertTrue(baseline.is_repo_dirty(tmp))

    def test_untracked_dot_claude_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _GitRepo(Path(tmp))
            worktree_file = repo.path / ".claude" / "worktrees" / "x" / "f.txt"
            worktree_file.parent.mkdir(parents=True)
            worktree_file.write_text("agent worktree junk")
            # negative control: untracked junk under .claude/ does not count as dirty
            self.assertFalse(baseline.is_repo_dirty(tmp))

    def test_untracked_file_outside_dot_claude_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _GitRepo(Path(tmp))
            (repo.path / "new.txt").write_text("untracked")
            self.assertTrue(baseline.is_repo_dirty(tmp))


class SaveBaselineDirtyTests(unittest.TestCase):
    def test_refuses_dirty_repo_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            # negative control: dirty and without --force must never write anything
            with self.assertRaises(RuntimeError):
                baseline.save_baseline(tmp, "deadbeef", {"x": 1}, repo_dirty=True)
            self.assertFalse((Path(tmp) / "deadbeef.json").exists())
            self.assertFalse((Path(tmp) / "deadbeef-dirty.json").exists())

    def test_force_writes_dirty_suffixed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = baseline.save_baseline(tmp, "deadbeef", {"x": 1}, repo_dirty=True, force=True)
            self.assertEqual(path.name, "deadbeef-dirty.json")
            self.assertFalse((Path(tmp) / "deadbeef.json").exists())

    def test_clean_repo_keeps_plain_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = baseline.save_baseline(tmp, "deadbeef", {"x": 1}, repo_dirty=False)
            self.assertEqual(path.name, "deadbeef.json")


class DeltaToolDriftTests(unittest.TestCase):
    def test_matching_tool_sha_computes_normal_delta(self):
        before = {"tool_sha": "aaa", "tool_versions": {"python": "3.11"}, "totals": {"loc": 10}}
        after = {"tool_sha": "aaa", "tool_versions": {"python": "3.11"}, "totals": {"loc": 20}}
        result = baseline.delta(before, after)
        self.assertEqual(result["changed"], {"totals.loc": {"before": 10, "after": 20, "delta": 10}})

    def test_mismatched_tool_sha_is_void(self):
        before = {"tool_sha": "aaa", "tool_versions": {"python": "3.11"}, "totals": {"loc": 10}}
        after = {"tool_sha": "bbb", "tool_versions": {"python": "3.11"}, "totals": {"loc": 20}}
        result = baseline.delta(before, after)
        # negative control: two different tool_sha values must never produce a numeric delta
        self.assertEqual(result["verdict"], "VOID: tool drift")
        self.assertNotIn("changed", result)
        self.assertEqual(result["tool_sha_before"], "aaa")
        self.assertEqual(result["tool_sha_after"], "bbb")

    def test_mismatched_tool_versions_is_void(self):
        before = {"tool_sha": "aaa", "tool_versions": {"python": "3.11"}, "totals": {"loc": 10}}
        after = {"tool_sha": "aaa", "tool_versions": {"python": "3.12"}, "totals": {"loc": 20}}
        result = baseline.delta(before, after)
        self.assertEqual(result["verdict"], "VOID: tool drift")

    def test_allow_tool_drift_computes_delta_anyway(self):
        before = {"tool_sha": "aaa", "tool_versions": {"python": "3.11"}, "totals": {"loc": 10}}
        after = {"tool_sha": "bbb", "tool_versions": {"python": "3.11"}, "totals": {"loc": 20}}
        result = baseline.delta(before, after, allow_tool_drift=True)
        self.assertEqual(result["changed"], {"totals.loc": {"before": 10, "after": 20, "delta": 10}})

    def test_bare_dicts_without_tool_sha_are_never_drift(self):
        # compatibility: payloads with no header (the ones old tests use)
        # must never fall into the VOID branch.
        result = baseline.delta({"a": 1}, {"a": 2})
        self.assertEqual(result, {"added": [], "removed": [], "changed": {"a": {"before": 1, "after": 2, "delta": 1}}})


if __name__ == "__main__":
    unittest.main()
