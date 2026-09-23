"""Tool versions for the tool_versions header of every payload.

It invents nothing: python/java come from the runtime running the script;
pmd, detekt, and ktlint come from config/tools.lock.json (what
fetch-tools.sh recorded). If a tool is not available, it shows up as
"unavailable" instead of being silently omitted.
"""
from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

from lib import baseline


def python_version() -> str:
    return platform.python_version()


def java_version() -> str:
    try:
        proc = subprocess.run(["java", "-version"], capture_output=True, text=True)
    except OSError:
        return "unavailable"
    text = proc.stderr or proc.stdout
    match = re.search(r'version "([^"]+)"', text)
    return match.group(1) if match else "unavailable"


def _lock_entry_version(lock: dict, name: str) -> str:
    entry = lock.get(name) or {}
    if entry.get("status") == "unavailable":
        return "unavailable"
    return entry.get("version", "unavailable")


def tool_versions(tools_repo_root: Path) -> dict:
    lock_path = Path(tools_repo_root) / "config" / "tools.lock.json"
    lock = baseline.load_json(lock_path) if lock_path.exists() else {}
    return {
        "python": python_version(),
        "java": java_version(),
        "pmd": _lock_entry_version(lock, "pmd"),
        "detekt": _lock_entry_version(lock, "detekt"),
        "ktlint": _lock_entry_version(lock, "ktlint"),
    }
