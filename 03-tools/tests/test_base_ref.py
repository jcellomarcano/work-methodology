"""lib/base_ref.py: the one place the base ref is resolved. Order: explicit
ref, config test_sectors.base_ref, the remote's default branch
(refs/remotes/origin/HEAD), and only then origin/develop."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS_ROOT = Path(__file__).resolve().parent.parent
BASE_REF_PY = TOOLS_ROOT / "lib" / "base_ref.py"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(root: Path, origin_head: str | None = None) -> Path:
    """A one-commit repo; with origin_head, refs/remotes/origin/<name> exists
    and refs/remotes/origin/HEAD points at it (what `git clone` leaves)."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    if origin_head:
        _git(repo, "update-ref", f"refs/remotes/origin/{origin_head}", "HEAD")
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{origin_head}")
    return repo


class ResolveTests(unittest.TestCase):
    def setUp(self):
        from lib import base_ref
        self.base_ref = base_ref
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_base_ref_wins_over_origin_head(self):
        repo = make_repo(self.root, origin_head="main")
        config = {"test_sectors": {"base_ref": "origin/release"}}
        self.assertEqual(self.base_ref.resolve(repo, config), "origin/release")

    def test_unset_config_falls_back_to_origin_head(self):
        repo = make_repo(self.root, origin_head="main")
        self.assertEqual(self.base_ref.resolve(repo, {}), "origin/main")
        self.assertEqual(self.base_ref.resolve(repo, {"test_sectors": {"base_ref": ""}}), "origin/main")

    def test_neither_falls_back_to_origin_develop(self):
        repo = make_repo(self.root)
        self.assertEqual(self.base_ref.resolve(repo, {}), "origin/develop")

    def test_not_a_repo_falls_back_to_origin_develop(self):
        # negative control: a non-git directory is not an error.
        self.assertEqual(self.base_ref.resolve(self.root, {}), "origin/develop")

    def test_explicit_ref_wins_over_everything(self):
        repo = make_repo(self.root, origin_head="main")
        config = {"test_sectors": {"base_ref": "origin/release"}}
        self.assertEqual(self.base_ref.resolve(repo, config, explicit="feature/x"), "feature/x")

    def test_load_config_honors_metodo_project_config(self):
        cfg = self.root / "alt.json"
        cfg.write_text(json.dumps({"test_sectors": {"base_ref": "origin/alt"}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"METODO_PROJECT_CONFIG": str(cfg)}):
            self.assertEqual(self.base_ref.load_config(), {"test_sectors": {"base_ref": "origin/alt"}})

    def test_load_config_missing_or_broken_is_empty(self):
        broken = self.root / "broken.json"
        broken.write_text("{", encoding="utf-8")
        self.assertEqual(self.base_ref.load_config(self.root / "nope.json"), {})
        self.assertEqual(self.base_ref.load_config(broken), {})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args, env_extra=None):
        env = dict(os.environ, **(env_extra or {}))
        return subprocess.run([sys.executable, str(BASE_REF_PY), *args], capture_output=True, text=True, env=env)

    def test_cli_reads_active_config(self):
        repo = make_repo(self.root, origin_head="main")
        cfg = self.root / "project.json"
        cfg.write_text(json.dumps({"test_sectors": {"base_ref": "origin/release"}}), encoding="utf-8")
        proc = self._run(str(repo), env_extra={"METODO_PROJECT_CONFIG": str(cfg)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "origin/release")

    def test_cli_explicit_config_and_base(self):
        repo = make_repo(self.root, origin_head="main")
        cfg = self.root / "project.json"
        cfg.write_text("{}", encoding="utf-8")
        self.assertEqual(self._run(str(repo), "--config", str(cfg)).stdout.strip(), "origin/main")
        self.assertEqual(self._run(str(repo), "--config", str(cfg), "--base", "x/y").stdout.strip(), "x/y")


if __name__ == "__main__":
    unittest.main()
