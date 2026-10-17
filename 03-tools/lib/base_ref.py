#!/usr/bin/env python3
"""The one place the repo's base ref is resolved, so no script hardcodes a
branch name. Order: an explicit ref, then the active config's
`test_sectors.base_ref`, then the remote's default branch
(`refs/remotes/origin/HEAD`, what `git clone` leaves), and only then
`origin/develop`.

The active config is METODO_PROJECT_CONFIG when set, else the tools root's
config/project.json (the same rule as hooks/_common.py).

Usage:
    lib/base_ref.py <repo> [--config project.json] [--base REF]
Prints the resolved ref on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
FALLBACK = "origin/develop"


def config_path() -> Path:
    return Path(os.environ.get("METODO_PROJECT_CONFIG") or TOOLS_ROOT / "config" / "project.json")


def load_config(path: Path | None = None) -> dict:
    try:
        data = json.loads(Path(path or config_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def from_config(config: dict | None) -> str | None:
    return ((config or {}).get("test_sectors") or {}).get("base_ref") or None


def remote_default(repo: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def resolve(repo: Path, config: dict | None = None, explicit: str | None = None) -> str:
    return explicit or from_config(config) or remote_default(Path(repo)) or FALLBACK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("--config", default=None, help="project.json (default: the active config)")
    parser.add_argument("--base", default=None, help="explicit ref; wins over everything")
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    print(resolve(Path(args.repo), config, args.base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
