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

Kit-owned top-level keys (KIT_SETTINGS) are set only when the owner has not
set them, and --remove takes one out only while it still holds the kit's
value: autoCompactWindow 300000 is the orchestrator's auto-compact window
(decision D1; code.claude.com/docs/en/settings-reference#autocompactwindow).

Output: {path, changed, added, removed, keys_added, keys_removed}.
Idempotent: an identical second pass does not change the file. --remove
deletes the file when removing the kit's hooks and keys leaves it empty
({}): the kit created it, nothing else is in it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MARKER = "metodo-hook"
TOOLS_TOKEN = "__TOOLS_DEFAULT__"
DEFAULT_TOOLS = "$HOME/metodologia-de-trabajo/03-tools"
KIT_SETTINGS = {"autoCompactWindow": 300000}


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
    kit_events = kit_hooks.get("hooks") or {}
    # Every event is swept, not only the ones the kit ships today: a kit entry left
    # under an event the kit dropped (the old Stop reply_lint) goes on re-install.
    for event in sorted(set(hooks) | set(kit_events)):
        kept = []
        for entry in hooks.get(event, []):
            if _is_kit_entry(entry, marker):
                removed += 1
            else:
                kept.append(entry)
        kit_entries = kit_events.get(event, [])
        kept.extend(kit_entries)
        added += len(kit_entries)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    merged["hooks"] = {event: hooks[event] for event in [*(settings.get("hooks") or {}), *kit_events] if event in hooks}
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


def merge_keys(settings: dict) -> tuple[dict, list[str]]:
    """Adds each kit-owned key the owner has not set; an owner value is never overwritten."""
    merged = dict(settings)
    added = [key for key in KIT_SETTINGS if key not in settings]
    for key in added:
        merged[key] = KIT_SETTINGS[key]
    return merged, added


def remove_keys(settings: dict) -> tuple[dict, list[str]]:
    """Takes out each kit-owned key that still holds the kit's value; an edited one is the owner's."""
    merged = dict(settings)
    removed = [key for key, value in KIT_SETTINGS.items() if key in settings and settings[key] == value]
    for key in removed:
        merged.pop(key)
    return merged, removed


def apply(settings_path: Path, kit_hooks_path: Path | None, marker: str, remove: bool, tools_default: str = DEFAULT_TOOLS) -> dict:
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    if remove:
        merged, counts = remove_hooks(settings, marker)
        merged, keys_removed = remove_keys(merged)
        counts.update(keys_added=[], keys_removed=keys_removed)
    else:
        kit_hooks = json.loads(Path(kit_hooks_path).read_text(encoding="utf-8"))
        merged, counts = merge_hooks(settings, kit_hooks, marker, tools_default)
        merged, keys_added = merge_keys(merged)
        counts.update(keys_added=keys_added, keys_removed=[])
    changed = merged != settings
    if changed and remove and not merged and settings_path.exists():
        settings_path.unlink()
    elif changed:
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
