#!/usr/bin/env python3
"""PreToolUse Bash (and the receipt_start|finalize|acknowledge MCP tools);
PostToolUse Bash only logs. Absolute: `git push --force` without lease is
always denied; a subagent never pushes, opens a PR, merges, tags, or
opens/closes/acknowledges receipts. Non-absolute (RDD): in the main session a
push/PR/merge without an approved receipt for the pushed tree warns or asks
(block); --no-verify, --amend and rebase are only logged.

A done-gate waiver (bin/done-waive.sh, T14) is the owner's: a subagent is
denied and the main session's agent always gets an ask, RDD on or off. It is
recognized by mention, not by a list of prefix words (T19): every simple
command of the line, including $(...), backticks, `sh -c '...'`, eval and a
heredoc fed to a shell or interpreter, counts when it names done-waive or
waive_main, unless its command word only reads (cat, grep, sed without -i,
echo, git, ...). Writing the hooks ledger by hand is the same gate (kind
ledger-write): a redirect, tee, cp/mv/ln/install/rsync destination, dd of=,
rm/truncate/touch, or sed/perl -i on a ledger.jsonl or under the hooks dir.
Text inside quotes is data. A guardrail against a silent self-grant, not a
signature: a program that opens the file itself (python open(), awk system())
still gets through; the ledger shows it.

A command with several gate kinds is judged kind by kind: each gets its
ledger line (and its -outcome line on PostToolUse), the strongest decision
wins (deny > ask > warn) and the reason names every kind."""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "guard_gates"
# Each command is split into segments (| ; && || and line breaks) and only
# the command word of each segment is checked: an `echo '... git push ...'`
# is not a push. Guardrail, not a sandbox: `bash -c "git push"` is invisible
# to it, and the ledger measures what slips through.
SEGMENT_SPLIT = re.compile(r"\|\||&&|[|;\n]")
PREFIX = r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:command\s+|sudo\s+|time\s+)?"
GIT = PREFIX + r"git\s+(?:-C\s+\S+\s+)?(?:--?[A-Za-z-]+(?:=\S+)?\s+)*"
GATES = (
    ("gate-push", re.compile(GIT + r"push\b(?P<rest>.*)$")),
    ("gate-pr", re.compile(PREFIX + r"gh\s+pr\s+(create|merge)\b")),
    ("gate-merge", re.compile(GIT + r"merge\b")),
    ("gate-tag", re.compile(GIT + r"tag\s+(?!-l|--list)(-a|-s|-m|-f|[A-Za-z0-9])")),
    ("gate-receipt", re.compile(PREFIX + r"(?:python3?\s+)?\S*rdd_receipt\.py\s+(?:--\S+\s+\S+\s+)*(start|finalize|acknowledge)\b")),
)
# T19: owner gates by mention over every simple command (see the docstring).
MENTION = re.compile(r"(?<![\w-])done-waive(?:\.sh)?(?![\w-])|\bwaive_main\b")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
READ_ONLY = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ls", "wc", "file", "stat",
             "diff", "cmp", "echo", "printf", "git", "sed", "shasum", "sha256sum", "md5", "md5sum", "test", "["}
CONTROL = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "(", ")", "time"}
WRAPPERS = {"command", "exec", "sudo", "nohup", "nice", "timeout", "env", "xargs", "stdbuf", "builtin"}
COPY_LIKE = {"cp", "mv", "ln", "install", "rsync"}      # the last argument is the destination
TOUCH_LIKE = {"rm", "truncate", "touch", "tee", "shred", "unlink"}  # every argument is written
IN_PLACE = {"sed", "gsed", "perl"}                       # written only with -i
SEPARATOR = re.compile(r"^[;&|]+$")
REDIRECT_TOKEN = re.compile(r"^&?>[>|&]?$")
VAR_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
IN_PLACE_FLAG = re.compile(r"^(?:-[A-Za-z]*i|--in-place)")
HEREDOC_BODY_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\1(?=\n|$)", re.DOTALL)
SUBST_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
OWNER_KINDS = ("gate-waiver", "ledger-write")
WAIVER_REASON = ("a done-gate waiver is the owner's step (bin/done-waive.sh from the owner's terminal); "
                 "confirm only if the owner asked for this waiver, it is recorded with their email")
