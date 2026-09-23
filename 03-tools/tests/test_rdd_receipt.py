"""The receipt lifecycle over a temporary git repo, a round outside the repo,
and a temporary receipts directory (METODO_RDD_DIR). Every state and every
lineage outcome has its case; negative controls are marked."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib import rdd_receipt as rr

TOOLS_ROOT = Path(__file__).resolve().parent.parent

CONFIG = {
    "shared_build_files": ["settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle"],
    "money_paths": ["payment/"],
    "invariant_prefix": "INV",
    "extra_invariant_tokens": [],
    "rdd": {"exempt_globs": ["**/*.md", "docs/**"], "tests_globs": ["**/src/test/**"], "low_max_changed_lines": 120,
            "lens_paths": {"flujo-critico": ["**/*Repository*.kt"]}},
}

CARD_LOW = """## Change Card
**Why**: the test requires it [Medido]
**For what**: UX [Medido]
**What it risks**: none [Medido]
**When**: now [Medido]
**How**: a change [Medido]
**How far**: domain/** [Medido]
**How we'll know**: green test [Medido]
**Invariant**: n/a
**Ticket**: no ticket
"""
CARD_HIGH = CARD_LOW.replace("**For what**: UX [Medido]", "**For what**: Data integrity [Medido]").replace("**Invariant**: n/a", "**Invariant**: INV-01")
CARD_MEDIUM = CARD_LOW.replace("**What it risks**: none [Medido]", "**What it risks**: UX, one screen [Medido]")

FINDINGS_OK = {"round": "r", "role": "challenger", "summary": "ok", "findings": [
    {"id": "F-01", "lens": "simplicidad", "claim": "c", "attack": "a", "failure_scenario": "f", "evidence": ["x.kt:1"],
     "verdict": "OK", "epistemic": "Probado", "simpler_alternative": "none"}]}
FINDINGS_ROTO = {"round": "r", "role": "challenger", "summary": "roto", "findings": [
    dict(FINDINGS_OK["findings"][0], id="F-02", verdict="ROTO")]}
BLIND_CLOSED = {"round": "r", "role": "blind-spot-adversary", "summary": "x", "blind_spots": [
    {"id": "B-01", "what_nobody_looks_at": "w", "why_it_matters": "y", "where_it_should_live": "z", "state": "CERRADO",
     "proposed_owner": "n/a", "epistemic": "Inferido"}]}
BLIND_OPEN = {"round": "r", "role": "blind-spot-adversary", "summary": "x", "blind_spots": [
    dict(BLIND_CLOSED["blind_spots"][0], id="B-02", state="ABIERTO CON DUEÑO", proposed_owner="owner")]}
VERIFICATION_PASS = {"change_card_id": "c", "battery": ["t"], "verdict": "PASS", "evidence": ["e"]}
VERIFICATION_FAIL = dict(VERIFICATION_PASS, verdict="FAIL")
VERIFICATION_INC = dict(VERIFICATION_PASS, verdict="INCONCLUSIVE")


def _rulings(**ids):
    return {"round": "r", "role": "judge", "rulings": [
        {"finding_id": fid, "ruling": ruling, "evidence": ["e"], "epistemic": "Probado"} for fid, ruling in ids.items()]}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class ReceiptFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rdd-receipt-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "domain").mkdir()
        (self.repo / "domain" / "Foo.kt").write_text("class Foo\n", encoding="utf-8")
        (self.repo / "README.md").write_text("readme\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "checkout", "-q", "-b", "feature")
        self.round_dir = self.tmp / "round-t"
        self.round_dir.mkdir()
        self.receipts = self.tmp / "rdd"
        os.environ["METODO_RDD_DIR"] = str(self.receipts)

    def tearDown(self):
        os.environ.pop("METODO_RDD_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _commit(self, rel: str, content: str, msg: str = "change") -> str:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", msg)
        return rr.tree_sha(self.repo)

    def _card(self, text: str, name: str = "001-change-card.md") -> Path:
        path = self.round_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def _artifact(self, name: str, doc) -> Path:
        path = self.round_dir / name
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def _start(self, card=None, **kw):
        return rr.start(self.repo, "main", self.round_dir, card, config=CONFIG, **kw)

    def _capture_scripts(self, tree):
        for role in ("script:role_contract", "script:comment_gate", "script:docs_lint"):
            rr.capture(tree, role, self._artifact(f"{role.split(':')[1]}.json", {"verdict": "PASS"}), self.repo)


class StartTests(ReceiptFixture):
    def test_start_binds_to_tree_and_writes_file(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        receipt = self._start(self._card(CARD_LOW))
        self.assertEqual(receipt["tree_sha"], _git(self.repo, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(receipt["risk"]["tier"], "low")
        self.assertEqual(receipt["state"], "started")
        self.assertTrue(rr.receipt_path(tree).exists())
        text = rr.receipt_path(tree).read_text(encoding="utf-8")
        self.assertNotIn(str(Path.home()), text)

    def test_dirty_tree_is_refused_and_writes_nothing(self):
        # negative control
        self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        (self.repo / "domain" / "Foo.kt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(rr.ReceiptError) as ctx:
            self._start(self._card(CARD_LOW))
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(ctx.exception.next_step, "COMMIT_FIRST")
        self.assertFalse(self.receipts.exists())

    def test_start_is_idempotent(self):
        self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        first = self._start(self._card(CARD_LOW))
        second = self._start(self._card(CARD_LOW))
        self.assertEqual(first, second)

    def test_medium_without_card_is_refused(self):
        self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        with self.assertRaises(rr.ReceiptError) as ctx:
            self._start(None)
        self.assertEqual(ctx.exception.exit_code, 2)

    def test_docs_only_is_exempt_and_approved_at_once(self):
        self._commit("README.md", "readme v2\n")
        receipt = self._start(None)
        self.assertEqual(receipt["risk"]["tier"], "exempt")
        self.assertEqual((receipt["state"], receipt["verdict"]), ("finalized", "approved"))

    def test_money_path_is_high_with_consent_pending(self):
        self._commit("payment/Pay.kt", "class Pay\n")
        receipt = self._start(self._card(CARD_HIGH))
        self.assertEqual(receipt["risk"]["tier"], "high")
        self.assertEqual(receipt["risk"]["consent"], "pending")


class CaptureTests(ReceiptFixture):
    def test_capture_records_sha_and_summary(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        receipt, entry = rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        self.assertEqual(receipt["state"], "captured")
        self.assertEqual(entry["summary"], {"findings": {"OK": 1}})
        self.assertEqual(entry["schema"], "findings")
        self.assertEqual(entry["artifact"], "f.json")

    def test_capture_with_handoff_writes_numbered_handoff(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        _, entry = rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo, handoff_to="judge")
        self.assertTrue(entry["handoff"].endswith("-challenger-to-judge.json"))
        self.assertTrue((self.round_dir / entry["handoff"]).exists())

    def test_invalid_artifact_is_refused_with_exit_one(self):
        # negative control
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        with self.assertRaises(rr.ReceiptError) as ctx:
            rr.capture(tree, "challenger", self._artifact("bad.json", {"round": 1}), self.repo)
        self.assertEqual(ctx.exception.exit_code, 1)
        self.assertEqual(rr.load_receipt(tree)["captures"], [])

    def test_capture_after_tree_moved_is_refused(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        self._commit("domain/Foo.kt", "class Foo { val x = 2 }\n")
        with self.assertRaises(rr.ReceiptError) as ctx:
            rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_card_changed_blocks_capture_and_finalizes_inconclusive(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        card = self._card(CARD_MEDIUM)
        self._start(card)
        card.write_text(CARD_MEDIUM + "\nnota nueva\n", encoding="utf-8")
        with self.assertRaises(rr.ReceiptError) as ctx:
            rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        self.assertEqual(ctx.exception.next_step, "FINALIZE")
        self.assertEqual(rr.finalize(tree)["verdict"], "inconclusive")

    def test_high_tier_adversary_needs_consent(self):
        tree = self._commit("payment/Pay.kt", "class Pay\n")
        self._start(self._card(CARD_HIGH))
        with self.assertRaises(rr.ReceiptError) as ctx:
            rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        self.assertEqual(ctx.exception.next_step, "ACKNOWLEDGE_CONSENT")
        rr.acknowledge(tree, "consent", "ok")
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)


class FinalizeTests(ReceiptFixture):
    def _medium(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        self._capture_scripts(tree)
        return tree

    def test_low_tier_with_scripts_is_approved(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_LOW))
        self._capture_scripts(tree)
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "approved")
        with self.assertRaises(rr.ReceiptError):
            rr.finalize(tree)

    def test_missing_required_role_is_inconclusive(self):
        tree = self._medium()
        self.assertEqual(rr.finalize(tree)["verdict"], "inconclusive")

    def test_medium_clean_round_is_approved(self):
        tree = self._medium()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")

    def test_roto_without_judge_rejects(self):
        tree = self._medium()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_ROTO), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        receipt = rr.finalize(tree)
        self.assertEqual(receipt["verdict"], "rejected")
        self.assertIn("F-02", receipt["verdict_reasons"][0])

    def test_verifier_fail_rejects_and_inconclusive_stays_inconclusive(self):
        tree = self._medium()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_FAIL), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "rejected")
        tree2 = self._commit("domain/Foo.kt", "class Foo { val x = 3 }\n")
        self._start(self._card(CARD_MEDIUM))
        self._capture_scripts(tree2)
        rr.capture(tree2, "challenger", self._artifact("f2.json", FINDINGS_OK), self.repo)
        rr.capture(tree2, "verifier", self._artifact("v2.json", VERIFICATION_INC), self.repo)
        self.assertEqual(rr.finalize(tree2)["verdict"], "inconclusive")

    def test_truncated_capture_is_inconclusive(self):
        tree = self._medium()
        rr.capture(tree, "challenger", self._artifact("f.json", dict(FINDINGS_OK, truncated=True, not_covered=["C"])), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "inconclusive")

    def _high(self):
        tree = self._commit("payment/Pay.kt", "class Pay\n")
        self._start(self._card(CARD_HIGH))
        rr.acknowledge(tree, "consent", "ok")
        self._capture_scripts(tree)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        return tree

    def test_high_roto_refuted_by_judge_is_approved(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_ROTO), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_CLOSED), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-02": "REFUTED"})), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")

    def test_high_unresolved_ruling_escalates(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_CLOSED), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-01": "NEEDS_BENCH"})), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "escalated")

    def test_high_open_blind_spot_without_ruling_escalates(self):
        tree = self._high()
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_OK), self.repo)
        rr.capture(tree, "blind-spot-adversary", self._artifact("b.json", BLIND_OPEN), self.repo)
        rr.capture(tree, "judge", self._artifact("j.json", _rulings(**{"F-01": "CONFIRMED"})), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "escalated")


class LineageTests(ReceiptFixture):
    def _rejected_medium(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        card = self._card(CARD_MEDIUM)
        self._start(card)
        self._capture_scripts(tree)
        rr.capture(tree, "challenger", self._artifact(f"f-{tree[:6]}.json", FINDINGS_ROTO), self.repo)
        rr.capture(tree, "verifier", self._artifact(f"v-{tree[:6]}.json", VERIFICATION_PASS), self.repo)
        self.assertEqual(rr.finalize(tree)["verdict"], "rejected")
        return tree, card

    def test_supersedes_once_then_escalate(self):
        old, card = self._rejected_medium()
        new = self._commit("domain/Foo.kt", "class Foo { val x = 2 }\n")
        receipt = self._start(card, supersedes=old)
        self.assertEqual((receipt["correction_index"], receipt["supersedes"]), (1, old))
        self.assertEqual(rr.load_receipt(old)["superseded_by"], new)
        self._capture_scripts(new)
        rr.capture(new, "challenger", self._artifact("f2.json", FINDINGS_ROTO), self.repo)
        rr.capture(new, "verifier", self._artifact("v2.json", VERIFICATION_PASS), self.repo)
        self.assertEqual(rr.finalize(new)["verdict"], "rejected")
        self._commit("domain/Foo.kt", "class Foo { val x = 3 }\n")
        with self.assertRaises(rr.ReceiptError) as ctx:
            self._start(card, supersedes=new)
        self.assertEqual((ctx.exception.exit_code, ctx.exception.next_step), (3, "ESCALATE"))

    def test_supersedes_requires_same_card(self):
        # negative control
        old, card = self._rejected_medium()
        self._commit("domain/Foo.kt", "class Foo { val x = 2 }\n")
        card.write_text(CARD_MEDIUM.replace("a change", "a different change"), encoding="utf-8")
        with self.assertRaises(rr.ReceiptError) as ctx:
            self._start(card, supersedes=old)
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_inherit_from_when_candidate_files_unchanged(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_LOW))
        self._capture_scripts(tree)
        self.assertEqual(rr.finalize(tree)["verdict"], "approved")
        new = self._commit("other.txt", "unrelated\n", "rebase-like")
        receipt = self._start(self._card(CARD_LOW), inherit_from=tree)
        self.assertEqual((receipt["verdict"], receipt["inherited_from"]), ("approved", tree))
        self.assertEqual(receipt["tree_sha"], new)

    def test_inherit_from_refused_when_candidate_changed(self):
        # negative control
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_LOW))
        self._capture_scripts(tree)
        rr.finalize(tree)
        self._commit("domain/Foo.kt", "class Foo { val x = 9 }\n")
        with self.assertRaises(rr.ReceiptError) as ctx:
            self._start(self._card(CARD_LOW), inherit_from=tree)
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_amend_message_only_keeps_receipt(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        receipt = self._start(self._card(CARD_LOW))
        _git(self.repo, "commit", "-q", "--amend", "-m", "otro mensaje")
        self.assertEqual(rr.tree_sha(self.repo), tree)
        self.assertEqual(rr.status(self.repo, config=CONFIG)["receipt"]["state"], receipt["state"])


class AcknowledgeValidateTests(ReceiptFixture):
    def test_acknowledge_never_turns_rejected_into_approved(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        self._capture_scripts(tree)
        rr.capture(tree, "challenger", self._artifact("f.json", FINDINGS_ROTO), self.repo)
        rr.capture(tree, "verifier", self._artifact("v.json", VERIFICATION_PASS), self.repo)
        rr.finalize(tree)
        receipt = rr.acknowledge(tree, "push-without-receipt", "hotfix")
        self.assertEqual(receipt["verdict"], "rejected")
        self.assertEqual(receipt["owner_ack"]["decision"], "push-without-receipt")

    def test_unreviewed_creates_receipt(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        receipt = rr.acknowledge(tree, "unreviewed", "docs typo", self.repo, self.round_dir)
        self.assertEqual((receipt["risk"]["tier"], receipt["verdict"]), ("exempt", "approved"))
        self.assertEqual(receipt["owner_ack"]["decision"], "unreviewed")

    def test_validate_detects_tampered_artifact(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_MEDIUM))
        artifact = self._artifact("f.json", FINDINGS_OK)
        rr.capture(tree, "challenger", artifact, self.repo)
        self.assertEqual(rr.validate_receipt(rr.receipt_path(tree))["verdict"], "PASS")
        artifact.write_text(json.dumps(FINDINGS_ROTO), encoding="utf-8")
        result = rr.validate_receipt(rr.receipt_path(tree))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("sha256 mismatch", result["errors"][0])

    def test_status_reports_next_step(self):
        self.assertEqual(rr.status(self.repo, config=CONFIG)["next"], "START")
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        self._start(self._card(CARD_LOW))
        self.assertEqual(rr.status(self.repo, config=CONFIG)["next"], "CAPTURE_OR_FINALIZE")
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        self.assertEqual(rr.status(self.repo, config=CONFIG)["next"], "COMMIT_FIRST")

    def test_cli_exit_codes(self):
        tree = self._commit("domain/Foo.kt", "class Foo { val x = 1 }\n")
        cfg = self.tmp / "project.json"
        cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
        card = self._card(CARD_LOW)
        self.assertEqual(rr.main(["--config", str(cfg), "start", "--repo", str(self.repo), "--base", "main",
                                  "--round-dir", str(self.round_dir), "--change-card", str(card)]), 0)
        self.assertEqual(rr.main(["--config", str(cfg), "finalize", "--tree", tree]), 1)
        self.assertEqual(rr.main(["--config", str(cfg), "finalize", "--tree", tree]), 3)
        self.assertEqual(rr.main(["--config", str(cfg), "validate", "--receipt", str(rr.receipt_path(tree))]), 0)
