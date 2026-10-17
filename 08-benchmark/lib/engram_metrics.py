#!/usr/bin/env python3
"""Engram usage metrics from an `engram export <file> --all` JSON dump.

Deterministic: the export's `exported_at` is dropped; same data, same bytes.
Private: titles, contents, prompts and directories never leave this script.

Usage:
  engram export /path/scratch/engram-all.json --all
  engram_metrics.py --export /path/scratch/engram-all.json --out engram.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

SCHEMA_VERSION = "1.0.0"


def _day(value) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def analyze_export(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    sessions = data.get("sessions") or []
    observations = data.get("observations") or []
    prompts = data.get("prompts") or []
    relations = data.get("relations") or []

    obs_by_session = defaultdict(list)
    for o in observations:
        obs_by_session[o.get("session_id")].append(o)
    prompts_by_session = Counter(p.get("session_id") for p in prompts)

    projects = {}
    session_rows = []
    for s in sorted(sessions, key=lambda x: (x.get("project") or "", x.get("started_at") or "", x.get("id") or "")):
        proj = s.get("project") or "unknown"
        obs = obs_by_session.get(s.get("id"), [])
        p = projects.setdefault(proj, {
            "sessions": 0, "sessions_with_observations": 0, "observations": 0, "by_type": Counter(),
            "with_topic_key": 0, "upserted": 0, "pinned": 0, "prompts": 0,
            "first_session": None, "last_session": None, "ownership": Counter(),
        })
        p["sessions"] += 1
        p["sessions_with_observations"] += int(bool(obs))
        p["prompts"] += prompts_by_session.get(s.get("id"), 0)
        p["ownership"][s.get("ownership_mode") or "unknown"] += 1
        day = _day(s.get("started_at"))
        if day:
            p["first_session"] = min(filter(None, [p["first_session"], day]))
            p["last_session"] = max(filter(None, [p["last_session"], day]))
        session_rows.append({
            "session_id": s.get("id"),
            "project": proj,
            "started_at": _day(s.get("started_at")),
            "observations": len(obs),
            "by_type": dict(sorted(Counter(o.get("type") or "unknown" for o in obs).items())),
            "prompts": prompts_by_session.get(s.get("id"), 0),
        })

    for o in observations:
        p = projects.setdefault(o.get("project") or "unknown", {
            "sessions": 0, "sessions_with_observations": 0, "observations": 0, "by_type": Counter(),
            "with_topic_key": 0, "upserted": 0, "pinned": 0, "prompts": 0,
            "first_session": None, "last_session": None, "ownership": Counter(),
        })
        p["observations"] += 1
        p["by_type"][o.get("type") or "unknown"] += 1
        p["with_topic_key"] += int(bool(o.get("topic_key")))
        p["upserted"] += int((o.get("revision_count") or 0) > 1)
        p["pinned"] += int(bool(o.get("pinned")))

    for p in projects.values():
        p["by_type"] = dict(sorted(p["by_type"].items()))
        p["ownership"] = dict(sorted(p["ownership"].items()))

    return {
        "projects": dict(sorted(projects.items())),
        "sessions": session_rows,
        "totals": {
            "sessions": len(sessions),
            "sessions_with_zero_observations": sum(1 for s in sessions if not obs_by_session.get(s.get("id"))),
            "observations": len(observations),
            "prompts": len(prompts),
            "relations": len(relations),
            "relations_by_relation": dict(sorted(Counter(r.get("relation") or "unknown" for r in relations).items())),
            "relations_pending": sum(1 for r in relations if r.get("judgment_status") == "pending"),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--export", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    payload = analyze_export(pathlib.Path(args.export).expanduser())
    payload["schema_version"] = SCHEMA_VERSION
    payload["tool_sha256"] = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": payload["totals"]["sessions"], "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