LEDGER_REASON = ("the hooks ledger (out/hooks) is written by the hooks and the owner's bin/done-waive.sh only; "
                 "confirm only if the owner asked for this write")
SUBAGENT_REASON = {"gate-waiver": "A done-gate waiver is the owner's: report the unproven rule in your output.",
                   "ledger-write": "The hooks ledger is the hooks' and the owner's: report the need in your output."}
SUBAGENT_LEDGER = {"gate-waiver": "subagents never waive a done-gate rule",
                   "ledger-write": "subagents never write the hooks ledger"}
DELIVERY_DENY = ("Delivery (push, PR, merge, tag) and receipt start/finalize/acknowledge are the owner's: "
                 "report it in your output.")
STRENGTH = {"deny": 3, "ask": 2, "warn": 1}
LOG_ONLY = (
    ("no-verify", re.compile(GIT + r"(?:push|commit)\b.*--no-verify")),
    ("amend", re.compile(GIT + r"commit\b.*--amend")),
    ("rebase", re.compile(GIT + r"rebase\b")),
)
FORCE_RE = re.compile(r"(^|\s)(--force|-f)(\s|$)")
LEASE_RE = re.compile(r"--force-with-lease|--force-if-includes")
INTEGRATION_BRANCHES = ("develop", "master", "main", "release")


HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1(?=\n|$)", re.DOTALL)


def strip_heredocs(command: str) -> str:
    """A heredoc's body is data (a file being written), not a command: a
    `git push --force` line inside a README is not a push."""
    return HEREDOC_RE.sub("<<HEREDOC", command or "")


def segments(command: str) -> list[str]:
    return [seg for seg in SEGMENT_SPLIT.split(strip_heredocs(command)) if seg.strip()]


def push_segments(command: str) -> list[re.Match]:
    return [m for seg in segments(command) if (m := GATES[0][1].match(seg))]


def is_force_push(command: str) -> bool:
    for match in push_segments(command):
        rest = match.group("rest")
        if FORCE_RE.search(rest) and not LEASE_RE.search(rest):
            return True
    return False


def pushed_ref(command: str) -> str:
    for match in push_segments(command):
        try:
            words = [w for w in shlex.split(match.group("rest"), posix=True) if not w.startswith("-")]
        except ValueError:
            words = []
        if len(words) >= 2:
            return words[1].split(":")[0] or "HEAD"
    return "HEAD"


def _ledger_target(word: str, inp: dict) -> bool:
    word = word.strip("'\"")
    return bool(word) and (word.rsplit("/", 1)[-1] == "ledger.jsonl" or c.in_hooks_dir(word, inp))


def _tokens(text: str) -> list[str]:
    """Shell words with quotes removed; `;`, `&&`, `|`, `>`... are their own tokens, a quoted one is data."""
    try:
        lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return text.replace("\n", " ; ").split()


def _commands(text: str, depth: int = 0):
    """Yields (words, heredoc bodies) for each simple command in `text`,
    descending into $(...) and backticks; each heredoc body goes to the
    command that receives it."""
    if not text or depth > 3:
        return
    bodies = [m.group(2) for m in HEREDOC_BODY_RE.finditer(text)]
    flat = strip_heredocs(text)
    for m in SUBST_RE.finditer(flat):
        yield from _commands(m.group(1) if m.group(1) is not None else m.group(2), depth + 1)
    words: list[str] = []
    for tok in _tokens(SUBST_RE.sub(" ", flat)) + [";"]:
        if not SEPARATOR.match(tok):
            words.append(tok)
            continue
        if words:
            n = sum(1 for i, w in enumerate(words) if w == "HEREDOC" and i and words[i - 1].startswith("<<"))
            yield words, bodies[:n]
            del bodies[:n]
        words = []


