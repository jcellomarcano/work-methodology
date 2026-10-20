#!/usr/bin/env python3
"""bench.py: measure a Claude Code harness, kit or setup (stdlib only, runs in vanilla too).

Usage:
  bench.py session [--root DIR] [--project PATH|SUBSTR] [--since YYYY-MM-DD] [--window-table FILE] [--out DIR]
  bench.py ab --config ab.json [--out DIR] [--dry-run]
  bench.py judge --run DIR
  bench.py report --run DIR [--out DIR]

session: observational report over existing transcripts (correlational only).
ab, judge, report: the A/B experiment; they need bench_ab.py next to this script.
Usage errors exit 2.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

# This file runs from a skill folder that the kit installer copies entry by entry with plain cp:
# a __pycache__ directory left next to it would break the next install, so write no bytecode.
sys.dont_write_bytecode = True

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

AB_COMMANDS = {"ab": "main_ab", "judge": "main_judge", "report": "main_report"}


def _usage(stream) -> None:
    print(__doc__.strip(), file=stream)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _usage(sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        _usage(sys.stdout)
        return 0
    if cmd == "session":
        import bench_session
        return bench_session.main(rest)
    if cmd in AB_COMMANDS:
        try:
            bench_ab = importlib.import_module("bench_ab")
        except ModuleNotFoundError as exc:
            if exc.name != "bench_ab":
                raise
            print(f"bench.py {cmd}: the A/B module (bench_ab.py) is not next to this script; "
                  "`bench.py session` still works.", file=sys.stderr)
            return 2
        try:
            return getattr(bench_ab, AB_COMMANDS[cmd])(rest)
        except SystemExit as exc:  # an argparse usage error or --help inside bench_ab
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    print(f"bench.py: unknown subcommand {cmd!r}", file=sys.stderr)
    _usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
