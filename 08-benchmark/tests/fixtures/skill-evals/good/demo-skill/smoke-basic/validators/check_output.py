#!/usr/bin/env python3
"""Fixture validator: exit 0 when `src/app.py` in the workspace carries the wording of the answer key.

The runner calls it as `check_output.py WORKSPACE TESTDATA`, with the workspace as cwd.
"""
import pathlib
import sys

workspace, testdata = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
expected = (testdata / "expected.txt").read_text(encoding="utf-8").strip()
source = workspace / "src" / "app.py"
if not source.is_file():
    sys.exit("src/app.py is missing")
if expected not in source.read_text(encoding="utf-8"):
    sys.exit(f"src/app.py does not return {expected!r}")
