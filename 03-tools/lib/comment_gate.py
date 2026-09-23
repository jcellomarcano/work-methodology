#!/usr/bin/env python3
"""Locates and measures the comments a diff ADDS in Kotlin and Java files.

This is the deterministic half of the comment gate (DOC-001): this script
says WHAT new comments exist, where, how big they are, and what shape they
have; the `generic-comment-gate` agent decides whether they deserve to
exist and `generic-mechanic` applies the decision. No verdict comes out of
here, only facts.

Analysis mode. For every comment the diff adds at least one line to (a new
comment, or an existing one that gets a line added): path, line, type
(line | block | kdoc | marker), text, word count, sentence count, words in
the longest sentence, the statement it annotates, whether that statement is
a public or internal surface (a KDoc candidate), a list of deterministic
signals (commented-out code, narrates the diff, restates the code, not in
English, secret shape, sentence too long), plus, on a `kdoc` entry, DOC-002's
`summary`/`block_tags`/`empty_block_tags` and `kdoc_*` flags, and on every
entry DOC-003's `action_tags` field and `action_tag_*` flags (`--config`
supplies the accepted `ticket_keys`). Comments the diff did not add do not
appear: old code, ticket-only comments.

--verify mode. Checks that a range (the mechanic's) touched ONLY comment
lines or removed NEEDS-COMMENT markers, and that no marker remains in the
files of that range (or of --range, if given). Any changed code line is a
FAIL. Declared limitation: inside a block comment, each line must start
with `*` to be recognized as a comment.

Usage:
    lib/comment_gate.py --repo <repo> (--range A..B | --worktree <dir>) [--scope-glob G ...]
    lib/comment_gate.py --repo <repo> --verify B..HEAD [--range A..B]

Output: JSON on stdout with sorted keys, no timestamps or absolute paths,
with the common header (schema_version, tool_sha, tool_versions, repo_sha,
repo_dirty). Exit 0 on analysis; on --verify, 1 if FAIL.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, toolenv  # noqa: E402

SOURCE_GLOBS = ("*.kt", "*.java")
MARKER = "NEEDS-COMMENT"
MAX_SENTENCE_WORDS = 30
RESTATES_RATIO = 0.6
STATEMENT_MAX_CHARS = 200
DEFAULT_CONFIG_PATH = TOOLS_ROOT / "config" / "project.json"

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DECLARATION_RE = re.compile(
    r"^(?!private\b)(?:(?:public|internal|protected|open|abstract|override|suspend|inline|data|sealed|enum|"
    r"annotation|value|expect|actual|external|const|lateinit|operator|infix|tailrec|static|final|synchronized)\s+)*"
    r"(?:fun|class|interface|object|val|var|typealias|void|int|long|boolean|String)\b"
)
WORD_RE = re.compile(r"[A-Za-z0-9_']+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
KDOC_OPENER_SUBJECT_RE = re.compile(r"^(?:An?|The)\s+`?([A-Za-z_][\w.]*)`?\s+is\s+(?:an?|the)\b", re.IGNORECASE)
KDOC_OPENER_KIND_RE = re.compile(r"^(?:This|The|It)\s+(?:is|method|function|class|property|object|interface)\b", re.IGNORECASE)
DECLARED_IDENT_RE = re.compile(r"\b(?:fun|class|interface|object|val|var|typealias)\s+([A-Za-z_]\w*)")
BLOCK_TAG_RE = re.compile(r"@([A-Za-z]+)([^@]*)")
ACTION_TAG_RE = re.compile(r"(?im)^\s*(TODO|FIXME|STOPSHIP)\b(?!\s+(?:is|are|was|were)\b)")
TAG_IDENT_RE = re.compile(r"^(?:TODO|FIXME|STOPSHIP)\(([^)]*)\)", re.IGNORECASE)
TICKET_RE = re.compile(r"^([A-Z][A-Z0-9]*)-(\d+)$")
TRACKED_TODO_RE = re.compile(r"^TODO\([A-Z][A-Z0-9]*-\d+\):\s+\S")
NARRATES_DIFF_RE = re.compile(
    r"^(?:removed?|fix(?:ed)?|chang(?:e|ed)|add(?:ed)?|refactor(?:ed)?|moved?|renamed?|updated?|deleted?)\b",
    re.IGNORECASE,
)
COMMENTED_CODE_RES = (
    re.compile(r"^(?:val|var|fun|return|import|package|override|private|internal|public|throw|class|object)\b"),
    re.compile(r"^[\w.]+\(.*\)\s*;?$"),
    re.compile(r"^[\w.\[\]]+\s*(?:=|\+=|-=)\s*\S"),
    re.compile(r"[;{}]\s*$"),
)
SECRET_RES = (
    re.compile(r"[0-9a-fA-F]{32,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\s*[=:]\s*[A-Za-z0-9_./+=-]{12,}"),
)
SPANISH_WORDS = {
    "el", "la", "los", "las", "que", "para", "porque", "una", "uno", "del", "con", "sin", "pero",
    "aquí", "también", "cuando", "esto", "esta", "este", "tiene", "hay", "sino", "donde",
}
ENGLISH_STOPWORDS = {
    "the", "this", "that", "and", "for", "with", "from", "into", "when", "then", "than", "are",
    "was", "were", "has", "have", "not", "but", "its", "our", "you", "all", "any", "can",
}
CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")


# ---------------------------------------------------------------- git helpers

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _matches_scope(path: str, scope_globs: list[str]) -> bool:
    if not scope_globs:
        return True
    return any(fnmatch.fnmatch(path, g) for g in scope_globs)


def _is_source(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in SOURCE_GLOBS)


def added_lines_from_diff(diff_text: str) -> dict[str, set[int]]:
    """Map of path -> line numbers (in the new version) that the diff adds."""
    added: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if path is not None:
                added.setdefault(path, set())
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git") or raw.startswith("index "):
            continue
        match = HUNK_RE.match(raw)
        if match:
            new_line = int(match.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            added[path].add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        elif raw.startswith("\\"):
            continue
        else:
            new_line += 1
    return added


def changed_lines_from_diff(diff_text: str) -> dict[str, list[tuple[str, int, str]]]:
    """Map of path -> [(sign, line, text)] for '+' and '-' lines; the line
    of a '-' is from the old version, the line of a '+' from the new one."""
    changed: dict[str, list[tuple[str, int, str]]] = {}
    path: str | None = None
    old_line = new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if path is not None:
                changed.setdefault(path, [])
            continue
        if raw.startswith("--- "):
            source = raw[4:].strip()
            if source != "/dev/null" and path is None:
                # whole-file deletion: the old path is the only one available
                path = source[2:] if source.startswith("a/") else source
                changed.setdefault(path, [])
            continue
        if raw.startswith("diff --git") or raw.startswith("index "):
            path = None
            continue
        match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if match:
            old_line, new_line = int(match.group(1)), int(match.group(2))
            continue
        if path is None or raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            changed[path].append(("+", new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-"):
            changed[path].append(("-", old_line, raw[1:]))
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return changed


def _range_right(range_arg: str) -> str | None:
    if ".." not in range_arg:
        return None
    right = range_arg.split("..")[-1].strip()
    return right or "HEAD"


def _file_at(repo: Path, ref: str | None, path: str, worktree: Path | None) -> str:
    if worktree is not None or ref is None:
        base = worktree if worktree is not None else repo
        return (base / path).read_text(encoding="utf-8", errors="replace")
    return _git(repo, "show", f"{ref}:{path}")


# ----------------------------------------------------------- comment scanner

def _strip_string_literals(line: str) -> str:
    """Replaces the content of string literals with spaces so a `//` inside
    a string does not count as a comment. Heuristic: unescaped double
    quotes; enough for application Kotlin and Java."""
    out = []
    in_string = False
    escaped = False
    for ch in line:
        if in_string:
            out.append(" ")
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(" ")
            continue
        out.append(ch)
    return "".join(out)


def scan_comments(text: str) -> list[dict]:
    """Returns every comment in the file with its lines (1-based), type, and
    clean text. Consecutive `//` lines are grouped into a single comment; a
    `//` with code before it is its own inline comment."""
    lines = text.splitlines()
    comments: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        visible = _strip_string_literals(raw)
        if stripped.startswith("/*"):
            kind = "kdoc" if stripped.startswith("/**") and not stripped.startswith("/**/") else "block"
            start = i
            body: list[str] = []
            while i < n:
                body.append(lines[i])
                if "*/" in lines[i]:
                    break
                i += 1
            end = min(i, n - 1)
            comments.append(_comment_entry(kind, start + 1, end + 1, body, inline=False))
            i = end + 1
            continue
        if stripped.startswith("//"):
            start = i
            body = []
            while i < n and lines[i].strip().startswith("//"):
                body.append(lines[i])
                i += 1
            comments.append(_comment_entry("line", start + 1, i, body, inline=False))
            continue
        marker_pos = visible.find("//")
        if marker_pos >= 0 and visible[:marker_pos].strip():
            comments.append(
                _comment_entry("line", i + 1, i + 1, [raw[marker_pos:]], inline=True,
                               inline_code=raw[:marker_pos].strip())
            )
        i += 1
    return comments


def _clean_comment_lines(body: list[str]) -> list[str]:
    """Per-physical-line cleaned text, before joining (needed to apply
    ACTION_TAG_RE the way detekt applies it: one line at a time)."""
    parts = []
    for line in body:
        s = line.strip()
        s = re.sub(r"^/\*+", "", s)
        s = re.sub(r"\*/\s*$", "", s)
        s = re.sub(r"^//+", "", s)
        s = re.sub(r"^\*+", "", s)
        parts.append(s.strip())
    return parts


def _clean_comment_text(body: list[str]) -> str:
    return " ".join(p for p in _clean_comment_lines(body) if p).strip()


def _comment_entry(kind: str, first: int, last: int, body: list[str], inline: bool,
                   inline_code: str | None = None) -> dict:
    lines = _clean_comment_lines(body)
    text = " ".join(p for p in lines if p).strip()
    if text.startswith(MARKER):
        kind = "marker"
    return {
        "kind": kind, "first_line": first, "last_line": last, "text": text,
        "inline": inline, "inline_code": inline_code, "lines": lines,
    }


def _statement_after(lines: list[str], last_line: int) -> str:
    """First non-empty, non-comment line after the comment."""
    j = last_line  # last_line is 1-based: the next index is last_line
    while j < len(lines):
        s = lines[j].strip()
        if s and not s.startswith("//") and not s.startswith("/*") and not s.startswith("*"):
            return s[:STATEMENT_MAX_CHARS]
        j += 1
    return ""


# ------------------------------------------------------------------ metrics

def _tokens(text: str) -> list[str]:
    return [t for t in (w.lower() for w in CAMEL_SPLIT_RE.split(text) if w) if len(t) > 2]


def _flags(kind: str, text: str, statement: str, max_sentence_words: int) -> list[str]:
    flags: set[str] = set()
    if kind != "kdoc" and any(r.search(text) for r in COMMENTED_CODE_RES):
        flags.add("commented_out_code")
    if NARRATES_DIFF_RE.match(text):
        flags.add("narrates_diff")
    comment_tokens = [t for t in _tokens(text) if t not in ENGLISH_STOPWORDS]
    if len(comment_tokens) >= 3 and statement:
        statement_tokens = set(_tokens(statement))
        shared = sum(1 for t in comment_tokens if t in statement_tokens)
        if shared / len(comment_tokens) >= RESTATES_RATIO:
            flags.add("restates_code")
    words = {w.lower() for w in WORD_RE.findall(text)}
    if len(words & SPANISH_WORDS) >= 2:
        flags.add("non_english")
    if any(r.search(text) for r in SECRET_RES):
        flags.add("has_secret_shape")
    if max_sentence_words > MAX_SENTENCE_WORDS:
        flags.add("too_long")
    return sorted(flags)


def _kdoc_fields(text: str) -> dict:
    """DOC-002 fields: `summary` is the first sentence of `text` with block
    tags stripped; `block_tags`/`empty_block_tags` come from every `@tag`
    found in `text`, in order. `_tag_details` is private, popped by the
    caller once `_kdoc_flags` has used it."""
    tag_details = [(m.group(1), m.group(2).strip()) for m in BLOCK_TAG_RE.finditer(text)]
    prose_match = re.search(r"(?<!\S)@[A-Za-z]", text)
    prose = text[:prose_match.start()].strip() if prose_match else text.strip()
    sentences = [s for s in SENTENCE_SPLIT_RE.split(prose) if s.strip()]
    return {
        "summary": sentences[0].strip() if sentences else "",
        "block_tags": [name for name, _ in tag_details],
        "empty_block_tags": [name for name, desc in tag_details if not desc],
        "_tag_details": tag_details,
    }


def _kdoc_redundant_tag(tag_details: list[tuple[str, str]], statement: str) -> bool:
    ident_m = DECLARED_IDENT_RE.search(statement) if statement else None
    function_name = ident_m.group(1) if ident_m else ""
    for name, desc in tag_details:
        lowered = name.lower()
        if lowered == "param":
            words = desc.split(maxsplit=1)
            if len(words) < 2:
                continue
            target, body = words[0], words[1]
        elif lowered == "return":
            target, body = function_name, desc
        else:
            continue
        desc_tokens = [t for t in _tokens(body) if t not in ENGLISH_STOPWORDS]
        target_tokens = set(_tokens(target))
        if not desc_tokens or not target_tokens:
            continue
        shared = sum(1 for t in desc_tokens if t in target_tokens)
        if shared / len(desc_tokens) >= RESTATES_RATIO:
            return True
    return False


def _kdoc_flags(fields: dict, tag_details: list[tuple[str, str]], statement: str) -> set[str]:
    flags: set[str] = set()
    summary = fields["summary"]
    if not summary:
        flags.add("kdoc_no_summary")
        return flags
    if KDOC_OPENER_KIND_RE.match(summary):
        flags.add("kdoc_banned_opener")
    else:
        subject_m = KDOC_OPENER_SUBJECT_RE.match(summary)
        ident_m = DECLARED_IDENT_RE.search(statement) if (subject_m and statement) else None
        if subject_m and ident_m and subject_m.group(1).lower() == ident_m.group(1).lower():
            flags.add("kdoc_banned_opener")
    if fields["empty_block_tags"]:
        flags.add("kdoc_empty_block_tag")
    if _kdoc_redundant_tag(tag_details, statement):
        flags.add("kdoc_redundant_tag")
    return flags


def _action_tags(cleaned_lines: list[str], first_line: int) -> list[dict]:
    """DOC-003 field: `ACTION_TAG_RE` runs per physical line, before the
    lines are joined into `text` (detekt's own documented semantics)."""
    tags = []
    for offset, line in enumerate(cleaned_lines):
        match = ACTION_TAG_RE.match(line)
        if not match:
            continue
        ident_m = TAG_IDENT_RE.match(line)
        tags.append({
            "line": first_line + offset,
            "word": match.group(1).upper(),
            "identifier": ident_m.group(1).strip() if ident_m else None,
            "_raw_line": line,
        })
    return tags


def _action_tag_flags(tag: dict, line_text: str, ticket_keys: list[str] | None) -> set[str]:
    flags: set[str] = set()
    if tag["word"] in ("FIXME", "STOPSHIP"):
        flags.add("action_tag_forbidden")
    identifier = tag["identifier"]
    if not identifier:
        flags.add("action_tag_untracked")
        return flags
    ticket_m = TICKET_RE.match(identifier)
    if not ticket_m:
        flags.add("action_tag_bad_identifier")
        return flags
    if ticket_keys is not None and ticket_m.group(1) not in ticket_keys:
        flags.add("action_tag_bad_identifier")
        return flags
    if not TRACKED_TODO_RE.match(line_text):
        flags.add("action_tag_malformed")
    return flags


def describe(path: str, comment: dict, lines: list[str], ticket_keys: list[str] | None = None) -> dict:
    text = comment["text"]
    words = WORD_RE.findall(text)
    sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()] if text else []
    max_sentence_words = max((len(WORD_RE.findall(s)) for s in sentences), default=0)
    statement = comment["inline_code"] if comment["inline"] else _statement_after(lines, comment["last_line"])
    kind = comment["kind"]
    flags = set(_flags(kind, text, statement, max_sentence_words))

    entry = {
        "path": path,
        "line": comment["first_line"],
        "kind": kind,
        "inline": comment["inline"],
        "text": text,
        "words": len(words),
        "sentences": len(sentences),
        "max_sentence_words": max_sentence_words,
        "statement": statement,
        "kdoc_candidate": bool(DECLARATION_RE.match(statement)) if statement else False,
    }

    if kind == "kdoc":
        kdoc_fields = _kdoc_fields(text)
        tag_details = kdoc_fields.pop("_tag_details")
        flags |= _kdoc_flags(kdoc_fields, tag_details, statement)
        entry.update(kdoc_fields)

    action_tags = _action_tags(comment["lines"], comment["first_line"])
    for tag in action_tags:
        raw_line = tag.pop("_raw_line")
        flags |= _action_tag_flags(tag, raw_line, ticket_keys)
    entry["action_tags"] = action_tags

    entry["flags"] = sorted(flags)
    return entry


