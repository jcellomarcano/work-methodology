import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import baseline, cartography

TOOLS_ROOT = Path(__file__).resolve().parent.parent
CARTOGRAFIA_SH = TOOLS_ROOT / "bin" / "cartography.sh"

FAKE_SHA = "0test0000000000000000000000000000test00"

FAKE_METRICS = {
    "totals": {"files_count": 10, "loc": 500, "files_over_500": 1, "fun_count": 40, "var_count": 2},
}
FAKE_DEPS = {
    "violations": [{"file": "domain/Bad.kt", "line": 3, "import": "android.os.Bundle",
                     "from_node": "domain", "to_node": "android.os.Bundle", "rule": "domain-purity"}],
    "cycle_candidates": {
        "app-framework->app-ui": {"count": 2, "occurrences": ["a.kt:1", "b.kt:2"]},
        "app-ui->app-framework": {"count": 0, "occurrences": []},
    },
    "adapter_law_candidates": [{"file": "x.kt", "line": 1, "function": "f", "matches": ["y.kt"], "epistemic": "Inferido"}],
}


class ParseHotspotsTests(unittest.TestCase):
    def test_orders_by_count_desc_then_path_asc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hotspots.txt"
            path.write_text("   3 app/Foo.kt\n   3 app/Bar.kt\n  10 app/Baz.kt\n", encoding="utf-8")
            result = cartography.parse_hotspots(path, limit=10)
            self.assertEqual(
                result,
                [
                    {"path": "app/Baz.kt", "touches": 10},
                    {"path": "app/Bar.kt", "touches": 3},
                    {"path": "app/Foo.kt", "touches": 3},
                ],
            )

    def test_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hotspots.txt"
            path.write_text("\n".join(f"   {i} f{i}.kt" for i in range(1, 6)), encoding="utf-8")
            result = cartography.parse_hotspots(path, limit=2)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["touches"], 5)

    def test_missing_file_returns_empty_list_not_an_error(self):
        # negative control: with no hotspots file, an empty list, no exception.
        result = cartography.parse_hotspots(Path("/does/not/exist"))
        self.assertEqual(result, [])


class ParseConflictsTests(unittest.TestCase):
    def test_dedupes_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conflicts.txt"
            path.write_text("b.kt\na.kt\na.kt\n\n", encoding="utf-8")
            self.assertEqual(cartography.parse_conflicts(path), ["a.kt", "b.kt"])

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(cartography.parse_conflicts(Path("/does/not/exist")), [])


class BuildCartografiaTests(unittest.TestCase):
    def setUp(self):
        self.out_dir = TOOLS_ROOT / "out" / FAKE_SHA
        baseline.write_json(self.out_dir / "metrics.json", FAKE_METRICS)
        baseline.write_json(self.out_dir / "deps.json", FAKE_DEPS)

    def tearDown(self):
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_summaries_pulled_from_existing_metrics_and_deps(self):
        content = cartography.build_cartography(
            Path("."), FAKE_SHA, hotspots=[], conflicted_paths=[],
            target_branch="origin/develop", merge_tree_available=True,
        )
        self.assertEqual(content["shape_summary"]["files_over_500"], 1)
        self.assertEqual(content["dep_summary"]["violations_total"], 1)
        self.assertEqual(content["dep_summary"]["cycle_candidates"]["app-framework->app-ui"], 2)
        self.assertEqual(content["dep_summary"]["adapter_law_candidates_total"], 1)

    def test_merge_conflict_simulation_shape(self):
        content = cartography.build_cartography(
            Path("."), FAKE_SHA, hotspots=[], conflicted_paths=["f.kt"],
            target_branch="origin/develop", merge_tree_available=True,
        )
        self.assertEqual(content["merge_conflict_simulation"], {
            "target_branch": "origin/develop", "available": True, "conflicted_paths": ["f.kt"],
        })

    def test_determinism(self):
        first = cartography.build_cartography(Path("."), FAKE_SHA, [], [], "origin/develop", True)
        second = cartography.build_cartography(Path("."), FAKE_SHA, [], [], "origin/develop", True)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class RenderMarkdownTests(unittest.TestCase):
    def test_no_conflicts_message(self):
        payload = {
            "repo_sha": "abc",
            "shape_summary": {"files_count": 1},
            "dep_summary": {"violations_total": 0, "adapter_law_candidates_total": 0, "cycle_candidates": {}},
            "hotspots": [],
            "merge_conflict_simulation": {"target_branch": "origin/develop", "available": True, "conflicted_paths": []},
        }
        text = cartography.render_markdown(payload)
        self.assertIn("No conflicts.", text)

    def test_unavailable_merge_message(self):
        payload = {
            "repo_sha": "abc",
            "shape_summary": {},
            "dep_summary": {"violations_total": 0, "adapter_law_candidates_total": 0, "cycle_candidates": {}},
            "hotspots": [],
            "merge_conflict_simulation": {"target_branch": "origin/develop", "available": False, "conflicted_paths": []},
        }
        text = cartography.render_markdown(payload)
        self.assertIn("Could not simulate", text)

    def test_conflicted_paths_listed(self):
        payload = {
            "repo_sha": "abc",
            "shape_summary": {},
            "dep_summary": {"violations_total": 0, "adapter_law_candidates_total": 0, "cycle_candidates": {}},
            "hotspots": [],
            "merge_conflict_simulation": {"target_branch": "origin/develop", "available": True, "conflicted_paths": ["f.kt"]},
        }
        text = cartography.render_markdown(payload)
        self.assertIn("f.kt", text)


class MainCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)
        (self.repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo, check=True)
        self.repo_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        self.out_dir = TOOLS_ROOT / "out" / self.repo_sha
        baseline.write_json(self.out_dir / "metrics.json", FAKE_METRICS)
        baseline.write_json(self.out_dir / "deps.json", FAKE_DEPS)

    def tearDown(self):
        self.tmp.cleanup()
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_writes_json_and_md_with_merge_tree_unavailable(self):
        hotspots_file = Path(self.tmp.name) / "hotspots.txt"
        hotspots_file.write_text("   1 f.txt\n", encoding="utf-8")
        conflicts_file = Path(self.tmp.name) / "conflicts.txt"
        conflicts_file.write_text("", encoding="utf-8")

        code = cartography.main([
            str(self.repo), "--hotspots-file", str(hotspots_file), "--conflicts-file", str(conflicts_file),
            "--target-branch", "origin/develop", "--merge-tree-unavailable",
        ])
        self.assertEqual(code, 0)

        payload = json.loads((self.out_dir / "cartography.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["repo_sha"], self.repo_sha)
        self.assertEqual(payload["merge_conflict_simulation"]["available"], False)
        self.assertEqual(payload["hotspots"], [{"path": "f.txt", "touches": 1}])
        self.assertTrue((self.out_dir / "cartography.md").exists())


class BinCartografiaEndToEndTests(unittest.TestCase):
    """End to end with the real bash script: creates a develop branch that
    collides with the current one and checks that bin/cartography.sh really
    detects that conflict (uses git merge-tree, not a stub)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.repo / "settings.gradle").write_text("", encoding="utf-8")
        (self.repo / "f.kt").write_text("val x = 1\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("branch", "develop")

        (self.repo / "f.kt").write_text("val x = 2\n", encoding="utf-8")
        git("commit", "-q", "-am", "feature change")

        git("checkout", "-q", "develop")
        (self.repo / "f.kt").write_text("val x = 3\n", encoding="utf-8")
        git("commit", "-q", "-am", "develop change")
        git("checkout", "-q", "master")

        # bin/cartography.sh looks at origin/develop, not plain develop: a
        # "remote" is simulated by pointing the local ref origin/develop at develop.
        subprocess.run(
            ["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/develop", "refs/heads/develop"],
            check=True,
        )

        self.repo_sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.out_dir = TOOLS_ROOT / "out" / self.repo_sha

    def tearDown(self):
        self.tmp.cleanup()
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_detects_real_conflict_against_origin_develop(self):
        proc = subprocess.run(
            ["bash", str(CARTOGRAFIA_SH), str(self.repo)], capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads((self.out_dir / "cartography.json").read_text(encoding="utf-8"))
        mt = payload["merge_conflict_simulation"]
        self.assertTrue(mt["available"])
        self.assertEqual(mt["conflicted_paths"], ["f.kt"])
        self.assertGreaterEqual(len(payload["hotspots"]), 1)


if __name__ == "__main__":
    unittest.main()
