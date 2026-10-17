import io
import json
import tempfile
import unittest
import unittest.mock
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from lib import review_comment_post

GOOD_EN = (
    "`app/Foo.kt:10` @ abc1234\n"
    "What happens: the balance goes negative. Why it happens: the guard is missing. "
    "Impact: seats are lost silently. How to fix: add the guard back.\n"
    "\n"
    "```kotlin\n"
    "val guard = true\n"
    "```\n"
)

RENDERED_EN = (
    "`app/Foo.kt:10` @ abc1234\n\n"
    "- **What happens:** the balance goes negative.\n"
    "- **Why it happens:** the guard is missing.\n"
    "- **Impact:** seats are lost silently.\n"
    "- **How to fix:** add the guard back.\n\n"
    "```kotlin\n"
    "val guard = true\n"
    "```\n"
)

GOOD_ES = (
    "`app/Foo.kt:10` @ abc1234\n"
    "Qué sucede: el saldo se vuelve negativo. Por qué sucede: falta la guarda. "
    "Cómo afecta: se pierden plazas en silencio. Cómo solucionar: reponer la guarda.\n"
    "\n"
    "```kotlin\n"
    "val guard = true\n"
    "```\n"
)

RENDERED_ES = (
    "`app/Foo.kt:10` @ abc1234\n\n"
    "- **Qué sucede:** el saldo se vuelve negativo.\n"
    "- **Por qué sucede:** falta la guarda.\n"
    "- **Cómo afecta:** se pierden plazas en silencio.\n"
    "- **Cómo solucionar:** reponer la guarda.\n\n"
    "```kotlin\n"
    "val guard = true\n"
    "```\n"
)

PR_LEVEL = (
    "General finding, no single line owns it.\n"
    "What happens: the balance goes negative. Why it happens: the guard is missing. "
    "Impact: seats are lost silently. How to fix: add the guard back.\n"
    "\n"
    "```kotlin\n"
    "val guard = true\n"
    "```\n"
)


class RenderTests(unittest.TestCase):
    def test_render_golden_english(self):
        self.assertEqual(review_comment_post.render(GOOD_EN), RENDERED_EN)

    def test_render_spanish_labels(self):
        self.assertEqual(review_comment_post.render(GOOD_ES), RENDERED_ES)

    def test_render_refuses_paragraph_missing_a_label(self):
        broken = GOOD_EN.replace(
            "Impact: seats are lost silently. ", ""
        )
        with self.assertRaises(ValueError) as ctx:
            review_comment_post.render(broken)
        self.assertIn("Impact:", str(ctx.exception))


class AnchorTests(unittest.TestCase):
    def test_anchor_for_inline_comment(self):
        self.assertEqual(review_comment_post.anchor(GOOD_EN), {"path": "app/Foo.kt", "line": 10})

    def test_anchor_is_none_for_pr_level_comment(self):
        self.assertIsNone(review_comment_post.anchor(PR_LEVEL))


class PayloadTests(unittest.TestCase):
    def test_payload_has_inline_only_when_anchored(self):
        rendered = review_comment_post.render(GOOD_EN)
        pld = review_comment_post.payload(GOOD_EN, rendered)
        self.assertEqual(pld["content"]["raw"], rendered)
        self.assertEqual(pld["inline"], {"path": "app/Foo.kt", "to": 10})

    def test_payload_has_no_inline_for_pr_level_comment(self):
        rendered = review_comment_post.render(PR_LEVEL)
        pld = review_comment_post.payload(PR_LEVEL, rendered)
        self.assertNotIn("inline", pld)


class CliTests(unittest.TestCase):
    def _write_comment(self, tmp: Path) -> Path:
        path = tmp / "comment.md"
        path.write_text(GOOD_EN, encoding="utf-8")
        return path

    def test_dry_run_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            comment = self._write_comment(Path(tmp))
            with unittest.mock.patch("urllib.request.urlopen", side_effect=AssertionError("network hit")):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = review_comment_post.main(
                        ["post", str(comment), "--repo", "ws/repo", "--pr", "42"]
                    )
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["action"], "dry-run")
            self.assertEqual(result["method"], "POST")

    def test_dry_run_uses_put_with_comment_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            comment = self._write_comment(Path(tmp))
            with unittest.mock.patch("urllib.request.urlopen", side_effect=AssertionError("network hit")):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = review_comment_post.main(
                        ["post", str(comment), "--repo", "ws/repo", "--pr", "42", "--comment-id", "7"]
                    )
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["method"], "PUT")
            self.assertIn("/comments/7", result["url"])

    def test_token_never_appears_in_dry_run_or_error_output(self):
        secret = "sk-super-secret-token"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            comment = self._write_comment(tmp_path)
            token_file = tmp_path / "token"
            token_file.write_text(secret, encoding="utf-8")

            dry_out = io.StringIO()
            with unittest.mock.patch("urllib.request.urlopen", side_effect=AssertionError("network hit")):
                with redirect_stdout(dry_out):
                    review_comment_post.main(
                        ["post", str(comment), "--repo", "ws/repo", "--pr", "1", "--token-file", str(token_file)]
                    )
            self.assertNotIn(secret, dry_out.getvalue())

            error_out, error_err = io.StringIO(), io.StringIO()
            http_error = urllib.error.HTTPError(
                "https://api.bitbucket.org/x", 400, "Bad Request", None,
                io.BytesIO(b'{"error":{"message":"nope"}}'),
            )
            with unittest.mock.patch("urllib.request.urlopen", side_effect=http_error):
                with redirect_stdout(error_out), redirect_stderr(error_err):
                    code = review_comment_post.main(
                        ["post", str(comment), "--repo", "ws/repo", "--pr", "1",
                         "--token-file", str(token_file), "--confirm"]
                    )
            self.assertEqual(code, 1)
            self.assertNotIn(secret, error_out.getvalue())
            self.assertNotIn(secret, error_err.getvalue())
            self.assertIn("nope", error_out.getvalue() + error_err.getvalue())


if __name__ == "__main__":
    unittest.main()
