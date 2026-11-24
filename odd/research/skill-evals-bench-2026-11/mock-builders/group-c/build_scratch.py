#!/usr/bin/env python3
"""Build the scratch repositories of the three scenarios and call the kit's real MCP server on them.

Usage: build_scratch.py WORK KIT
  WORK  an empty `mktemp -d` directory; everything is written under it
  KIT   the kit checkout whose server is called

Each answer is saved under WORK/answers/<n>-<tool>.json as the text the model receives
(result.content[0].text) plus a final newline. Receipts go to WORK/rdd (METODO_RDD_DIR), never
to the kit's own out folder.
"""
import json
import os
import pathlib
import subprocess
import sys

WORK = pathlib.Path(sys.argv[1]).resolve()
KIT = pathlib.Path(sys.argv[2]).resolve()
CASES = KIT / "08-benchmark" / "evals"
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="dev@example.com", GIT_COMMITTER_NAME="Dev",
               GIT_COMMITTER_EMAIL="dev@example.com", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(repo, *args, date="2026-11-02T09:00:00+00:00"):
    env = dict(GIT_ENV, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True, text=True)


def put(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def calls(repo, requests, name):
    """Send tools/call requests to one server process started for `repo`; save and return the texts."""
    env = dict(os.environ, METODO_REPO=str(repo), METODO_RDD_DIR=str(WORK / "rdd"), METODO_MEMORY="off",
               METODO_HOOKS_DIR=str(WORK / "hooks"))
    lines = [json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})]
    lines += [json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": tool, "arguments": args}})
              for n, (tool, args) in enumerate(requests, 1)]
    proc = subprocess.run([sys.executable, str(KIT / "03-tools" / "mcp" / "server.py")], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, env=env, cwd=str(WORK))
    answers = [json.loads(line) for line in proc.stdout.splitlines()][1:]
    out = WORK / "answers"
    out.mkdir(exist_ok=True)
    texts = []
    for n, ((tool, args), answer) in enumerate(zip(requests, answers), 1):
        result = answer.get("result") or answer
        text = result["content"][0]["text"] if "content" in result else json.dumps(result)
        (out / f"{name}-{n}-{tool}.json").write_text(text + "\n", encoding="utf-8")
        print(f"{name}-{n}-{tool} args={json.dumps(args)} isError={result.get('isError')} bytes={len(text)}")
        texts.append(text)
    return texts


# ---------------------------------------------------------------- billing: review-comment and pr-message
billing = WORK / "shop"
tip = CASES / "review-comment" / "smoke-base-drift" / "setup" / "billing"
billing.mkdir()
git(billing, "init", "-q", "-b", "develop")
put(billing, "billing/RetryPolicy.kt", "package billing\n\nclass RetryPolicy(private val maxAttempts: Int = 3) {\n"
    "    fun shouldRetry(attempt: Int): Boolean = attempt < maxAttempts\n}\n")
put(billing, "billing/LegacyExport.kt", (tip / "LegacyExport.kt").read_text(encoding="utf-8"))
git(billing, "add", "-A")
git(billing, "commit", "-q", "-m", "chore(billing): retry policy and legacy export")
git(billing, "checkout", "-q", "-b", "feature/retry-webhook")
for name in ("RetryPolicy.kt", "WebhookHandler.kt"):
    put(billing, f"billing/{name}", (tip / name).read_text(encoding="utf-8"))
git(billing, "add", "-A")
git(billing, "commit", "-q", "-m", "feat(billing): retry the payment webhook with backoff", date="2026-11-03T09:00:00+00:00")
git(billing, "checkout", "-q", "develop")  # the base moves on after the branch forked: the drift
put(billing, "billing/LegacyExport.kt", "package billing\n\nimport java.io.File\nimport java.io.IOException\n\n"
    "class LegacyExport(private val target: File) {\n    fun write(rows: List<String>) {\n        try {\n"
    "            target.writeText(rows.joinToString(\"\\n\"))\n        } catch (e: IOException) {\n"
    "            System.err.println(\"export skipped: ${e.message}\")\n        }\n    }\n}\n")
git(billing, "add", "-A")
git(billing, "commit", "-q", "-m", "fix(export): keep the export alive on a failed write", date="2026-11-04T09:00:00+00:00")
git(billing, "checkout", "-q", "feature/retry-webhook")
for name in ("LegacyExport.kt", "RetryPolicy.kt", "WebhookHandler.kt"):  # the tip is what the case stages
    assert (billing / "billing" / name).read_bytes() == (tip / name).read_bytes(), name

calls(billing, [("pr_scope", {"base": "develop", "head": "feature/retry-webhook"}),
                ("pr_scope", {"base": "develop"})], "review-comment")

card = WORK / "pr" / "card.md"
card.parent.mkdir()
card.write_bytes((CASES / "pr-message" / "smoke-skipped-check" / "setup" / "card.md").read_bytes())
calls(billing, [("change_card_validate", {"card_path": str(card)}),
                ("receipt_status", {}),
                ("change_card_validate", {"card_path": str(card)}),
                ("receipt_status", {})], "pr-message")

# ---------------------------------------------------------------- booking: receipt-review
booking = WORK / "seats"
booking.mkdir()
hold = ("package booking\n\nimport java.time.Duration\n\nclass SeatHold(private val hold: Duration = Duration.ofMinutes(%d)) {\n"
        "    fun expiresAt(startedAtMs: Long): Long = startedAtMs + hold.toMillis()\n}\n")
git(booking, "init", "-q", "-b", "develop")
put(booking, "booking/SeatHold.kt", hold % 10)
git(booking, "add", "-A")
git(booking, "commit", "-q", "-m", "feat(booking): hold a seat while its buyer pays")
git(booking, "checkout", "-q", "-b", "fix/seat-hold-15")
put(booking, "booking/SeatHold.kt", hold % 15)
git(booking, "add", "-A")
git(booking, "commit", "-q", "-m", "fix(booking): hold a seat for 15 minutes", date="2026-11-03T09:00:00+00:00")
round_dir = WORK / "rounds" / "book-118"
round_dir.mkdir(parents=True)
card = round_dir / "001-card.md"
card.write_bytes((CASES / "receipt-review" / "smoke-tier-frozen" / "setup" / "round" / "001-card.md").read_bytes())
start = {"round_dir": str(round_dir), "base": "develop", "change_card_path": str(card)}
calls(booking, [("receipt_status", {}), ("receipt_start", start)], "receipt-review-open")
receipts = sorted((WORK / "rdd").glob("*.receipt.json"))
before = [(p.name, p.read_bytes(), p.stat().st_mtime_ns) for p in receipts]
calls(booking, [("receipt_status", {}), ("receipt_start", start), ("receipt_status", {}),
                ("receipt_start", {"round_dir": str(WORK / "rounds" / "other"), "base": "develop"}),
                ("test_sectors", {"base": "develop"}), ("test_sectors", {})], "receipt-review")
after = [(p.name, p.read_bytes(), p.stat().st_mtime_ns) for p in sorted((WORK / "rdd").glob("*.receipt.json"))]
print("receipt files:", [name for name, _, _ in after], "unchanged by the second batch (bytes and mtime):", before == after)