# ----------------------------------------------------------------- analysis

def analyze(repo: Path, range_arg: str | None = None, worktree: Path | None = None,
            scope_globs: list[str] | None = None, ticket_keys: list[str] | None = None) -> dict:
    scope_globs = scope_globs or []
    if worktree is not None:
        diff_text = _git(worktree, "diff", "-U0", "--no-color", "HEAD", "--", *SOURCE_GLOBS)
        added = added_lines_from_diff(diff_text)
        untracked = _git(worktree, "ls-files", "--others", "--exclude-standard", "--", *SOURCE_GLOBS)
        for path in untracked.splitlines():
            if path.strip():
                count = len((worktree / path).read_text(encoding="utf-8", errors="replace").splitlines())
                added[path] = set(range(1, count + 1))
        ref = None
        repo_sha = _git(worktree, "rev-parse", "HEAD").strip()
        repo_dirty = True
        range_label = f"worktree:{worktree.name}"
    else:
        assert range_arg is not None
        diff_text = _git(repo, "diff", "-U0", "--no-color", range_arg, "--", *SOURCE_GLOBS)
        added = added_lines_from_diff(diff_text)
        ref = _range_right(range_arg)
        repo_sha = _git(repo, "rev-parse", ref or "HEAD").strip()
        repo_dirty = baseline.is_repo_dirty(repo)
        range_label = range_arg

    comments: list[dict] = []
    for path in sorted(added):
        if not _is_source(path) or not _matches_scope(path, scope_globs) or not added[path]:
            continue
        text = _file_at(repo, ref, path, worktree)
        lines = text.splitlines()
        for comment in scan_comments(text):
            touched = range(comment["first_line"], comment["last_line"] + 1)
            if any(line in added[path] for line in touched):
                comments.append(describe(path, comment, lines, ticket_keys=ticket_keys))

    comments.sort(key=lambda c: (c["path"], c["line"]))
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, toolenv.tool_versions(TOOLS_ROOT), repo_dirty)
    payload.update({
        "range": range_label,
        "comments": comments,
        "summary": {
            "total": len(comments),
            "markers": sum(1 for c in comments if c["kind"] == "marker"),
            "kdoc": sum(1 for c in comments if c["kind"] == "kdoc"),
            "flagged": sum(1 for c in comments if c["flags"]),
            "action_tags": sum(len(c["action_tags"]) for c in comments),
            "kdoc_flagged": sum(1 for c in comments if c["kind"] == "kdoc" and c["flags"]),
        },
    })
    return payload