def _effective(words: list[str]) -> int:
    """Index of the command word after control words, VAR=val and wrappers (env, timeout 60, xargs -n1, ...)."""
    i = 0
    while i < len(words):
        t, prev = words[i], words[i - 1].rsplit("/", 1)[-1] if i else ""
        if (t in CONTROL or VAR_ASSIGN.match(t) or t.rsplit("/", 1)[-1] in WRAPPERS
                or (i and t.startswith("-")) or (prev in ("timeout", "nice", "-n") and t[:1].isdigit())):
            i += 1
            continue
        break
    return i


def _args(words: list[str], i: int) -> list[str]:
    out, skip = [], False
    for t in words[i + 1:]:
        if skip:
            skip = False
        elif REDIRECT_TOKEN.match(t) or t in ("<", "<<", "<<<"):
            skip = True
        elif not t.startswith("-") and t not in ("(", ")", "HEREDOC"):
            out.append(t)
    return out


def _nested(words: list[str], i: int) -> str | None:
    """The command text a shell -c or eval runs, if any."""
    cmd, rest = words[i].rsplit("/", 1)[-1], words[i + 1:]
    if cmd in SHELLS and "-c" in rest and rest.index("-c") + 1 < len(rest):
        return rest[rest.index("-c") + 1]
    if cmd == "eval":
        return " ".join(rest)
    return None


def is_waiver(command: str) -> bool:
    for words, bodies in _commands(command):
        i = _effective(words)
        if i >= len(words):
            continue
        cmd = words[i].rsplit("/", 1)[-1]
        nested = _nested(words, i)
        if nested is not None:
            if is_waiver(nested):
                return True
            continue
        if cmd in SHELLS and any(is_waiver(b) for b in bodies):
            return True
        if cmd in READ_ONLY and not (cmd in IN_PLACE and any(IN_PLACE_FLAG.match(t) for t in words[i + 1:])):
            continue
        if any(MENTION.search(w) for w in words[i:]) or (cmd not in SHELLS and any(MENTION.search(b) for b in bodies)):
            return True
    return False


def writes_ledger(command: str, inp: dict) -> bool:
    """A redirect, tee or file command that writes a ledger.jsonl or under the hooks dir."""
    for words, bodies in _commands(command):
        if any(REDIRECT_TOKEN.match(t) and k + 1 < len(words) and _ledger_target(words[k + 1], inp)
               for k, t in enumerate(words)):
            return True
        i = _effective(words)
        if i >= len(words):
            continue
        cmd, args = words[i].rsplit("/", 1)[-1], _args(words, i)
        nested = _nested(words, i)
        if nested is not None and writes_ledger(nested, inp):
            return True
        if cmd in SHELLS and any(writes_ledger(b, inp) for b in bodies):
            return True
        if ((cmd in COPY_LIKE and args and _ledger_target(args[-1], inp))
                or (cmd in TOUCH_LIKE and any(_ledger_target(a, inp) for a in args))
                or (cmd == "dd" and any(a.startswith("of=") and _ledger_target(a[3:], inp) for a in args))
                or (cmd in IN_PLACE and any(IN_PLACE_FLAG.match(t) for t in words[i + 1:])
                    and any(_ledger_target(a, inp) for a in args))):
            return True
    return False


def classify(command: str, tool_name: str, inp: dict | None = None) -> list[str]:
    if tool_name.startswith("mcp__metodo__receipt_"):
        return ["gate-receipt"]
    kinds = ["gate-waiver"] if is_waiver(command or "") else []
    for seg in segments(command):
        for kind, regex in GATES:
            if regex.match(seg):
                if kind == "gate-merge" and not any(b in seg for b in INTEGRATION_BRANCHES):
                    continue
                if kind not in kinds:
                    kinds.append(kind)
    if writes_ledger(command or "", inp or {}):
        kinds.append("ledger-write")
    return kinds


def log_only_kinds(command: str) -> list[str]:
    return [kind for kind, regex in LOG_ONLY if any(regex.match(seg) for seg in segments(command))]


