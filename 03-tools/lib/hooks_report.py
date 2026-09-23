#!/usr/bin/env python3
"""Turns the hooks ledger (out/hooks/<session>/ledger.jsonl) and the
receipts (out/rdd/*.receipt.json) into the figures agent-protocol.md
paragraph 8 asks for and nobody measured: calls per agent, denials,
warnings, invalid or truncated outputs, gates, receipts by tier and
verdict, first-pass acceptance. And the warn -> block pass criterion.

Usage:
    lib/hooks_report.py [--hooks-dir out/hooks] [--receipts-dir out/rdd] [--min-days 7] [--min-receipts 5] [--max-false-positives 2]
    lib/hooks_report.py --false-positive "<reason>" --session <id> --seq <n> [--hooks-dir ...]

Output: out/hooks/report.json (and on stdout). Tokens never reach a hook:
they go in not_measured with how to get them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline  # noqa: E402

LEDGER_FIELDS = ("seq", "hook", "event", "agent_type", "agent_id", "tool", "kind", "decision", "mode", "reason", "path", "tree", "receipt")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _days_observed(hooks_dir: Path) -> int:
    stamps = []
    for meta in hooks_dir.glob("*/run-meta.json"):
        try:
            stamps.append(datetime.datetime.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["started_at"]))
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    if len(stamps) < 1:
        return 0
    return (max(stamps) - min(stamps)).days


def build_report(hooks_dir: Path, receipts_dir: Path, min_days: int, min_receipts: int, max_false_positives: int) -> dict:
    per_agent: dict[str, Counter] = defaultdict(Counter)
    gates = Counter()
    sessions = 0
    for session_dir in sorted(p for p in hooks_dir.glob("*") if p.is_dir()):
        sessions += 1
        for count_file in session_dir.glob("budget-*.count"):
            agent_type = count_file.stem[len("budget-"):].rsplit("-", 1)[0]
            try:
                calls = int(count_file.read_text(encoding="utf-8").strip() or 0)
            except ValueError:
                calls = 0
            per_agent[agent_type]["calls"] += calls
            per_agent[agent_type]["max_calls"] = max(per_agent[agent_type]["max_calls"], calls)
            per_agent[agent_type]["runs"] += 1
        for line in read_jsonl(session_dir / "ledger.jsonl"):
            agent = line.get("agent_type") or "main"
            kind = line.get("kind", "")
            decision = line.get("decision", "")
            if decision == "deny":
                per_agent[agent]["denials"] += 1
            elif decision in ("warn", "ask"):
                per_agent[agent]["warnings"] += 1
            if kind == "output-invalid":
                per_agent[agent]["invalid_outputs"] += 1
            if kind == "output-truncated":
                per_agent[agent]["truncated_outputs"] += 1
            if kind in ("gate-push", "gate-pr", "gate-merge", "gate-tag"):
                gates[kind] += 1
                if line.get("receipt") == "approved":
                    gates[f"{kind}_with_receipt"] += 1
                elif decision != "deny":
                    gates[f"{kind}_without_receipt"] += 1
                if decision == "ask":
                    gates["asks"] += 1
            if kind == "force-push" and decision == "deny":
                gates["force_denied"] += 1
            if kind == "budget-deny":
                gates["budget_denied"] += 1

    receipts = Counter()
    verdicts = Counter()
    finalized = first_pass = corrections = escalations = verifier_fail = acks = 0
    for path in sorted(receipts_dir.glob("*.receipt.json")):
        r = baseline.load_json(path)
        receipts[r["risk"]["tier"]] += 1
        if r["state"] == "finalized":
            finalized += 1
            verdicts[r["verdict"] or "none"] += 1
            if r["verdict"] == "approved" and r["correction_index"] == 0 and not r.get("inherited_from"):
                first_pass += 1
            if r["correction_index"] == 1:
                corrections += 1
            if r["verdict"] == "escalated":
                escalations += 1
            if any("verifier FAIL" in reason for reason in r.get("verdict_reasons", [])):
                verifier_fail += 1
        if r.get("owner_ack"):
            acks += 1

    false_positives = read_jsonl(hooks_dir / "false-positives.jsonl")
    days = _days_observed(hooks_dir)
    flip = {
        "min_days": min_days, "days_observed": days,
        "min_receipts": min_receipts, "receipts_finalized": finalized,
        "max_false_positives": max_false_positives, "false_positives": len(false_positives),
    }
    flip["ready"] = days >= min_days and finalized >= min_receipts and len(false_positives) <= max_false_positives

    return {
        "sessions": sessions,
        "per_agent": {agent: dict(sorted(counter.items())) for agent, counter in sorted(per_agent.items())},
        "gates": dict(sorted(gates.items())),
        "receipts": {
            "by_tier": dict(sorted(receipts.items())),
            "by_verdict": dict(sorted(verdicts.items())),
            "finalized": finalized,
            "first_pass_acceptance": first_pass,
            "corrections_used": corrections,
            "escalations": escalations,
            "verifier_fail_caught": verifier_fail,
            "owner_acks": acks,
        },
        "false_positives": false_positives,
        "flip_warn_to_block": flip,
        "not_measured": [{"metric": "tokens_per_agent",
                          "how_to_get_it": "hooks do not receive tokens; parse transcript_path per session, not built"}],
    }


def record_false_positive(hooks_dir: Path, session: str, seq: int, reason: str) -> Path:
    path = hooks_dir / "false-positives.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"session": session, "seq": seq, "reason": reason}, ensure_ascii=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hooks-dir", default=str(TOOLS_ROOT / "out" / "hooks"))
    parser.add_argument("--receipts-dir", default=str(TOOLS_ROOT / "out" / "rdd"))
    parser.add_argument("--min-days", type=int, default=7)
    parser.add_argument("--min-receipts", type=int, default=5)
    parser.add_argument("--max-false-positives", type=int, default=2)
    parser.add_argument("--false-positive", default=None, help="reason; requires --session and --seq")
    parser.add_argument("--session", default=None)
    parser.add_argument("--seq", type=int, default=None)
    args = parser.parse_args(argv)

    hooks_dir = Path(args.hooks_dir)
    if args.false_positive:
        if not (args.session and args.seq is not None):
            parser.error("--false-positive requires --session and --seq")
        path = record_false_positive(hooks_dir, args.session, args.seq, args.false_positive)
        print(json.dumps({"recorded": str(path)}))
        return 0

    report = build_report(hooks_dir, Path(args.receipts_dir), args.min_days, args.min_receipts, args.max_false_positives)
    if hooks_dir.exists():
        baseline.write_json(hooks_dir / "report.json", report)
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