# ------------------------------------------------------------------- verify

def _is_comment_only_line(text: str) -> bool:
    s = text.strip()
    return (not s) or s.startswith("//") or s.startswith("/*") or s.startswith("*")


def verify(repo: Path, verify_range: str, range_arg: str | None = None) -> dict:
    diff_all = _git(repo, "diff", "--name-only", verify_range)
    non_source = sorted(p for p in diff_all.splitlines() if p.strip() and not _is_source(p))
    diff_text = _git(repo, "diff", "-U0", "--no-color", verify_range, "--", *SOURCE_GLOBS)
    changed = changed_lines_from_diff(diff_text)

    offending: list[dict] = []
    for path in non_source:
        offending.append({"path": path, "line": 0, "text": "", "reason": "non_source_file_changed"})
    for path in sorted(changed):
        for sign, line, text in changed[path]:
            if _is_comment_only_line(text):
                continue
            offending.append({"path": path, "line": line, "text": text.strip()[:STATEMENT_MAX_CHARS],
                              "reason": "code_line_removed" if sign == "-" else "code_line_added"})

    head = _range_right(verify_range) or "HEAD"
    files_to_scan = set(changed)
    if range_arg:
        files_to_scan |= {p for p in _git(repo, "diff", "--name-only", range_arg).splitlines() if _is_source(p)}
    remaining: list[dict] = []
    for path in sorted(files_to_scan):
        try:
            content = _git(repo, "show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            continue  # deleted in HEAD: no marker can remain
        for idx, line in enumerate(content.splitlines(), start=1):
            if MARKER in line:
                remaining.append({"path": path, "line": idx, "text": line.strip()[:STATEMENT_MAX_CHARS]})

    verdict = "PASS" if not offending and not remaining else "FAIL"
    repo_sha = _git(repo, "rev-parse", head).strip()
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, toolenv.tool_versions(TOOLS_ROOT),
                                     baseline.is_repo_dirty(repo))
    payload.update({
        "verify_range": verify_range,
        "marker_scope": range_arg or verify_range,
        "offending": offending,
        "remaining_markers": remaining,
        "verdict": verdict,
    })
    return payload


