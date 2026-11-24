#!/usr/bin/env python3
"""Validator of necessary-comment/smoke-verdict-routing: round/004-routing.json routes as the skill says.

Called as `check_routing.py WORKSPACE TESTDATA`. The run starts at the skill's first step: the
script's list is the answer of the kit's measure tool, which the case carries as
`mocks/metodo/comment_gate_measure.md` (the real answer of `comment_gate_measure` on the staged
change: seven new comments, one of them a NEEDS-COMMENT marker). The agent already answered, since
an eval launches no role agent: `round/003-comment-verdicts.json` is staged (seven verdicts in the
shape of `03-tools/schemas/comment-gate-output.schema.json`). The run is asked who gets each
comment, saved as `round/004-routing.json`. The skill's text decides it (02-skills/necessary-comment/SKILL.md,
step 4 and "Escalate to the owner"): UNNECESSARY, and NECESSARY or KDOC-INTERFACE with a
`proposed_text`, go to `generic-mechanic`; MAKE-SELF-EXPLANATORY goes to `generic-judge`; a
MAKE-SELF-EXPLANATORY on a critical path (`config/project.json`) and a NEEDS-COMMENT the gate could
not word (epistemic Unknown) go to the owner. Its iron law adds that no one writes a comment by
hand at this step. The answer key, `answer-key.json`, holds the route of each verdict and the
sha256 of each staged source file. The validator reads the saved routing, the staged source files
and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing     round/004-routing.json is not among the files the run left
  output-unreadable  it is not JSON, or not a list of entries with file, line and to
  route-missing      a verdict has no entry
  route-wrong        an entry sends a comment where the skill does not, or not where it must
  route-unlisted     an entry names a file and line no verdict carries: never a line the script
                     did not list
  source-edited      a staged source file changed or is gone: the mechanic applies, not this run

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How the routing is read. A JSON list of objects, or an object whose only list is that list. Each
entry names its file under `file` (or `path`, as the verdicts do), its line as a number (or its
digits in a string) and its destination under `to`, a string or a list of strings. A destination is
recognised by the word of the role inside it, in any letter case: `mechanic`, `judge`, `owner`
(`destinations` of the answer key; the prompt gives the word `owner`, the skill gives the two
roles). Several entries for one file and line add up. A file is matched whole, or by its trailing
part when the entry left the leading folders out.

How a route is judged. Each route of the answer key says where the comment `must` go and where it
must `never` go; anything else beside them is accepted. So the critical-path rename passes as
`owner` and as `generic-judge` with the owner, and fails as `generic-judge` alone or with the
mechanic. A destination that names none of the three words (`developer`, `delete it`) is a wrong
route: the run did not route as the skill does.

What it cannot see. Whether the run knew why: an entry that says `owner` for the right comment
passes whatever its reason, and the judge reads the answer for that. Whether the run saved the
script's list in the round as it came. The two steps the staged round replaces (the agent's
verdicts, the verify of the mechanic's result): they need role agents and the mechanic's commits,
which the case format does not stage.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys


def read_entries(text: str) -> list[dict] | None:
    """The entries of the saved routing as [{path, line, to: [str]}]; None when it has another shape."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        lists = [value for value in data.values() if isinstance(value, list)]
        data = lists[0] if len(lists) == 1 else None
    if not isinstance(data, list) or not data:
        return None
    entries: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        path = item.get("file", item.get("path"))
        line = item.get("line")
        to = item.get("to")
        to = [to] if isinstance(to, str) else to
        if isinstance(line, str) and line.strip().isdigit():
            line = int(line)
        if (not isinstance(path, str) or isinstance(line, bool) or not isinstance(line, int)
                or not isinstance(to, list) or not to or not all(isinstance(one, str) for one in to)):
            return None
        path = path.strip()
        entries.append({"path": path[2:] if path.startswith("./") else path, "line": line, "to": to})
    return entries


def same_file(entry_path: str, route_path: str) -> bool:
    return entry_path == route_path or route_path.endswith("/" + entry_path)


def broken_rules(entries: list[dict], workspace: pathlib.Path, key: dict) -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    wrong: list[tuple[str, str]] = []
    claimed: set[int] = set()
    for route in key["routes"]:
        where = f"{route['path']}:{route['line']}"
        said: list[str] = []
        for index, entry in enumerate(entries):
            if entry["line"] == route["line"] and same_file(entry["path"], route["path"]):
                claimed.add(index)
                said += entry["to"]
        if not said:
            missing.append(("route-missing", f"{where} has no entry; every verdict is routed"))
            continue
        goes = {word for word in key["destinations"] if any(word in one.casefold() for one in said)}
        if not set(route["must"]) <= goes or goes & set(route["never"]):
            wrong.append(("route-wrong", f'{where} ({route["verdict"]}) goes to "{"; ".join(said)}"; {route["why"]}'))

    unlisted = [("route-unlisted", f"{entry['path']}:{entry['line']} is in no verdict; no line enters that the script did not list")
                for index, entry in enumerate(entries) if index not in claimed]

    edited: list[tuple[str, str]] = []
    for path, sha in sorted(key["sources"].items()):
        source = workspace / path
        by_hand = "no one writes a comment by hand at this step"
        if not source.is_file():
            edited.append(("source-edited", f"{path} is gone; {by_hand}"))
        elif hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            edited.append(("source-edited", f"{path} changed; {by_hand}"))
    return missing + wrong + unlisted + edited


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        text = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    entries = read_entries(text)
    if entries is None:
        print(f"output-unreadable: {key['saved_file']} is not a JSON list of entries with file, line and to", file=sys.stderr)
        return 1
    broken = broken_rules(entries, pathlib.Path(workspace), key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
