#!/usr/bin/env python3
"""Validator of review-comment/smoke-base-drift: the comments under comments/ are on the pull request.

Called as `check_comments.py WORKSPACE TESTDATA`. The case stages a reviewer's notes with two
findings, the saved scope of the pull request (`round/001-pr-scope.json`, real output of the kit's
`pr_scope.py`) and the code at the pull request's tip. One finding is on a file the pull request
changed; the other is on a file that only the base branch changed after the branch was cut, which
the web diff shows as if the author had touched it. The skill's iron law says that second file
never gets a comment and that a comment has four parts in one paragraph and a proposal in the
file's language. The answer key, `answer-key.json`, holds the two lists of the staged scope, the
file that must get a comment, and the labels, caps and language of the kit's
`config/review-comment.json`. It reads the `.md` files under `comments/` and the answer key,
nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing         comments/ holds no .md file among the files the run left
  base-drift-commented   a comment names a file of `base_drift_files`: it belongs to the base branch
  reference-missing      a comment cites no path:line
  not-in-pr              the file a comment cites is not among the pull request's files
  four-parts             a comment lacks one of the four parts, or has them out of order
  one-paragraph          a blank line separates the parts of a comment
  caps                   a part or the four together are longer than the caps
  proposal-language      a comment has no closed code block tagged with the cited file's language
  finding-uncommented    no comment cites the pull request file the notes raise a finding on

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How a comment is read. The way the kit's lint reads it (`03-tools/lib/review_comment_lint.py`),
so a comment the lint passes is not failed here for its shape: code blocks are split from the
prose, the first `path:line` of the prose is the file the comment is on, the four labels are
looked for in the prose without case (English or Spanish, as the lint accepts both), a part runs
from its label to the next one, and its length is counted with its whitespace collapsed. A cited
path names a listed file when it is that path or its tail (`RetryPolicy.kt` for
`billing/RetryPolicy.kt`).

One rule is stricter than the lint, on purpose: the lint looks only at the first `path:line`, so
one long comment that opens on a pull request file and then also asks for a change in a base
branch file passes it. Here a file of `base_drift_files` named anywhere in a comment, by its path
or by its file name, breaks `base-drift-commented`: the skill says those files never get comments
and that findings never go into one long comment.

What it does not read: the lint's rule against filler, preamble and the em dash (its word lists
live in a config file of the kit, outside the workspace), whether the proposal compiles, and
whether the diagnosis is right.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

FENCE = re.compile(r"^```(\w*)\s*$")
REF = re.compile(r"`?(?P<path>[\w./-]+\.(?P<ext>[A-Za-z0-9]{1,8})):(?P<line>\d+)(?:-\d+)?`?")


def split(text: str) -> tuple[list[str], list[str], bool]:
    """(prose lines, the language tag of each closed code block, a fence was left open)."""
    prose: list[str] = []
    tags: list[str] = []
    inside = False
    for line in text.splitlines():
        fence = FENCE.match(line.strip())
        if fence:
            if not inside:
                tag = fence.group(1).lower()
            else:
                tags.append(tag)
            inside = not inside
            continue
        if not inside:
            prose.append(line)
    return prose, tags, inside


def names(cited: str, listed: str) -> bool:
    """True when the cited path is the listed file or its tail."""
    return listed == cited or listed.endswith("/" + cited)


def parts_of(low: str, labels: dict) -> tuple[list[str], list[int]] | None:
    """(labels, their positions) for the first language whose four labels are all in the prose."""
    for language in labels:
        positions = [low.find(label) for label in labels[language]]
        if all(position >= 0 for position in positions):
            return labels[language], positions
    return None


def broken_in(name: str, text: str, key: dict) -> tuple[list[tuple[str, str]], str | None]:
    """The broken rules of one comment, and the pull request file it is on (None when it is on none)."""
    broken: list[tuple[str, str]] = []
    prose, tags, open_fence = split(text)
    body = "\n".join(prose)
    low = body.lower()

    drift = next((listed for listed in key["base_drift_files"]
                  if listed in text or pathlib.PurePosixPath(listed).name in text), None)
    if drift:
        broken.append(("base-drift-commented", f"{name} comments on {drift}, which the base branch changed, not the pull request"))

    ref = REF.search(body)
    on = None
    if ref is None:
        broken.append(("reference-missing", f"{name} cites no path:line"))
    else:
        cited = ref.group("path")
        on = next((listed for listed in key["pr_files"] if names(cited, listed)), None)
        if on is None and not any(names(cited, listed) for listed in key["base_drift_files"]):
            broken.append(("not-in-pr", f"{name} comments on {cited}, which is not among the pull request's files"))

    found = parts_of(low, key["labels"])
    if found is None or found[1] != sorted(found[1]):
        order = " ".join(next(iter(key["labels"].values())))
        broken.append(("four-parts", f"{name} does not carry the four parts in order ({order})"))
    else:
        labels, positions = found
        if "\n\n" in body[positions[0]:positions[-1]]:
            broken.append(("one-paragraph", f"{name} has a blank line between its parts"))
        lengths = []
        for index, label in enumerate(labels):
            end = positions[index + 1] if index + 1 < len(labels) else len(body)
            lengths.append(len(" ".join(body[positions[index] + len(label):end].split())))
        over = [f"{label} {length} > {key['max_chars_per_part']}" for label, length in zip(labels, lengths)
                if length > key["max_chars_per_part"]]
        if sum(lengths) > key["max_chars_total"]:
            over.append(f"total {sum(lengths)} > {key['max_chars_total']}")
        if over:
            broken.append(("caps", f"{name} goes over the caps ({'; '.join(over)})"))

    if ref is not None:
        language = key["language_by_extension"].get(ref.group("ext").lower())
        if language is not None and (open_fence or language not in tags or any(not tag for tag in tags)):
            broken.append(("proposal-language",
                           f"{name} has no closed code block tagged {language}, the language of {ref.group('path')}"))
    return broken, on


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    folder = pathlib.Path(workspace) / key["comments_dir"]
    files = sorted(path for path in folder.rglob("*.md") if path.is_file()) if folder.is_dir() else []
    if not files:
        print(f"output-missing: {key['comments_dir']}/ holds no .md file among the files the run left", file=sys.stderr)
        return 1
    broken: list[tuple[str, str]] = []
    commented: set[str] = set()
    for path in files:
        name = path.relative_to(workspace).as_posix()
        found, on = broken_in(name, path.read_text(encoding="utf-8", errors="replace"), key)
        broken += found
        if on:
            commented.add(on)
    for listed in key["must_comment"]:
        if listed not in commented:
            broken.append(("finding-uncommented", f"no comment cites {listed}, the pull request file the notes raise a finding on"))
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    rules = list(dict.fromkeys(rule for rule, _what in broken))
    if len(rules) > 1:
        print(f"{len(rules)} rules broken: {', '.join(rules)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
