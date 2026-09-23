import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import cite_check

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "config" / "output-lint.json").read_text(encoding="utf-8"))
TECH = "Respuesta.\n\n## Detalle técnico\n\n"


def make_repo(tmp: Path) -> str:
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.name", "t"], check=True)
    (tmp / "a").mkdir()
    (tmp / "a" / "b.kt").write_text("\n".join(f"line {i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp), "commit", "-q", "-m", "first"], check=True)
    sha = subprocess.run(["git", "-C", str(tmp), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    # the working tree grows to 20 lines with no commit: distinguishes "exists today" from "existed at the sha"
    (tmp / "a" / "b.kt").write_text("\n".join(f"line {i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    return sha


def status_of(result, **match):
    return [r["status"] for r in result["refs"] if all(r.get(k) == v for k, v in match.items())]


class CiteCheckTests(unittest.TestCase):
    def test_file_refs_against_worktree_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            sha = make_repo(repo)
            text = TECH + (
                f"- `a/b.kt:5` declara la clave [Medido]\n"
                f"- `a/b.kt:15` hoy existe [Medido]\n"
                f"- `a/b.kt:15` @ {sha} no existía en ese commit [Medido]\n"
                f"- `a/b.kt:3-4` @ {sha} sí [Medido]\n"
                f"- `missing.kt:1` no existe [Medido]\n"
                f"- `a/b.kt:1` @ deadbeef sha desconocido [Medido]\n"
            )
            result = cite_check.check(text, CONFIG, repo=repo)
            self.assertEqual(status_of(result, start=5, sha=None), ["OK"])
            self.assertEqual(status_of(result, start=15, sha=None), ["OK"])
            self.assertEqual(status_of(result, start=15, sha=sha), ["MISSING"])
            self.assertEqual(status_of(result, start=3, sha=sha), ["OK"])
            self.assertEqual(status_of(result, path="missing.kt"), ["MISSING"])
            self.assertEqual(status_of(result, sha="deadbeef"), ["MISSING"])
            self.assertEqual(result["verdict"], "FAIL")
            self.assertEqual(result["uncited_measured"], [])

    def test_clean_reply_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            sha = make_repo(repo)
            text = TECH + f"- `a/b.kt:2` @ {sha} [Medido]\n- inferencia sin cita, permitida [Inferido]\n"
            result = cite_check.check(text, CONFIG, repo=repo)
            self.assertEqual(result["verdict"], "PASS", result)

    def test_url_unverified_offline_and_measured_without_cite_warns(self):
        text = TECH + "- \"quote\" (https://example.org/x) [Medido]\n- salida pegada: 26 tests OK [Medido]\n- viñeta [Probado]\n"
        result = cite_check.check(text, CONFIG, repo=None)
        self.assertEqual(status_of(result, kind="url"), ["UNVERIFIED"])
        self.assertEqual(len(result["uncited_measured"]), 2)
        self.assertEqual(result["verdict"], "WARN")
        # negative control: with no technical layer there is nothing to check and no FAIL is invented
        self.assertEqual(cite_check.check("Respuesta.\n", CONFIG)["verdict"], "PASS")

    def test_file_ref_without_repo_is_unverified_not_missing(self):
        result = cite_check.check(TECH + "- `a/b.kt:5` [Medido]\n", CONFIG, repo=None)
        self.assertEqual(status_of(result, path="a/b.kt"), ["UNVERIFIED"])
        self.assertEqual(result["verdict"], "WARN")

    def test_determinism_and_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            make_repo(repo)
            text = TECH + "- `a/b.kt:5` [Medido]\n- `nope.kt:1` [Medido]\n"
            first = json.dumps(cite_check.check(text, CONFIG, repo=repo), sort_keys=True)
            second = json.dumps(cite_check.check(text, CONFIG, repo=repo), sort_keys=True)
            self.assertEqual(first, second)
            self.assertNotIn(tmp, first)

    def test_main_exit_code(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            make_repo(repo)
            reply = repo / "r.md"
            reply.write_text(TECH + "- `nope.kt:1` [Medido]\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = cite_check.main([str(reply), "--repo", str(repo)])
            self.assertEqual(code, 1)
            reply.write_text(TECH + "- `a/b.kt:1` [Medido]\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cite_check.main([str(reply), "--repo", str(repo)])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out.getvalue())["tool_sha"]), 12)


if __name__ == "__main__":
    unittest.main()