def _emit(event: str | None, found: list[tuple[str, str, str]]) -> None:
    """One output for every (kind, decision, message): the strongest decision
    wins; with more than one kind the message names each."""
    if event != "PreToolUse" or not found:
        return
    decision = max((d for _, d, _ in found), key=STRENGTH.__getitem__)
    text = " | ".join(dict.fromkeys(f"{k}: {m}" if len(found) > 1 else m for k, _, m in found))
    if decision == "warn":
        c.emit_warn(event, found[0][0], text)
    else:
        c.emit_pretool(decision, text)


def _delivery(inp: dict, config: dict, command: str, event: str | None, kinds: list[str]) -> list[tuple[str, str, str]]:
    repo = c.repo_root(inp)
    tree = c.current_tree(repo, pushed_ref(command) if "gate-push" in kinds else "HEAD")
    receipt = c.receipt_for(tree)
    receipt_state = (receipt or {}).get("verdict") or ("open" if receipt else "none")
    mode = c.hook_mode(config, HOOK, tree=tree)  # the profile's tier: the receipt of the tree delivered
    reason = f"no approved receipt for tree {tree[:12] if tree else '?'} (receipt: {receipt_state})"
    found = []
    for kind in kinds:
        if event == "PostToolUse":
            c.ledger(inp, HOOK, kind + "-outcome", "ran", mode, "", tree=tree, receipt=receipt_state)
        elif kind == "gate-receipt":
            c.ledger(inp, HOOK, kind, "allow", "log", "owner session", tree=tree, receipt=receipt_state)
        elif receipt_state == "approved":
            c.ledger(inp, HOOK, kind, "allow", mode, "receipt approved", tree=tree, receipt=receipt_state)
        elif mode == "block":
            c.ledger(inp, HOOK, kind, "ask", mode, reason, tree=tree, receipt=receipt_state)
            found.append((kind, "ask", reason + ". Run receipt-review first, or confirm to deliver without receipt (it will be recorded)."))
        elif mode in ("off", "log"):  # nothing is shown, so the line says log, never warn
            c.ledger(inp, HOOK, kind, "log", mode, reason, tree=tree, receipt=receipt_state)
        else:
            c.ledger(inp, HOOK, kind, "warn", mode, reason, tree=tree, receipt=receipt_state)
            found.append((kind, "warn", reason + "; run receipt-review first, or tell the owner this delivers without review."))
    return found


def main() -> int:
    inp = c.read_input()
    tool_name = inp.get("tool_name") or ""
    command = (inp.get("tool_input") or {}).get("command") or ""
    event = inp.get("hook_event_name")
    subagent = c.is_subagent(inp)

    if tool_name == "Bash" and is_force_push(command):
        if event == "PreToolUse":
            c.ledger(inp, HOOK, "force-push", "deny", "block", "git push --force without --force-with-lease")
            c.emit_pretool("deny", "git push --force is never allowed: use --force-with-lease (methodology.md paragraph 6).")
        return 0

    kinds = classify(command, tool_name, inp)
    if not kinds:
        if event == "PreToolUse":
            for kind in log_only_kinds(command):
                c.ledger(inp, HOOK, kind, "log", "log", "")
        return 0

    found: list[tuple[str, str, str]] = []
    if subagent:
        if event == "PreToolUse":
            for kind in kinds:
                owner = kind in OWNER_KINDS
                c.ledger(inp, HOOK, kind, "deny", "block",
                         SUBAGENT_LEDGER[kind] if owner else "subagents never deliver or open/close receipts")
                found.append((kind, "deny", SUBAGENT_REASON[kind] if owner else DELIVERY_DENY))
            _emit(event, found)
        return 0

    for kind in (k for k in kinds if k in OWNER_KINDS):  # RDD on or off
        if event == "PreToolUse":
            c.ledger(inp, HOOK, kind, "ask", "block", "owner gate")
            found.append((kind, "ask", WAIVER_REASON if kind == "gate-waiver" else LEDGER_REASON))
        else:
            c.ledger(inp, HOOK, kind + "-outcome", "ran", "block", "")
    delivery = [k for k in kinds if k not in OWNER_KINDS]
    if delivery:
        config = c.load_config()
        if c.rdd_enabled(config):
            found += _delivery(inp, config, command, event, delivery)
    _emit(event, found)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
