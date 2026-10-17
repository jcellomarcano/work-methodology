#!/usr/bin/env python3
"""Turns a linted review comment into the posted form, and posts it (review-comment step 5).

`render` takes a comment that already passes review_comment_lint (RC-01..07): a first line, either the
`path:line ...` anchor with its trailing `@ sha` or, for a PR-level comment, a line with no backtick
anchor; then ONE paragraph with the four parts in order, English or Spanish labels; then the proposal in
a fenced code block. It rewrites the paragraph into one bullet per tag and leaves the first line and the
snippet block untouched. `anchor` reads the `path:line` off that first line, or `None` for a PR-level
comment. `payload` builds the Bitbucket comment body, with an `inline` block only when anchored.

`post` creates or updates that rendered comment on a Bitbucket pull request. It is dry-run by default:
`--confirm` is required to actually send. The token is read from a file and never printed, in a dry-run
or in an error.

Usage:
    lib/review_comment_post.py render <comment.md> [--out file]
    lib/review_comment_post.py post <comment.md> --repo WORKSPACE/REPO --pr N
        [--comment-id CID] [--token-file ~/.config/metodo/bitbucket-token] [--ledger file.json] [--confirm]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent

_LABELS: dict[str, list[str]] = {
    "en": ["What happens:", "Why it happens:", "Impact:", "How to fix:"],
    "es": ["Qué sucede:", "Por qué sucede:", "Cómo afecta:", "Cómo solucionar:"],
}

_ANCHOR_RE = re.compile(r"^`(?P<path>[\w./-]+):(?P<line>\d+)(?:-\d+)?(?::[^`]*)?`")

_API_BASE = "https://api.bitbucket.org/2.0/repositories"


class PostError(Exception):
    def __init__(self, http_status: int, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.message = message


def _load_config() -> dict:
    path = TOOLS_ROOT / "config" / "review-comment.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _match(text: str, labels: list[str]) -> tuple[list[int], str | None]:
    positions: list[int] = []
    cursor = 0
    low = text.lower()
    for label in labels:
        idx = low.find(label.lower(), cursor)
        if idx < 0:
            return positions, label
        positions.append(idx)
        cursor = idx + len(label)
    return positions, None


def _match_best(text: str, label_sets: dict[str, list[str]]) -> tuple[list[str], list[int]]:
    best: tuple[list[str], str, list[int]] | None = None
    for labels in label_sets.values():
        positions, missing = _match(text, labels)
        if missing is None:
            return labels, positions
        if best is None or len(positions) > len(best[2]):
            best = (labels, missing, positions)
    _, missing, _ = best
    raise ValueError(f"missing label: {missing}")


def _paragraph_end(rest: str, start: int) -> int:
    candidates = [i for i in (rest.find("\n\n", start), rest.find("```", start)) if i >= 0]
    return min(candidates) if candidates else len(rest)


def render(text: str) -> str:
    config = _load_config()
    label_sets = config.get("posted_labels") or _LABELS
    first_line, _, rest = text.partition("\n")
    labels, positions = _match_best(rest, label_sets)
    paragraph_end = _paragraph_end(rest, positions[-1] + len(labels[-1]))
    parts = []
    for i, (label, pos) in enumerate(zip(labels, positions)):
        start = pos + len(label)
        end = positions[i + 1] if i + 1 < len(positions) else paragraph_end
        parts.append(rest[start:end].strip())
    snippet = rest[paragraph_end:].lstrip("\n")
    bullets = "\n".join(f"- **{label}** {part}" for label, part in zip(labels, parts))
    return f"{first_line}\n\n{bullets}\n\n{snippet}"


def anchor(text: str) -> dict | None:
    first_line = text.partition("\n")[0]
    match = _ANCHOR_RE.match(first_line)
    if not match:
        return None
    return {"path": match.group("path"), "line": int(match.group("line"))}


def payload(text: str, rendered: str) -> dict:
    result: dict = {"content": {"raw": rendered}}
    anc = anchor(text)
    if anc is not None:
        result["inline"] = {"path": anc["path"], "to": anc["line"]}
    return result


def _comment_url(repo: str, pr: str, comment_id: str | None) -> tuple[str, str]:
    base = f"{_API_BASE}/{repo}/pullrequests/{pr}/comments"
    if comment_id:
        return f"{base}/{comment_id}", "PUT"
    return base, "POST"


def _read_token(token_file: str) -> str:
    return Path(token_file).expanduser().read_text(encoding="utf-8").strip()


def _send(url: str, method: str, token: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            message = detail
        raise PostError(exc.code, message) from None


def _append_ledger(ledger_path: Path, entry: dict) -> None:
    entries = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
    entries.append(entry)
    ledger_path.write_text(json.dumps(entries, sort_keys=True, indent=2), encoding="utf-8")


def _read_comment(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    render_parser = sub.add_parser("render", help="turns a linted paragraph comment into the bullet form")
    render_parser.add_argument("comment", help="file with the comment, or - for stdin")
    render_parser.add_argument("--out", help="write the rendered comment here instead of stdout")

    post_parser = sub.add_parser("post", help="creates or updates a Bitbucket PR comment")
    post_parser.add_argument("comment", help="file with the comment, or - for stdin")
    post_parser.add_argument("--repo", required=True, help="WORKSPACE/REPO")
    post_parser.add_argument("--pr", required=True, help="pull request id")
    post_parser.add_argument("--comment-id", help="existing comment id: PUT instead of POST")
    post_parser.add_argument("--token-file", default="~/.config/metodo/bitbucket-token")
    post_parser.add_argument("--ledger", help="JSON file to append the posted/updated id to")
    post_parser.add_argument("--confirm", action="store_true", help="actually send; without it, dry-run only")

    args = parser.parse_args(argv)
    text = _read_comment(args.comment)

    try:
        rendered = render(text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.command == "render":
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0

    body = payload(text, rendered)
    url, method = _comment_url(args.repo, args.pr, args.comment_id)

    if not args.confirm:
        print(json.dumps({"action": "dry-run", "method": method, "payload": body, "url": url}, sort_keys=True))
        return 0

    token = _read_token(args.token_file)
    try:
        http_status, response_body = _send(url, method, token, body)
    except PostError as exc:
        print(json.dumps({"error": exc.message, "http": exc.http_status}, sort_keys=True), file=sys.stderr)
        return 1

    comment_id = response_body.get("id")
    action = "updated" if args.comment_id else "posted"
    print(json.dumps({"action": action, "http": http_status, "id": comment_id}, sort_keys=True))
    if args.ledger:
        _append_ledger(Path(args.ledger), {
            "comment_file": args.comment, "http": http_status, "id": comment_id,
            "method": method, "pr": args.pr,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
