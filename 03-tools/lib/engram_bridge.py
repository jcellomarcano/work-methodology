#!/usr/bin/env python3
"""Sends one note to engram, the persistent memory that lives outside the
repo (~/.engram/engram.db).

The rule the kit keeps: `out/` is the audit trail and engram is the index.
engram overwrites a note that carries the same topic key, so what you read
back there is always the latest state of that thing, never its history. When
you need the history, read the receipt or the handoff file.

Nothing here is ever load-bearing. No binary, memory disabled, a non-zero
exit: the function returns False and the caller carries on.

Usage:
    lib/engram_bridge.py --title T --body B [--kind K] [--topic-key K] [--project P]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(os.environ.get("METODO_TOOLS") or Path(__file__).resolve().parent.parent).resolve()
DEFAULT_KIND = "context"
TIMEOUT_SECONDS = 15


def load_config() -> dict:
    path = Path(os.environ.get("METODO_PROJECT_CONFIG") or TOOLS_ROOT / "config" / "project.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def memory_enabled(config: dict | None = None) -> bool:
    # METODO_MEMORY=off is the hard switch the test suite uses: a test that
    # exercises a receipt or a handoff must not write into the real engram.
    if os.environ.get("METODO_MEMORY", "").lower() == "off":
        return False
    memory = (config if config is not None else load_config()).get("memory") or {}
    return bool(memory.get("enabled"))


def resolve_project(project: str | None = None, config: dict | None = None, repo: Path | None = None) -> str:
    """project.json first, then ENGRAM_PROJECT, then the repo folder's name.
    The last one is a guess, which is why the first two exist."""
    if project:
        return project
    configured = ((config if config is not None else load_config()).get("memory") or {}).get("engram_project")
    if configured:
        return str(configured)
    env = os.environ.get("ENGRAM_PROJECT")
    if env:
        return env
    return Path(repo or os.getcwd()).resolve().name


def save(title: str, body: str, kind: str = DEFAULT_KIND, topic_key: str | None = None,
         project: str | None = None, repo: Path | None = None) -> bool:
    config = load_config()
    if not memory_enabled(config):
        return False
    binary = shutil.which("engram")
    if not binary:
        return False
    argv = [binary, "save", title, body, "--type", kind, "--project", resolve_project(project, config, repo)]
    if topic_key:
        argv += ["--topic", topic_key]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--kind", default=DEFAULT_KIND)
    parser.add_argument("--topic-key", default=None)
    parser.add_argument("--project", default=None)
    args = parser.parse_args(argv)
    saved = save(args.title, args.body, args.kind, args.topic_key, args.project)
    print(json.dumps({"saved": saved}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
