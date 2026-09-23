#!/usr/bin/env python3
"""Merges the kit's hooks into a Claude Code settings.local.json without
touching anything else in the file: keeps permissions and any other key
as-is, and inside `hooks` replaces only the entries whose command carries
the kit's marker (by default 'metodo-hook', a no-op `: metodo-hook;` at
the start of the command). A hook the owner wrote by hand, with no marker,
survives every pass. The __TOOLS_DEFAULT__ token in commands is replaced
with the kit's default path (--tools-default), so an instance at a
different path gets its own hooks.

Usage:
    lib/settings_merge.py <settings.json> --hooks <hooks.settings.json> [--marker M] [--tools-default PATH]
    lib/settings_merge.py <settings.json> --remove [--marker M]

Output: {path, changed, added, removed}. Idempotent: an identical second
pass does not change the file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MARKER = "metodo-hook"
TOOLS_TOKEN = "__TOOLS_DEFAULT__"
DEFAULT_TOOLS = "$HOME/metodologia-de-trabajo/03-tools"


def _is_kit_entry(entry: dict, marker: str) -> bool:
    return any(marker in str(hook.get("command", "")) for hook in entry.get("hooks", []))


def render_kit_hooks(kit_hooks: dict, tools_default: str = DEFAULT_TOOLS) -> dict:
    text = json.dumps(kit_hooks).replace(TOOLS_TOKEN, tools_default)
    return json.loads(text)


def merge_hooks(settings: dict, kit_hooks: dict, marker: str = DEFAULT_MARKER, tools_default: str = DEFAULT_TOOLS) -> tuple[dict, dict]:
    kit_hooks = render_kit_hooks(kit_hooks, tools_default)
    merged = dict(settings)
    hooks = {event: list(entries) for event, entries in (settings.get("hooks") or {}).items()}
    added = removed = 0
    for event, kit_entries in (kit_hooks.get("hooks") or {}).items():
        kept = []
        for entry in hooks.get(event, []):
            if _is_kit_entry(entry, marker):
                removed += 1
            else:
                kept.append(entry)
        kept.extend(kit_entries)
        added += len(kit_entries)
        hooks[event] = kept
    merged["hooks"] = hooks
    return merged, {"added": added, "removed": removed}


def remove_hooks(settings: dict, marker: str = DEFAULT_MARKER) -> tuple[dict, dict]:
    merged = dict(settings)
    hooks = {}
    removed = 0
    for event, entries in (settings.get("hooks") or {}).items():
        kept = [e for e in entries if not _is_kit_entry(e, marker)]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
    if hooks:
        merged["hooks"] = hooks
    else:
        merged.pop("hooks", None)
    return merged, {"added": 0, "removed": removed}


def apply(settings_path: Path, kit_hooks_path: Path | None, marker: str, remove: bool, tools_default: str = DEFAULT_TOOLS) -> dict:
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    if remove:
        merged, counts = remove_hooks(settings, marker)
    else:
        kit_hooks = json.loads(Path(kit_hooks_path).read_text(encoding="utf-8"))
        merged, counts = merge_hooks(settings, kit_hooks, marker, tools_default)
    changed = merged != settings
    if changed:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(settings_path), "changed": changed, **counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings", help="path to .claude/settings.local.json (created if missing)")
    parser.add_argument("--hooks", default=None, help="the kit's hooks.settings.json")
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--tools-default", default=DEFAULT_TOOLS, help="replaces __TOOLS_DEFAULT__ in the commands")
    args = parser.parse_args(argv)
    if not args.remove and not args.hooks:
        parser.error("pass --hooks, or --remove")
    result = apply(Path(args.settings), Path(args.hooks) if args.hooks else None, args.marker, args.remove, args.tools_default)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
