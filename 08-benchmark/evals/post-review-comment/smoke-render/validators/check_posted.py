#!/usr/bin/env python3
"""Validator of post-review-comment/smoke-render: posted.md is the script's own rendering.

Called as `check_posted.py WORKSPACE TESTDATA`. The answer key, `expected-posted.md`, is what
`03-tools/lib/review_comment_post.py render` prints for the staged comment: the anchor line, one
bullet per tag, the snippet untouched. Trailing spaces and blank lines at the end do not count.
Exit 0 when posted.md matches it; 1 with one line on stderr when it is missing or differs.
"""
import pathlib
import sys


def lines_of(path: pathlib.Path) -> list[str]:
    return [line.rstrip() for line in path.read_text(encoding="utf-8").rstrip().splitlines()]


def main(workspace: str, testdata: str) -> int:
    posted = pathlib.Path(workspace) / "posted.md"
    if not posted.is_file():
        print("posted.md is missing from the files the run left", file=sys.stderr)
        return 1
    try:
        got, expected = lines_of(posted), lines_of(pathlib.Path(testdata) / "expected-posted.md")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"cannot read posted.md or the answer key: {exc}", file=sys.stderr)
        return 1
    for number, (ours, theirs) in enumerate(zip(expected, got), 1):
        if ours != theirs:
            print(f"posted.md line {number} is {theirs!r}, the script renders {ours!r}", file=sys.stderr)
            return 1
    if len(got) != len(expected):
        print(f"posted.md has {len(got)} lines, the script renders {len(expected)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
