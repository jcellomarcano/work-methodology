#!/usr/bin/env python3
"""Checks that no doc exceeds its line cap (config/docs-caps.json) and,
with --tokens, its token cap (config/token-caps.json).

A missing doc is reported as "missing", not as a failure: a doc that does
not exist yet is not a doc that went over size. Only the ones that exist
AND exceed their cap fail the exit code.

The line config is {"docs_root": "~/path", "caps": {"name.md": cap, ...}}:
the reader's path lives on whoever runs this machine, never in the repo, so
`docs_root` is the only thing allowed to carry `~` (expanded on the fly)
and the `caps` keys are just the file name (relative, may carry
subfolders). The report uses those same relative names, never the
resolved absolute path. `--root DIR` replaces `docs_root`, so a checkout
lints itself: run from the repo root with `--root .`.

The token config is {"method": "ceil(chars/4)", "token_caps": {"name.md":
cap}, "field_caps": [{"glob": G, "field": F, "cap": N} | {"glob": G,
"part": "body"|"frontmatter", "cap": N}]}. Tokens are ceil(characters / 4),
an estimate, not a tokenizer. A field cap measures one frontmatter field
(e.g. a skill `description`); a part cap measures the body or frontmatter,
split exactly as render_agents.split_frontmatter splits a role. A glob that
matches nothing is "missing". With --tokens the two reports merge: every
entry carries its `unit`, and the report carries the `method`.

Usage:
    lib/docs_lint.py <config> [--tokens <token-config>] [--root DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    from lib.render_agents import frontmatter_field, split_frontmatter
except ImportError:  # run as a script: lib/ itself is on sys.path
    from render_agents import frontmatter_field, split_frontmatter

METHOD = "ceil(chars/4)"
PARTS = ("body", "frontmatter")


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


def token_count(text: str) -> int:
    return math.ceil(len(text) / 4)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _measure(text: str, spec: dict) -> tuple[int | None, str | None]:
    """Returns (tokens, error) for one field or part of a frontmatter file."""
    try:
        frontmatter, body = split_frontmatter(text)
    except ValueError as exc:
        return None, str(exc)
    if "field" in spec:
        value = frontmatter_field(frontmatter, spec["field"])
        if not value:
            return None, f"no `{spec['field']}` field in the frontmatter"
        return token_count(value), None
    return token_count(body if spec["part"] == "body" else frontmatter), None


def _sort_key(entry: dict) -> tuple:
    return (entry["path"], entry.get("unit", ""), entry.get("field", ""), entry.get("part", ""))


def check_tokens(docs_root: Path, config: dict) -> dict:
    docs_root = Path(docs_root).expanduser()
    offenders, missing, ok = [], [], []

    def place(entry: dict) -> None:
        over = entry["actual"] is None or entry["actual"] > entry["limit"]
        (offenders if over else ok).append(entry)

    caps = config.get("token_caps", {})
    for name in sorted(caps):
        path = docs_root / name
        if not path.is_file():
            missing.append(name)
            continue
        place({"path": name, "unit": "tokens", "actual": token_count(_read(path)), "limit": caps[name]})

    for spec in config.get("field_caps", []):
        if ("field" in spec) == ("part" in spec) or spec.get("part", "body") not in PARTS:
            raise ValueError(f"a field cap needs exactly one of field or part ({'|'.join(PARTS)}): {spec}")
        key = {"field": spec["field"]} if "field" in spec else {"part": spec["part"]}
        matches = sorted(p for p in docs_root.glob(spec["glob"]) if p.is_file())
        # A named file may carry its own cap (a documented exception); an override
        # naming a file the glob no longer finds is reported, never silently kept.
        overrides = spec.get("overrides", {})
        found = {p.relative_to(docs_root).as_posix() for p in matches}
        missing.extend(name for name in overrides if name not in found)
        if not matches:
            missing.append(spec["glob"])
            continue
        for path in matches:
            rel = path.relative_to(docs_root).as_posix()
            actual, error = _measure(_read(path), spec)
            entry = {"path": rel, "unit": "tokens", **key,
                     "actual": actual, "limit": overrides.get(rel, spec["cap"])}
            if error:
                entry["error"] = error
            place(entry)

    return {"method": METHOD, "offenders": sorted(offenders, key=_sort_key),
            "missing": sorted(set(missing)), "ok": sorted(ok, key=_sort_key)}


def merge(lines: dict, tokens: dict) -> dict:
    def tagged(entries: list) -> list:
        return [{**e, "unit": "lines"} for e in entries]

    return {
        "method": tokens["method"],
        "offenders": sorted(tagged(lines["offenders"]) + tokens["offenders"], key=_sort_key),
        "missing": sorted(set(lines["missing"]) | set(tokens["missing"])),
        "ok": sorted(tagged(lines["ok"]) + tokens["ok"], key=_sort_key),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", help="path to docs-caps.json")
    parser.add_argument("--tokens", help="path to token-caps.json; adds token caps to the report")
    parser.add_argument("--root", help="directory to lint; overrides the config's docs_root")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(args.root).expanduser() if args.root else config["docs_root"]
    result = check(root, config["caps"])
    if args.tokens:
        token_config = json.loads(Path(args.tokens).read_text(encoding="utf-8"))
        if token_config.get("method") != METHOD:
            parser.error(f"{args.tokens}: method must be {METHOD!r}, got {token_config.get('method')!r}")
        try:
            result = merge(result, check_tokens(root, token_config))
        except ValueError as exc:
            parser.error(f"{args.tokens}: {exc}")
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))

    if result["offenders"]:
        for entry in result["offenders"]:
            label = entry["path"]
            if args.tokens:
                label += f" [{entry.get('field') or entry.get('part') or 'file'} {entry['unit']}]"
            print(f"OFFENDER: {label}: {entry['actual']} > {entry['limit']}"
                  + (f" ({entry['error']})" if entry.get("error") else ""), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
