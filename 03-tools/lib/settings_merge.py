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
        [--user-settings PATH]
    lib/settings_merge.py <settings.json> --remove [--marker M]

Kit-owned top-level keys (KIT_SETTINGS): autoCompactWindow 300000 is the
orchestrator's auto-compact window (decision D1;
code.claude.com/docs/en/settings-reference#autocompactwindow). One is set
only when no Claude Code settings scope the installer can see sets it: the
user file ($METODO_CLAUDE_HOME/settings.json, default ~/.claude/settings.json,
or --user-settings), the project file (settings.json beside the merged one)
and the merged local file itself (T18, A-003/B-009). Managed settings are not
visible here. What the kit added is recorded in a sidecar beside the merged
file, KEYS_RECORD (`{"added": {key: value}}`), so the settings file carries no
foreign key; --remove takes a key out only when the record says the kit added
it and it still holds the recorded value, then deletes the sidecar. A
re-install withdraws a kit key once another scope sets it, since the local
file outranks the others and would shadow the owner's value.

Output: {path, changed, added, removed, keys_added, keys_removed}.
Idempotent: an identical second pass does not change the file. --remove
deletes the file when removing the kit's hooks and keys leaves it empty
({}): the kit created it, nothing else is in it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_MARKER = "metodo-hook"
TOOLS_TOKEN = "__TOOLS_DEFAULT__"
DEFAULT_TOOLS = "$HOME/metodologia-de-trabajo/03-tools"
KIT_SETTINGS = {"autoCompactWindow": 300000}
KEYS_RECORD = "metodo-settings-keys.json"


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


def user_settings_path() -> Path:
    return Path(os.environ.get("METODO_CLAUDE_HOME") or Path.home() / ".claude") / "settings.json"


def _read_json(path: Path) -> dict:
    """A scope the installer cannot parse is a scope it cannot see: {}."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _kit_owned(settings: dict, recorded: dict, key: str) -> bool:
    return key in recorded and key in settings and settings[key] == recorded[key]


def merge_keys(settings: dict, recorded: dict | None = None, other_scopes: list[dict] | tuple = ()) -> tuple[dict, list[str], list[str], dict]:
    """Adds each kit-owned key no visible scope sets; an owner value is never
    overwritten. Returns (merged, added, withdrawn, record): a key the kit
    added earlier is withdrawn once another scope sets it."""
    recorded = dict(recorded or {})
    merged, added, withdrawn, record = dict(settings), [], [], {}
    for key, value in KIT_SETTINGS.items():
        kit_owned = _kit_owned(settings, recorded, key)
        owner_set = any(key in scope for scope in other_scopes) or (key in settings and not kit_owned)
        if owner_set:
            if kit_owned:
                merged.pop(key)
                withdrawn.append(key)
            continue
        if not kit_owned:
            merged[key] = value
            added.append(key)
        record[key] = merged[key]
    return merged, added, withdrawn, record


def remove_keys(settings: dict, recorded: dict | None = None) -> tuple[dict, list[str]]:
    """Takes out each key the kit recorded as added that still holds the recorded value; an edited one is the owner's."""
    recorded = recorded or {}
    merged = dict(settings)
    removed = [key for key in KIT_SETTINGS if _kit_owned(settings, recorded, key)]
    for key in removed:
        merged.pop(key)
    return merged, removed


def apply(settings_path: Path, kit_hooks_path: Path | None, marker: str, remove: bool, tools_default: str = DEFAULT_TOOLS,
          user_settings: Path | None = None) -> dict:
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    record_path = settings_path.parent / KEYS_RECORD
    recorded = _read_json(record_path).get("added") or {} if record_path.exists() else {}
    recorded = recorded if isinstance(recorded, dict) else {}
    if remove:
        merged, counts = remove_hooks(settings, marker)
        merged, keys_removed = remove_keys(merged, recorded)
        counts.update(keys_added=[], keys_removed=keys_removed)
        record = {}
    else:
        kit_hooks = json.loads(Path(kit_hooks_path).read_text(encoding="utf-8"))
        merged, counts = merge_hooks(settings, kit_hooks, marker, tools_default)
        scopes = [_read_json(user_settings or user_settings_path()), _read_json(settings_path.parent / "settings.json")]
        merged, keys_added, keys_removed, record = merge_keys(merged, recorded, scopes)
        counts.update(keys_added=keys_added, keys_removed=keys_removed)
    record_changed = record != recorded or (not record and record_path.exists())
    if record:
        if record_changed:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps({"added": record}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif record_path.exists():
        record_path.unlink()
    changed = merged != settings or record_changed
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
    parser.add_argument("--user-settings", default=None,
                        help="the user scope (default $METODO_CLAUDE_HOME/settings.json, else ~/.claude/settings.json)")
    args = parser.parse_args(argv)
    if not args.remove and not args.hooks:
        parser.error("pass --hooks, or --remove")
    result = apply(Path(args.settings), Path(args.hooks) if args.hooks else None, args.marker, args.remove, args.tools_default,
                   Path(args.user_settings) if args.user_settings else None)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
