#!/usr/bin/env python3
"""Kit telemetry from a per-repo tools instance: hook ledgers and RDD receipts.

Reads <instance>/out/hooks/<ts>_<session_id>/{ledger.jsonl,run-meta.json,touched.jsonl}
and <instance>/out/rdd/*.receipt.json / *.void-N.json (03-tools/hooks/_common.py,
03-tools/lib/rdd_receipt.py). Deterministic, and no paths or reasons with
file names leave this script: only kinds, decisions, counts and rule ids.

Usage:
  kit_telemetry.py --instance ~/project-a-tools [--instance ...] --out kit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

SCHEMA_VERSION = "1.0.0"
RULE_ID = re.compile(r"\b(?:COM|RC|DOC|CC)-\d{2,3}\b")
SID_IN_DIR = re.compile(r"_([0-9a-f-]{36})$")


def _jsonl(path: pathlib.Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _session(dirpath: pathlib.Path) -> dict:
    m = SID_IN_DIR.search(dirpath.name)
    session_id = m.group(1) if m else dirpath.name
    started = None
    meta = dirpath / "run-meta.json"
    if meta.exists():
        try:
            started = json.loads(meta.read_text(encoding="utf-8")).get("started_at")
        except (json.JSONDecodeError, OSError):
            started = None
    by_kd = Counter()
    by_hook = Counter()
    rule_hits = Counter()
    budget = defaultdict(Counter)
    lines = 0
    for r in _jsonl(dirpath / "ledger.jsonl"):
        lines += 1
        kind, decision, hook = r.get("kind") or "?", r.get("decision") or "?", r.get("hook") or "?"
        by_kd[f"{kind}:{decision}"] += 1
        by_hook[hook] += 1
        if kind == "reply-lint":
            rule_hits.update(RULE_ID.findall(r.get("reason") or ""))
        if hook == "budget":
            budget[r.get("agent_type") or "unknown"][kind] += 1
    touched = sum(1 for _ in _jsonl(dirpath / "touched.jsonl"))
    return {
        "session_id": session_id,
        "dir_ts": dirpath.name.split("_")[0] if "_" in dirpath.name else None,
        "started_at": started,
        "lines": lines,
        "by_kind_decision": dict(sorted(by_kd.items())),
        "by_hook": dict(sorted(by_hook.items())),
        "reply_lint_rule_hits": dict(sorted(rule_hits.items())),
        "budget_by_agent_type": {k: dict(sorted(v.items())) for k, v in sorted(budget.items())},
        "touched_paths": touched,
    }


def _receipts(rdd_dir: pathlib.Path) -> dict:
    receipts = []
    voids = 0
    if rdd_dir.is_dir():
        for f in sorted(rdd_dir.iterdir()):
            if f.name.endswith(".receipt.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                stats = d.get("diff_stats") or {}
                receipts.append({
                    "tree": (d.get("tree_sha") or "")[:12],
                    "state": d.get("state") or "unknown",
                    "verdict": d.get("verdict") or "none",
                    "correction_index": d.get("correction_index"),
                    "captures": len(d.get("captures") or []),
                    "owner_ack": bool(d.get("owner_ack")),
                    "risk": (d.get("risk") or {}).get("tier") or (d.get("risk") or {}).get("level") or "unknown",
                    "files": stats.get("files"),
                    "insertions": stats.get("insertions"),
                    "deletions": stats.get("deletions"),
                })
            elif ".void-" in f.name and f.suffix == ".json":
                voids += 1
    return {
        "count": len(receipts),
        "voids": voids,
        "by_state": dict(sorted(Counter(r["state"] for r in receipts).items())),
        "by_verdict": dict(sorted(Counter(r["verdict"] for r in receipts).items())),
        "by_risk": dict(sorted(Counter(r["risk"] for r in receipts).items())),
        "captures_total": sum(r["captures"] for r in receipts),
        "diff_insertions_total": sum(r["insertions"] or 0 for r in receipts),
        "items": receipts,
    }


def analyze_instance(instance: pathlib.Path) -> dict:
    hooks_dir = instance / "out" / "hooks"
    sessions = []
    if hooks_dir.is_dir():
        for d in sorted(p for p in hooks_dir.iterdir() if p.is_dir()):
            sessions.append(_session(d))
    total_kd = Counter()
    for s in sessions:
        total_kd.update(s["by_kind_decision"])
    starts = sorted(s["started_at"][:10] for s in sessions if s["started_at"])
    return {
        "name": instance.name,
        "sessions": sessions,
        "receipts": _receipts(instance / "out" / "rdd"),
        "totals": {
            "sessions": len(sessions),
            "ledger_lines": sum(s["lines"] for s in sessions),
            "by_kind_decision": dict(sorted(total_kd.items())),
            "first_started_at": starts[0] if starts else None,
            "last_started_at": starts[-1] if starts else None,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--instance", action="append", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    instances = [analyze_instance(pathlib.Path(i).expanduser()) for i in args.instance]
    instances.sort(key=lambda x: x["name"])
    payload = {"schema_version": SCHEMA_VERSION,
               "tool_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
               "instances": instances}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"instances": len(instances), "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
