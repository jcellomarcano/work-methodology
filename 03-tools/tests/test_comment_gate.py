import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import comment_gate as cg


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")


def _commit(root: Path, path: str, content: str, message: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


BASE = """package pay

class Pay {
    fun boot() {
        val retryBudget = 3
        val x = 1
        start()
    }

    fun paymentToken(): String = "tok"
}
"""

WITH_COMMENTS = """package pay

class Pay {
    fun boot() {
        // Wizzit reorders the JCE table (WZ-015), so the guard runs before the kernel boots.
        guard()
        // set the retry budget
        val retryBudget = 3
        // val old = legacy(); old.run()
        val x = 1 // legacy default
        // removed the old timer because it leaked
        start()
        // NEEDS-COMMENT: the SDK requires the clock to be set
        clock()
        // el reloj tiene que estar puesto antes que el kernel
        tick()
        // key=deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
        seal()
    }

    /** Returns the token a caller needs to start a sale. */
    fun paymentToken(): String = "tok"
}
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)
        self.base = _commit(self.root, "src/Pay.kt", BASE, "base")
        self.with_comments = _commit(self.root, "src/Pay.kt", WITH_COMMENTS, "comments")

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, rng: str) -> dict:
        return cg.analyze(self.root, range_arg=rng)


class AnalyzeTests(Fixture):
    def test_lists_every_new_comment_with_its_statement(self):
        result = self.analyze(f"{self.base}..{self.with_comments}")
        by_line = {c["line"]: c for c in result["comments"]}
        self.assertEqual(result["summary"]["total"], 9)
        self.assertEqual(result["summary"]["markers"], 1)
        self.assertEqual(result["summary"]["kdoc"], 1)
        self.assertEqual(by_line[5]["statement"], "guard()")
        self.assertEqual(by_line[5]["flags"], [])
        self.assertEqual(by_line[5]["kind"], "line")

    def test_flags_are_deterministic_signals_not_verdicts(self):
        result = self.analyze(f"{self.base}..{self.with_comments}")
        by_line = {c["line"]: c for c in result["comments"]}
        self.assertIn("restates_code", by_line[7]["flags"])       # "set the retry budget" vs val retryBudget
        self.assertIn("commented_out_code", by_line[9]["flags"])  # val old = legacy(); old.run()
        self.assertTrue(by_line[10]["inline"])                    # val x = 1 // legacy default
        self.assertEqual(by_line[10]["statement"], "val x = 1")
        self.assertIn("narrates_diff", by_line[11]["flags"])
        self.assertEqual(by_line[13]["kind"], "marker")
        self.assertIn("non_english", by_line[15]["flags"])
        self.assertIn("has_secret_shape", by_line[17]["flags"])
        self.assertNotIn("verdict", by_line[5])

    def test_kdoc_on_public_surface_is_a_kdoc_candidate(self):
        result = self.analyze(f"{self.base}..{self.with_comments}")
        kdoc = [c for c in result["comments"] if c["kind"] == "kdoc"][0]
        self.assertTrue(kdoc["kdoc_candidate"])
        self.assertEqual(kdoc["statement"], 'fun paymentToken(): String = "tok"')
        self.assertEqual(kdoc["words"], 10)
        self.assertEqual(kdoc["sentences"], 1)

    def test_negative_control_code_only_diff_has_zero_comments(self):
        code_only = _commit(self.root, "src/Pay.kt", WITH_COMMENTS + "\nclass More { fun run() = 1 }\n", "code")
        result = self.analyze(f"{self.with_comments}..{code_only}")
        self.assertEqual(result["summary"], {
            "total": 0, "markers": 0, "kdoc": 0, "flagged": 0, "action_tags": 0, "kdoc_flagged": 0,
        })
        self.assertEqual(result["comments"], [])

    def test_old_comments_are_not_judged(self):
        # negative control: the base already has the comments; a diff that only adds code does not list them
        code_only = _commit(self.root, "src/Pay.kt", WITH_COMMENTS.replace("start()", "start()\n        more()"), "more")
        result = self.analyze(f"{self.with_comments}..{code_only}")
        self.assertEqual(result["summary"]["total"], 0)

    def test_scope_glob_filters_paths(self):
        result = cg.analyze(self.root, range_arg=f"{self.base}..{self.with_comments}", scope_globs=["other/**"])
        self.assertEqual(result["summary"]["total"], 0)

    def test_string_literal_with_slashes_is_not_a_comment(self):
        content = BASE.replace('"tok"', '"https://example.com/x"')
        sha = _commit(self.root, "src/Pay.kt", content, "url")
        result = self.analyze(f"{self.with_comments}..{sha}")
        self.assertEqual(result["summary"]["total"], 0)

    def test_determinism_two_runs_identical(self):
        first = json.dumps(self.analyze(f"{self.base}..{self.with_comments}"), sort_keys=True)
        second = json.dumps(self.analyze(f"{self.base}..{self.with_comments}"), sort_keys=True)
        self.assertEqual(first, second)
        self.assertNotIn("timestamp", first)
        self.assertNotIn(str(self.root), first)

    def test_worktree_mode_sees_uncommitted_comment(self):
        (self.root / "src" / "Pay.kt").write_text(
            WITH_COMMENTS.replace("        seal()\n", "        seal()\n        // why: the master needs the ack first\n        finish()\n"),
            encoding="utf-8",
        )
        result = cg.analyze(self.root, worktree=self.root)
        self.assertEqual(result["summary"]["total"], 1)
        self.assertTrue(result["repo_dirty"])
        self.assertEqual(result["comments"][0]["statement"], "finish()")

    def test_line_added_to_an_existing_comment_block_lists_the_whole_block(self):
        # the diff touches a line of an existing comment: the whole comment is judged again
        grown = WITH_COMMENTS.replace("        // removed the old timer because it leaked\n",
                                      "        // removed the old timer because it leaked\n        // and the master never noticed\n")
        sha = _commit(self.root, "src/Pay.kt", grown, "grow")
        result = self.analyze(f"{self.with_comments}..{sha}")
        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["comments"][0]["line"], 11)
        self.assertIn("never noticed", result["comments"][0]["text"])


class VerifyTests(Fixture):
    def test_comment_only_edits_and_marker_removal_pass(self):
        fixed = (WITH_COMMENTS
                 .replace("        // set the retry budget\n", "")
                 .replace("        // NEEDS-COMMENT: the SDK requires the clock to be set\n",
                          "        // MineSec signs attestation with the wall clock, so an unset clock fails it.\n"))
        sha = _commit(self.root, "src/Pay.kt", fixed, "mechanic")
        result = cg.verify(self.root, f"{self.with_comments}..{sha}", range_arg=f"{self.base}..{self.with_comments}")
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["offending"], [])
        self.assertEqual(result["remaining_markers"], [])

    def test_code_line_change_fails(self):
        touched = WITH_COMMENTS.replace("val retryBudget = 3", "val retryBudget = 4")
        sha = _commit(self.root, "src/Pay.kt", touched, "oops")
        result = cg.verify(self.root, f"{self.with_comments}..{sha}")
        # negative control: a changed statement never passes as a comment-only change
        self.assertEqual(result["verdict"], "FAIL")
        reasons = {o["reason"] for o in result["offending"]}
        self.assertEqual(reasons, {"code_line_removed", "code_line_added"})

    def test_remaining_marker_fails(self):
        only_delete = WITH_COMMENTS.replace("        // set the retry budget\n", "")
        sha = _commit(self.root, "src/Pay.kt", only_delete, "partial")
        result = cg.verify(self.root, f"{self.with_comments}..{sha}", range_arg=f"{self.base}..{self.with_comments}")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["offending"], [])
        self.assertEqual(len(result["remaining_markers"]), 1)
        self.assertIn("NEEDS-COMMENT", result["remaining_markers"][0]["text"])

    def test_non_source_file_change_fails(self):
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "readme")
        sha = _git(self.root, "rev-parse", "HEAD")
        result = cg.verify(self.root, f"{self.with_comments}..{sha}")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["offending"][0]["reason"], "non_source_file_changed")


class MainTests(Fixture):
    def test_main_prints_sorted_json_and_exit_codes(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cg.main(["--repo", str(self.root), "--range", f"{self.base}..{self.with_comments}"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(list(payload.keys()), sorted(payload.keys()))
        for key in ("schema_version", "tool_sha", "tool_versions", "repo_sha", "repo_dirty"):
            self.assertIn(key, payload)

    def test_verify_exit_code_is_one_on_fail(self):
        import io
        from contextlib import redirect_stdout
        touched = WITH_COMMENTS.replace("val x = 1", "val x = 2")
        sha = _commit(self.root, "src/Pay.kt", touched, "oops")
        with redirect_stdout(io.StringIO()):
            code = cg.main(["--repo", str(self.root), "--verify", f"{self.with_comments}..{sha}"])
        self.assertEqual(code, 1)


# ---------------------------------------------------- DOC-002 / DOC-003 (round-comments-research-18sep)

TICKET_KEYS = ["DEV", "POS"]


def _describe_snippet(source: str, ticket_keys=TICKET_KEYS):
    """Runs the real scan_comments + describe over a small standalone
    source snippet (no git needed), the way the auditor ruling measured
    every one of its 28 rows. Returns every comment entry, in order."""
    lines = source.splitlines()
    return [cg.describe("T.kt", c, lines, ticket_keys=ticket_keys) for c in cg.scan_comments(source)]


# Auditor ruling, section 3.3: name, KDoc text, the statement it sits over, expected kdoc_* flags.
KDOC_ROWS = [
    ("KD-TP-1", "A `Foo` is a wrapper around the kernel.", "class Foo {", {"kdoc_banned_opener"}),
    ("KD-TP-2", "This method returns the balance in cents.", "fun balance(): Int", {"kdoc_banned_opener"}),
    ("KD-FN-1", "This is the only entry point the gateway exposes.", "fun open() {}", {"kdoc_banned_opener"}),
    ("KD-FN-2", "The `Foo` is a wrapper around the Wizzit kernel.", "class Foo {", {"kdoc_banned_opener"}),
    ("KD-FN-4", "Save the record.", "fun save() {}", set()),
    ("KD-FP-1", "A `PaymentAttempt` is an immutable row; the fold never mutates it.",
     "fun foldAttempts() {}", set()),
    ("KD-FP-2", "This property is read by the ZeroMQ thread, so it must stay @Volatile.",
     "var state: Int = 0", {"kdoc_banned_opener"}),
    ("KD-FP-3", "An amount is a value class, never a Double.", "fun charge(amount: Amount) {}", set()),
    ("KD-OK-1", "Tag key used to cache the original text size.", "val TAG_KEY = 1", set()),
    ("KD-OK-2", "Applies the current DsTheme text size factor to this TextView.",
     "fun applyTheme() {}", set()),
    ("KD-OK-3", "An amount is a value class, never a Double.",
     "value class Amount(val cents: Int)", {"kdoc_banned_opener"}),
]


class Doc002KdocOpenerTests(unittest.TestCase):
    def test_kdoc_opener_rows(self):
        for name, text, statement, expected in KDOC_ROWS:
            with self.subTest(name):
                source = f"/**\n * {text}\n */\n{statement}\n"
                entries = _describe_snippet(source)
                self.assertEqual(len(entries), 1, name)
                entry = entries[0]
                self.assertEqual(entry["kind"], "kdoc", name)
                self.assertEqual(entry["statement"], statement, name)
                kdoc_flags = {f for f in entry["flags"] if f.startswith("kdoc_")}
                self.assertEqual(kdoc_flags, expected, name)


# Auditor ruling, section 3.3: name, source snippet, expected tag count, expected action_tag_* flags.
ACTION_TAG_ROWS = [
    ("TD-FN-1",
     "// The SDK wedges when two sessions overlap.\n// TODO fix before the next kernel bump.\n"
     "fun retry() {}\n",
     1, {"action_tag_untracked"}),
    ("TD-FN-2",
     "/** Refreshes the token.\n * TODO(DEV-1) drop after v2. */\nfun refresh() {}\n",
     1, {"action_tag_malformed"}),
    ("TD-FN-3", "val a = 1 // see DEV-1, TODO: remove please\n", 0, set()),
    ("TD-FN-4", "// Todo: aniquilar\nfun run() {}\n", 1, {"action_tag_untracked"}),
    ("TD-FN-5", "/* FIXME: this is a hack */\nfun run() {}\n", 1,
     {"action_tag_forbidden", "action_tag_untracked"}),
    ("TD-FP-1", "// TODO is the literal placeholder the master sends for an unknown SKU.\nfun run() {}\n",
     0, set()),
    ("TD-FP-2", "// XXX-XX-1234 is the masked PAN the receipt prints.\nfun run() {}\n", 0, set()),
    ("TD-FP-3", "// TODO(DEV-123):no space after the colon, ticket is present.\nfun run() {}\n",
     1, {"action_tag_malformed"}),
    ("TD-OK-1", "// TODO(DEV-123): restore the presence check.\nfun run() {}\n", 1, set()),
    ("TD-OK-2", "// TODO(POS-225): restore the presence check.\nfun run() {}\n", 1, set()),
    ("TD-BAD-1", "// TODO(John): restore the presence check.\nfun run() {}\n", 1, {"action_tag_bad_identifier"}),
    ("TD-BAD-2", "// TODO(JIRA-9): restore the presence check.\nfun run() {}\n", 1, {"action_tag_bad_identifier"}),
    ("TD-REPO-1", "//TODO KEPLER: modificar animacion\nfun run() {}\n", 1, {"action_tag_untracked"}),
    ("TD-REPO-2", "//TODO: aniquilar\nfun run() {}\n", 1, {"action_tag_untracked"}),
    ("TD-MARK", "// NEEDS-COMMENT why the retry is bounded\nfun run() {}\n", 0, set()),
    ("TD-CODE", "val x = TODO() // not implemented yet\n", 0, set()),
]


class Doc003ActionTagTests(unittest.TestCase):
    def test_action_tag_rows(self):
        for name, source, tag_count, expected_flags in ACTION_TAG_ROWS:
            with self.subTest(name):
                entries = _describe_snippet(source)
                comment = next(e for e in entries if e["kind"] != "marker" or name == "TD-MARK")
                self.assertEqual(len(comment["action_tags"]), tag_count, name)
                action_flags = {f for f in comment["flags"] if f.startswith("action_tag_")}
                self.assertEqual(action_flags, expected_flags, name)

    def test_td_mark_keeps_marker_kind(self):
        entries = _describe_snippet("// NEEDS-COMMENT why the retry is bounded\nfun run() {}\n")
        self.assertEqual(entries[0]["kind"], "marker")

    def test_td_fn_2_kind_stays_kdoc_not_a_new_kind(self):
        # F-06, upheld: a tag inside a KDoc never strips its kind or its DOC-002 flags.
        entries = _describe_snippet("/** Refreshes the token.\n * TODO(DEV-1) drop after v2. */\nfun refresh() {}\n")
        self.assertEqual(entries[0]["kind"], "kdoc")

    def test_ticket_keys_config_absent_degrades_to_shape_only(self):
        # TD-CFG: TD-OK-2 with ticket_keys absent -> shape-only fallback, no bad_identifier for an unknown key.
        entries = _describe_snippet(
            "// TODO(POS-225): restore the presence check.\nfun run() {}\n", ticket_keys=None,
        )
        self.assertEqual(len(entries[0]["action_tags"]), 1)
        self.assertEqual(entries[0]["flags"], [])


class Doc003NegativeControlTests(unittest.TestCase):
    def test_spanish_word_todo_mid_sentence_is_not_a_tag(self):
        # The Spanish word "todo" is common prose; it is only ever a tag when it opens the line.
        entries = _describe_snippet(
            "// el reloj tiene que estar puesto antes que el kernel para todo el sistema\nfun run() {}\n"
        )
        self.assertEqual(entries[0]["action_tags"], [])
        self.assertEqual([f for f in entries[0]["flags"] if f.startswith("action_tag_")], [])

    def test_well_formed_kdoc_with_no_block_tags_is_clean(self):
        entries = _describe_snippet(
            "/**\n * Returns the token a caller needs to start a sale.\n */\nfun paymentToken(): String\n"
        )
        self.assertEqual(entries[0]["kind"], "kdoc")
        self.assertEqual(entries[0]["flags"], [])
        self.assertEqual(entries[0]["block_tags"], [])
        self.assertEqual(entries[0]["empty_block_tags"], [])


class TicketKeysConfigTests(unittest.TestCase):
    def test_missing_config_file_returns_none(self):
        self.assertIsNone(cg._load_ticket_keys(Path("/no/such/config-does-not-exist.json")))

    def test_missing_ticket_keys_field_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "project.json"
            config_path.write_text(json.dumps({"docs_root": "~/x"}), encoding="utf-8")
            self.assertIsNone(cg._load_ticket_keys(config_path))

    def test_present_ticket_keys_field_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "project.json"
            config_path.write_text(json.dumps({"ticket_keys": ["DEV", "POS"]}), encoding="utf-8")
            self.assertEqual(cg._load_ticket_keys(config_path), ["DEV", "POS"])


class FollowUpFU1PendingTests(unittest.TestCase):
    """FU-1 (auditor ruling section 7): two NARRATES_DIFF_RE false positives on the
    d8cc5b2e1^..d8cc5b2e1 baseline. Named and not fixed in this round; pinned here as
    expected failures so a future fix is caught by this test flipping to a pass."""

    @unittest.expectedFailure
    def test_fu1_adjective_is_not_a_diff_narration(self):
        text = ("Fixed neutral gradient used for the payment process screen background "
                "so it never repeats the app bar color.")
        self.assertNotIn("narrates_diff", cg._flags("line", text, "", 0))

    @unittest.expectedFailure
    def test_fu1_imperative_is_not_a_diff_narration(self):
        text = ("Update only the purchase entry. A Seglan offline refund may have queued "
                "additional states before the ack arrived.")
        self.assertNotIn("narrates_diff", cg._flags("line", text, "", 0))


if __name__ == "__main__":
    unittest.main()
