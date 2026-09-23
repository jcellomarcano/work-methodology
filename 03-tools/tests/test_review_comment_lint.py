import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import pr_scope, review_comment_lint

TOOLS = Path(__file__).resolve().parent.parent
CONFIG = json.loads((TOOLS / "config" / "review-comment.json").read_text(encoding="utf-8"))
LINT = json.loads((TOOLS / "config" / "output-lint.json").read_text(encoding="utf-8"))

GOOD = """`app/PaymentRetry.kt:52` @ 9f3e2a1
Qué sucede: cada reintento genera una clave de idempotencia nueva. Por qué sucede: `newIdempotencyKey()` se llama dentro del bucle. Cómo afecta: el proveedor ve dos pagos distintos y cobra dos veces. Cómo solucionar: generar la clave una vez, antes del bucle, y reutilizarla.

```kotlin
val key = newIdempotencyKey()
repeat(maxRetries) { attempt -> provider.charge(amount, key) }
```
"""


def status(result, rule_id):
    return next(r["status"] for r in result["rules"] if r["id"] == rule_id)


class ReviewCommentTests(unittest.TestCase):
    def test_good_comment_passes(self):
        result = review_comment_lint.check(GOOD, CONFIG, LINT)
        self.assertEqual(result["verdict"], "PASS", result)

    def test_missing_part_and_wrong_order_fail(self):
        no_part = GOOD.replace("Cómo afecta: el proveedor ve dos pagos distintos y cobra dos veces. ", "")
        self.assertEqual(status(review_comment_lint.check(no_part, CONFIG, LINT), "RC-01"), "FAIL")
        swapped = GOOD.replace("Qué sucede: cada reintento genera una clave de idempotencia nueva. Por qué sucede:", "Por qué sucede: cada reintento genera una clave nueva. Qué sucede:")
        self.assertEqual(status(review_comment_lint.check(swapped, CONFIG, LINT), "RC-01"), "FAIL")

    def test_english_labels_pass(self):
        text = GOOD.replace("Qué sucede:", "What happens:").replace("Por qué sucede:", "Why it happens:").replace("Cómo afecta:", "Impact:").replace("Cómo solucionar:", "How to fix:")
        self.assertEqual(status(review_comment_lint.check(text, CONFIG, LINT), "RC-01"), "PASS")

    def test_two_paragraphs_fail(self):
        text = GOOD.replace(" Cómo afecta:", "\n\nCómo afecta:")
        self.assertEqual(status(review_comment_lint.check(text, CONFIG, LINT), "RC-02"), "FAIL")

    def test_too_long_fails(self):
        text = GOOD.replace("Cómo afecta: el proveedor", "Cómo afecta: " + "palabra " * 40 + "el proveedor")
        self.assertEqual(status(review_comment_lint.check(text, CONFIG, LINT), "RC-03"), "FAIL")

    def test_reference_required(self):
        text = GOOD.replace("`app/PaymentRetry.kt:52` @ 9f3e2a1\n", "")
        result = review_comment_lint.check(text, CONFIG, LINT)
        self.assertEqual(status(result, "RC-04"), "FAIL")

    def test_code_language_must_match_extension(self):
        wrong = GOOD.replace("```kotlin", "```python")
        self.assertEqual(status(review_comment_lint.check(wrong, CONFIG, LINT), "RC-05"), "FAIL")
        untagged = GOOD.replace("```kotlin", "```")
        self.assertEqual(status(review_comment_lint.check(untagged, CONFIG, LINT), "RC-05"), "FAIL")
        no_block = GOOD.split("```")[0]
        self.assertEqual(status(review_comment_lint.check(no_block, CONFIG, LINT), "RC-05"), "FAIL")
        unknown_ext = GOOD.replace("PaymentRetry.kt:52", "PaymentRetry.zig:52")
        self.assertEqual(status(review_comment_lint.check(unknown_ext, CONFIG, LINT), "RC-05"), "WARN")

    def test_filler_preamble_and_em_dash_fail(self):
        self.assertEqual(status(review_comment_lint.check("Buena pregunta. " + GOOD, CONFIG, LINT), "RC-06"), "FAIL")
        self.assertEqual(status(review_comment_lint.check(GOOD.replace("Cómo afecta: el", "Cómo afecta: cabe destacar que el"), CONFIG, LINT), "RC-06"), "FAIL")
        self.assertEqual(status(review_comment_lint.check(GOOD.replace("y cobra", "— y cobra"), CONFIG, LINT), "RC-06"), "FAIL")

    def test_scope_marks_base_drift_files_as_outside_pr(self):
        scope = {"pr_files": [{"path": "app/PaymentRetry.kt", "added": 3, "removed": 1}], "base_drift_files": ["app/Other.kt"]}
        self.assertEqual(status(review_comment_lint.check(GOOD, CONFIG, LINT, scope=scope), "RC-07"), "PASS")
        drift = GOOD.replace("app/PaymentRetry.kt:52", "app/Other.kt:10")
        self.assertEqual(status(review_comment_lint.check(drift, CONFIG, LINT, scope=scope), "RC-07"), "FAIL")
        self.assertEqual(status(review_comment_lint.check(GOOD, CONFIG, LINT), "RC-07"), "SKIP")

    def test_determinism(self):
        first = json.dumps(review_comment_lint.check(GOOD, CONFIG, LINT), sort_keys=True)
        second = json.dumps(review_comment_lint.check(GOOD, CONFIG, LINT), sort_keys=True)
        self.assertEqual(first, second)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class PrScopeTests(unittest.TestCase):
    def test_pr_files_vs_base_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "t@t")
            git(repo, "config", "user.name", "t")
            (repo / "a.kt").write_text("a\n", encoding="utf-8")
            (repo / "b.kt").write_text("b\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-q", "-m", "base")
            git(repo, "checkout", "-q", "-b", "feature")
            (repo / "a.kt").write_text("a\nchanged by pr\n", encoding="utf-8")
            git(repo, "commit", "-q", "-am", "pr: touch a")
            # the base moves forward after branching: b.kt changes on main, not in the PR
            git(repo, "checkout", "-q", "main")
            (repo / "b.kt").write_text("b\nchanged on main\n", encoding="utf-8")
            git(repo, "commit", "-q", "-am", "main: touch b")
            result = pr_scope.scope(repo, "main", "feature")
            self.assertEqual([f["path"] for f in result["pr_files"]], ["a.kt"])
            self.assertEqual(result["base_drift_files"], ["b.kt"])
            self.assertEqual(result["summary"]["commits"], 1)
            self.assertEqual(result["commits"][0]["subject"], "pr: touch a")
            self.assertEqual(len(result["merge_base"]), 12)
            # negative control: with no base drift, base_drift_files stays empty
            git(repo, "checkout", "-q", "feature")
            same = pr_scope.scope(repo, "main", "feature")
            self.assertEqual(same["base_drift_files"], ["b.kt"])
            git(repo, "checkout", "-q", "-b", "clean", "main")
            (repo / "c.kt").write_text("c\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-q", "-m", "pr2")
            clean = pr_scope.scope(repo, "main", "clean")
            self.assertEqual(clean["base_drift_files"], [])
            self.assertEqual([f["path"] for f in clean["pr_files"]], ["c.kt"])
            self.assertNotIn(tmp, json.dumps(clean))


if __name__ == "__main__":
    unittest.main()
