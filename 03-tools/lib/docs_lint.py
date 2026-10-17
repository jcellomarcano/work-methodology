#!/usr/bin/env python3
"""Checks that no doc exceeds its line cap (config/docs-caps.json).

A missing doc is reported as "missing", not as a failure: a doc that does
not exist yet is not a doc that went over size. Only the ones that exist
AND exceed their cap fail the exit code.

The config is {"docs_root": "~/path", "caps": {"name.md": cap, ...}}: the
reader's path lives on whoever runs this machine, never in the repo, so
`docs_root` is the only thing allowed to carry `~` (expanded on the fly)
and the `caps` keys are just the file name (relative, may carry
subfolders). The report uses those same relative names, never the
resolved absolute path.

Usage:
    lib/docs_lint.py <config>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(docs_root: Path, caps: dict) -> dict:
    docs_root = Path(docs_root).expanduser()
    offenders = []
    missing = []
    ok = []
    for name in sorted(caps):
        limit = caps[name]
        path = docs_root / name
        if not path.exists():
            missing.append(name)
            continue
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            actual = sum(1 for _ in fh)
        entry = {"path": name, "actual": actual, "limit": limit}
        if actual > limit:
            offenders.append(entry)
        else:
            ok.append(entry)
    return {"offenders": offenders, "missing": missing, "ok": ok}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="path to docs-caps.json")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    result = check(config["docs_root"], config["caps"])
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))

    if result["offenders"]:
        for entry in result["offenders"]:
            print(f"OFFENDER: {entry['path']}: {entry['actual']} > {entry['limit']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
