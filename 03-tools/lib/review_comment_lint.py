#!/usr/bin/env python3
"""Checks the shape of a code review comment (review-comment skill).

A correct comment has: a `path:line` reference (with an optional `@ sha`); ONE paragraph with four parts
in this order, `Qué sucede:` `Por qué sucede:` `Cómo afecta:` `Cómo solucionar:` (or their English
equivalents), short (caps in config/review-comment.json); and a proposal in a code block whose language
matches the cited file's extension. With `--scope <pr_scope.json>` it also checks that the commented
file belongs to the PR and is not base-branch noise.

Rules: RC-01 four parts in order - RC-02 a single paragraph - RC-03 character caps - RC-04 path:line
reference - RC-05 proposal in the code's language - RC-06 no filler, no preamble, no em dash -
RC-07 file inside the PR (only with --scope). JSON output with sorted keys, `tool_sha`, `config_sha`;
exit 1 on any FAIL.

Usage:
    lib/review_comment_lint.py comment.md [--scope pr_scope.json] [--lang es|en]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import output_lint  # noqa: E402

_FENCE = re.compile(r"^```(\w*)\s*$")
_REF = re.compile(r"`?(?P<path>[\w./-]+\.(?P<ext>[A-Za-z0-9]{1,8})):(?P<line>\d+)(?:-\d+)?`?")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _rule(rule_id: str, status: str, note: str = "", evidence: list | None = None) -> dict:
    entry = {"evidence": evidence or [], "id": rule_id, "status": status}
    if note:
        entry["note"] = note
    return entry


def _split(text: str) -> tuple[list[str], list[tuple[str, list[str]]], bool]:
    """Splits prose from code blocks. Returns (prose lines, [(language, lines)], open fence)."""
    prose: list[str] = []
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    lang = ""
    for line in text.splitlines():
        m = _FENCE.match(line.strip())
        if m:
            if current is None:
                lang, current = m.group(1).lower(), []
            else:
                blocks.append((lang, current))
                current = None
            continue
        (current if current is not None else prose).append(line)
    return prose, blocks, current is not None


def check(text: str, config: dict, lint_config: dict, lang: str | None = None, scope: dict | None = None) -> dict:
    prose, blocks, open_fence = _split(text)
    body = "\n".join(prose)
    low = body.lower()
    rules: list[dict] = []

    # RC-04 reference
    ref = _REF.search(body)
    rules.append(_rule("RC-04", "PASS" if ref else "FAIL", "" if ref else "no path:line"))

    # RC-01 four parts in order (language detected by the first label if not fixed)
    langs = [lang] if lang else list(config["labels"])
    chosen, positions = None, []
    for code in langs:
        pos = [low.find(label) for label in config["labels"][code]]
        if all(p >= 0 for p in pos):
            chosen, positions = code, pos
            break
    if chosen is None:
        missing = [label for code in langs for label in config["labels"][code] if low.find(label) < 0]
        rules.append(_rule("RC-01", "FAIL", "missing parts: " + ", ".join(sorted(set(missing))[:4])))
    elif positions != sorted(positions):
        rules.append(_rule("RC-01", "FAIL", "parts out of order"))
    else:
        rules.append(_rule("RC-01", "PASS", f"language {chosen}"))

    # RC-02 a single paragraph: the four parts with no blank line between the first and the last
    if chosen:
        first, last = positions[0], positions[-1]
        segment = body[first:last]
        rules.append(_rule("RC-02", "FAIL" if "\n\n" in segment else "PASS", "blank line between parts" if "\n\n" in segment else ""))
    else:
        rules.append(_rule("RC-02", "SKIP", "no parts"))

    # RC-03 character caps
    if chosen:
        labels = config["labels"][chosen]
        parts = []
        for i, label in enumerate(labels):
            start = positions[i] + len(label)
            end = positions[i + 1] if i + 1 < len(labels) else len(body)
            parts.append(" ".join(body[start:end].split()))
        total = sum(len(p) for p in parts)
        over = [f"{labels[i]} {len(p)} > {config['max_chars_per_part']}" for i, p in enumerate(parts) if len(p) > config["max_chars_per_part"]]
        if total > config["max_chars_total"]:
            over.append(f"total {total} > {config['max_chars_total']}")
        rules.append(_rule("RC-03", "FAIL" if over else "PASS", "; ".join(over) if over else f"total {total}"))
    else:
        rules.append(_rule("RC-03", "SKIP", "no parts"))

    # RC-05 proposal in the code's language
    if open_fence:
        rules.append(_rule("RC-05", "FAIL", "unclosed ``` fence"))
    elif not blocks:
        rules.append(_rule("RC-05", "FAIL", "no code block with the proposal"))
    else:
        expected = config["language_by_extension"].get(ref.group("ext").lower()) if ref else None
        tags = [b[0] for b in blocks]
        if any(not t for t in tags):
            rules.append(_rule("RC-05", "FAIL", "code block with no language tag"))
        elif expected is None:
            rules.append(_rule("RC-05", "WARN", "extension with no language known in config; tags: " + ", ".join(tags)))
        elif expected not in tags:
            rules.append(_rule("RC-05", "FAIL", f"the file is {expected}; the proposal is in {', '.join(tags)}"))
        else:
            rules.append(_rule("RC-05", "PASS", expected))

    # RC-06 no filler, no preamble, no em dash
    problems = []
    first_line = next((l for l in prose if l.strip()), "")
    if output_lint._starts_with_any(output_lint._strip_markup(first_line), lint_config["preambles"]):
        problems.append("preamble")
    for l in prose:
        hit = output_lint._contains_any(l, lint_config["fillers"])
        if hit:
            problems.append(f"filler: {hit}")
    if "—" in body:
        problems.append("em dash")
    rules.append(_rule("RC-06", "FAIL" if problems else "PASS", "; ".join(sorted(set(problems)))))

    # RC-07 file inside the PR
    if scope is None:
        rules.append(_rule("RC-07", "SKIP", "no --scope"))
    elif not ref:
        rules.append(_rule("RC-07", "SKIP", "no reference"))
    else:
        path = ref.group("path")
        pr_files = {f["path"] for f in scope.get("pr_files", [])}
        drift = set(scope.get("base_drift_files", []))
        if path in drift:
            rules.append(_rule("RC-07", "FAIL", f"{path} is base-branch noise, not part of the PR"))
        elif not any(p == path or p.endswith("/" + path) for p in pr_files):
            rules.append(_rule("RC-07", "FAIL", f"{path} is not among the PR's files"))
        else:
            rules.append(_rule("RC-07", "PASS"))

    rules.sort(key=lambda r: r["id"])
    statuses = [r["status"] for r in rules]
    return {
        "rules": rules,
        "summary": {s: statuses.count(s) for s in ("PASS", "WARN", "FAIL", "SKIP")},
        "verdict": "FAIL" if "FAIL" in statuses else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    here = TOOLS_ROOT / "config"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="file with the comment, or - for stdin")
    parser.add_argument("--scope", help="JSON from pr_scope.py")
    parser.add_argument("--lang", choices=["es", "en"])
    parser.add_argument("--config", default=str(here / "review-comment.json"))
    parser.add_argument("--lint-config", default=str(here / "output-lint.json"))
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    lint_config = json.loads(Path(args.lint_config).read_text(encoding="utf-8"))
    scope = json.loads(Path(args.scope).read_text(encoding="utf-8")) if args.scope else None
    result = check(text, config, lint_config, args.lang, scope)
    result["config_sha"] = _sha(config_path)
    result["tool_sha"] = _sha(Path(__file__).resolve())
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    if result["verdict"] == "FAIL":
        for rule in result["rules"]:
            if rule["status"] == "FAIL":
                print(f"FAIL {rule['id']}: {rule.get('note', '')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