# --------------------------------------------------------------------- config

def _load_ticket_keys(config_path: Path) -> list[str] | None:
    """DOC-003 accepted project keys, from `config/project.json:ticket_keys`.
    Missing file, unreadable JSON, or a missing/malformed key degrades to
    `None` (shape-only: never emits action_tag_bad_identifier for an
    unknown key), the pattern `change_card_validator.py` already uses."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    keys = data.get("ticket_keys")
    return keys if isinstance(keys, list) else None


# --------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--range", default=None, help="e.g. 'origin/develop..HEAD'")
    parser.add_argument("--worktree", default=None, help="directory of a worktree with uncommitted changes")
    parser.add_argument("--scope-glob", action="append", default=[], help="repeatable; limits the paths analyzed")
    parser.add_argument("--config", default=None,
                        help="project.json with ticket_keys; defaults to TOOLS_ROOT/config/project.json")
    parser.add_argument("--verify", default=None, metavar="B..HEAD",
                        help="checks that this range only touched comments and left no NEEDS-COMMENT")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if args.verify:
        result = verify(repo, args.verify, args.range)
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        return 0 if result["verdict"] == "PASS" else 1

    if bool(args.range) == bool(args.worktree):
        parser.error("pass exactly one of --range or --worktree (or --verify)")
    worktree = Path(args.worktree).resolve() if args.worktree else None
    config_path = Path(args.config).resolve() if args.config else DEFAULT_CONFIG_PATH
    ticket_keys = _load_ticket_keys(config_path)
    result = analyze(repo, args.range, worktree, args.scope_glob, ticket_keys=ticket_keys)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
