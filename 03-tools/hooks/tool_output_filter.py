#!/usr/bin/env python3
"""PostToolUse Bash: a long output reaches the model as a summary (WU12).

Claude Code documents `updatedToolOutput` on PostToolUse: it "Replaces the
tool's output with the provided value before it is sent to Claude. The value
must match the tool's output shape" (Bash: stdout, stderr, interrupted,
isImage). Over `context.tool_output_max_tokens` (default 2000, tokens =
ceil(chars / 4)) the hook saves the full output to
out/hooks/<session>/outputs/<seq>.txt and replaces stdout with a summary that
fits the cap: the first and last lines, and every line matching
`context.tool_output_patterns` (a pattern with a capital letter matches case
by case, a lowercase one ignores case), so the line that mattered stays in
view; the last line is `METODO-OUTPUT full: <path>`.

Never filtered: tools other than Bash, outputs at or under the cap, image
output, and any output it cannot save outside the target repo (a save dir
inside the repo counts only when git ignores it). A cap of 0 turns it off.
The exit code is not in the documented PostToolUse Bash shape (a non-zero
exit fires PostToolUseFailure instead), so the summary does not claim one.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

HOOK = "tool_output_filter"
DEFAULT_MAX_TOKENS = 2000
DEFAULT_HEAD_LINES = 20
DEFAULT_TAIL_LINES = 20
DEFAULT_PATTERNS = ("error", "fail", "traceback", "exception", "assert", "FAILED", "ERROR")
LINE_MAX_CHARS = 240
FULL_PREFIX = "METODO-OUTPUT full: "


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def settings(config: dict) -> dict:
    context = config.get("context") if isinstance(config.get("context"), dict) else {}

    def number(key, default):
        value = context.get(key, default)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    patterns = context.get("tool_output_patterns")
    if not (isinstance(patterns, list) and all(isinstance(p, str) and p for p in patterns)):
        patterns = list(DEFAULT_PATTERNS)
    return {"max_tokens": number("tool_output_max_tokens", DEFAULT_MAX_TOKENS),
            "head": max(0, number("tool_output_head_lines", DEFAULT_HEAD_LINES)),
            "tail": max(0, number("tool_output_tail_lines", DEFAULT_TAIL_LINES)),
            "patterns": patterns}


def match_at(line: str, patterns: list[str]) -> int:
    """Index of the first pattern hit in `line`, or -1. Smart case: a pattern
    with any capital letter is case-sensitive, an all-lowercase one is not."""
    folded = line.lower()
    hits = []
    for pattern in patterns:
        exact = any(c.isupper() for c in pattern)
        at = line.find(pattern) if exact else folded.find(pattern)
        if at >= 0:
            hits.append(at)
    return min(hits) if hits else -1


def clip(line: str, at: int = -1) -> str:
    """At most LINE_MAX_CHARS; a long matching line keeps a window around the hit."""
    if len(line) <= LINE_MAX_CHARS:
        return line
    start = max(0, min(at - LINE_MAX_CHARS // 3, len(line) - LINE_MAX_CHARS)) if at >= 0 else 0
    body = line[start:start + LINE_MAX_CHARS - 2]
    return ("\u2026" if start else "") + body + "\u2026"


def summarize(text: str, cap_tokens: int, cfg: dict, saved: str, interrupted: bool = False) -> str:
    """Deterministic: same text and settings, same summary. Budget order is
    matching lines (in order), then the tail (last first), then the head; a
    section stops at its first line that does not fit."""
    lines = text.splitlines()
    total = len(lines)
    hits = {i: match_at(line, cfg["patterns"]) for i, line in enumerate(lines)}
    matches = [i for i in range(total) if hits[i] >= 0]
    tail = list(range(total - 1, max(total - cfg["tail"], 0) - 1, -1))
    head = [i for i in range(min(cfg["head"], total)) if i not in tail]
    rendered = {i: clip(lines[i], hits[i]) for i in set(matches) | set(head) | set(tail)}

    footer = FULL_PREFIX + saved
    gap_cost = len(f"[... {total} lines omitted ...]") + 1
    kept: set[int] = set()

    def header() -> str:
        kept_matches = sum(1 for i in matches if i in kept)
        return (f"METODO-OUTPUT filtered: {total} lines, {tokens(text)} tokens over the {cap_tokens}-token cap; "
                f"kept {kept_matches} of {len(matches)} matching lines, head {sum(1 for i in head if i in kept)}, "
                f"tail {sum(1 for i in tail if i in kept)}" + ("; interrupted" if interrupted else ""))

    # The header's width only grows with digits already bounded by `total`.
    fixed = len(header()) + len(str(total)) * 3 + 1 + len(footer)
    used = fixed + gap_cost  # gaps are at most the kept runs plus one
    limit = cap_tokens * 4
    for section in (matches, tail, head):
        for i in section:
            if i in kept:
                continue
            delta_runs = 1 - (i - 1 in kept) - (i + 1 in kept)
            cost = len(rendered[i]) + 1 + delta_runs * gap_cost
            if used + cost > limit:
                break
            kept.add(i)
            used += cost

    body: list[str] = []
    previous = -1
    for i in sorted(kept):
        if i - previous > 1:
            body.append(f"[... {i - previous - 1} lines omitted ...]")
        body.append(rendered[i])
        previous = i
    if total - previous > 1:
        body.append(f"[... {total - previous - 1} lines omitted ...]")
    return "\n".join([header(), *body, footer])


def save_dir_allowed(target: Path, inp: dict) -> bool:
    """Never inside the target repo, unless git ignores that place."""
    repo = _common.repo_root(inp)
    if repo is None:
        return True
    try:
        target.resolve().relative_to(repo.resolve())
    except ValueError:
        return True
    probe = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(target)], capture_output=True)
    return probe.returncode == 0


def save(text: str, inp: dict) -> Path | None:
    outputs = _common.session_dir(inp) / "outputs"
    if not save_dir_allowed(outputs, inp):
        return None
    try:
        outputs.mkdir(parents=True, exist_ok=True)
        seq = len(list(outputs.glob("*.txt"))) + 1
        while True:  # exclusive create: two parallel calls never share a file
            path = outputs / f"{seq}.txt"
            try:
                with path.open("x", encoding="utf-8") as fh:
                    fh.write(text)
                return path
            except FileExistsError:
                seq += 1
    except OSError:
        return None


def main() -> int:
    inp = _common.read_input()
    if inp.get("tool_name") != "Bash":
        return 0
    response = inp.get("tool_response")
    if not isinstance(response, dict) or response.get("isImage"):
        return 0
    stdout, stderr = response.get("stdout"), response.get("stderr") or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return 0
    config = _common.load_config()
    # bare (RDD off) and an owner/profile OFF pass the output through untouched; LOG and up filter
    if not _common.rdd_enabled(config) or _common.hook_mode(config, HOOK, inp) == "off":
        return 0
    cfg = settings(config)
    cap = cfg["max_tokens"]
    text = stdout + (("" if stdout.endswith("\n") or not stdout else "\n") + "--- stderr ---\n" + stderr if stderr else "")
    if cap <= 0 or tokens(text) <= cap:
        return 0
    path = save(text, inp)
    if path is None:
        return 0
    summary = summarize(text, cap, cfg, str(path), bool(response.get("interrupted")))
    updated = dict(response, stdout=summary, stderr="")
    _common.ledger(inp, HOOK, "tool-output-filtered", "replace", "on",
                   reason=f"{tokens(text)} -> {tokens(summary)} tokens", path=str(path), tool="Bash")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_common.run_guarded(main))
