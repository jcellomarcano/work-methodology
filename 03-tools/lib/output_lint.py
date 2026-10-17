#!/usr/bin/env python3
"""Checks a reply addressed to a human against the COM-xx rules (07-communication/rules.md).

The script locates and counts; it does not judge. Rules with the `proposed` detector (COM-07, COM-13,
COM-16, COM-17) come out as SKIP with detector "reviewer": a reviewer looks at them with rules.md as
the rulebook.

Input: a markdown file with the reply (or `-` for stdin). Optional: `--type` (question | status |
decision | failure | investigation | clarification), `--lang` (one of the config's languages),
`--audience` (public | owner), `--allow COM-xx` (repeatable: the owner downgrades that FAIL to WARN and
it stays recorded in the output), `--config`, and `--personal` (list of personal terms; if the file
does not exist, COM-14 comes out SKIP and says so).

Output: JSON with sorted keys, no timestamps or absolute paths. `tool_sha` is the sha256 of the script
itself and `config_sha` that of the config: same text, same script, same config, same output.
Exit 1 if the verdict is FAIL. A WARN does not block: it is noted.

Usage:
    lib/output_lint.py reply.md [--type status] [--lang es] [--audience public] [--allow COM-03]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROPOSED = {
    "COM-07": "plain words; technical term defined once",
    "COM-13": "one explicit analogy at a time, familiar base",
    "COM-16": "list only for discrete items or steps",
    "COM-17": "dependent things, kept together",
}
TYPES = ["pregunta", "estado", "decision", "fallo", "investigacion", "aclaracion"]

_BULLET = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
_UNORDERED = re.compile(r"^[-*+]\s+")
_HEADING = re.compile(r"^(#{1,6})\s")
_BOLD = re.compile(r"\*\*[^*\n]+\*\*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-záéíóúñüàèòçäöß]+", re.IGNORECASE)
_TAG = re.compile(r"\[([A-ZÁÉÍÓÚ][a-záéíóúñ]+)(?:[ :][^\]]*)?\]")
_QUOTED = re.compile(r"\"[^\"\n]*\"|`[^`\n]*`")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _strip_markup(line: str) -> str:
    text = _BULLET.sub("", line)
    text = _HEADING.sub("", text)
    text = text.replace("**", "").replace("`", "")
    return text.strip().lstrip("¡¿\"'«*_ ").strip()


def _starts_with_any(text: str, markers: list[str]) -> str | None:
    low = text.lower()
    for marker in markers:
        if low.startswith(marker):
            return marker
    return None


def _contains_any(text: str, markers: list[str]) -> str | None:
    low = text.lower()
    for marker in markers:
        if marker in low:
            return marker
    return None


def _evidence(number: int, line: str) -> dict:
    text = line.strip()
    if len(text) > 120:
        text = text[:117] + "..."
    return {"line": number, "text": text}


def _rule(rule_id: str, status: str, detector: str, evidence: list[dict], note: str = "") -> dict:
    entry = {"detector": detector, "evidence": evidence, "id": rule_id, "status": status}
    if note:
        entry["note"] = note
    return entry


def split_layers(lines: list[str], technical_headings: list[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str]], bool, bool]:
    """Returns (human layer, technical layer, has_heading, unclosed_fence). Lines numbered from 1.

    Lines inside ``` code blocks fall outside both layers: they are not linted. A fence that does not
    close before the end is flagged: what comes after it was not checked.
    """
    human: list[tuple[int, str]] = []
    technical: list[tuple[int, str]] = []
    in_technical = False
    in_code = False
    found = False
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not in_technical and line.strip().lower() in technical_headings:
            in_technical = True
            found = True
            continue
        (technical if in_technical else human).append((number, line))
    return human, technical, found, in_code


def _valid_tag(line: str, allowed: set) -> bool:
    return any(m.group(1) in allowed for m in _TAG.finditer(line))


def _unknown_tags(line: str, allowed: set) -> list[str]:
    """Tags outside the vocabulary, only where an epistemic tag would go: at the start of the line
    (after the bullet) or at the end (before punctuation). `[Docker]` mid-sentence or `[text](url)` do not count."""
    stripped = _strip_markup(line)
    found = []
    for m in _TAG.finditer(stripped):
        after = stripped[m.end():]
        at_start = m.start() == 0
        at_end = after.strip(" .;:,)") == ""
        if (at_start or at_end) and not after.startswith("(") and m.group(1) not in allowed:
            found.append(m.group(1))
    return found


def _units(layer: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Claim units of the technical layer: each bullet and each table row is one; consecutive prose
    is a single unit (numbered by its first line)."""
    units: list[tuple[int, str]] = []
    buffer: list[tuple[int, str]] = []
    for n, l in layer:
        if not l.strip() or _HEADING.match(l) or _TABLE_SEP.match(l):
            if buffer:
                units.append((buffer[0][0], " ".join(x for _, x in buffer)))
                buffer = []
            continue
        if _BULLET.match(l) or l.lstrip().startswith("|"):
            if buffer:
                units.append((buffer[0][0], " ".join(x for _, x in buffer)))
                buffer = []
            units.append((n, l))
        else:
            buffer.append((n, l))
    if buffer:
        units.append((buffer[0][0], " ".join(x for _, x in buffer)))
    return units


def _marker_rule(rule_id: str, kind: str | None, required_types: list[str], markers: list[str], layer: list[tuple[int, str]], empty_values: list[str]) -> dict:
    if kind is None:
        return _rule(rule_id, "SKIP", "script", [], "no --type")
    if kind not in required_types:
        return _rule(rule_id, "SKIP", "script", [], f"not required for {kind}")
    found = [(n, l, m) for n, l in layer for m in [_starts_with_any(_strip_markup(l), markers)] if m]
    if not found:
        return _rule(rule_id, "FAIL", "script", [], "marker missing in the human layer")
    n, l, m = found[0]
    content = _strip_markup(l)[len(m):].strip(" .").lower()
    if content in empty_values:
        return _rule(rule_id, "WARN", "script", [_evidence(n, l)], "empty marker: the marker is a string, not a commitment")
    return _rule(rule_id, "PASS", "script", [_evidence(n, l)])


def check(text: str, config: dict, kind: str | None = None, lang: str | None = None, audience: str | None = None,
          personal_terms: list[str] | None = None, allow: list[str] | None = None) -> dict:
    th = config["thresholds"]
    lines = text.splitlines()
    human, technical, has_technical, open_fence = split_layers(lines, config["technical_headings"])
    all_layers = human + technical
    allowed = {tag.strip("[]") for tag in config["epistemic_tags"]}
    markers = config["not_tested_markers"] + config["next_step_markers"]
    irreversible = config["irreversible_terms"]
    rules: list[dict] = []

    # COM-01 answer first
    first = next(((n, l) for n, l in human if l.strip() and not _HEADING.match(l)), None)
    if first is None:
        rules.append(_rule("COM-01", "FAIL", "script", [], "no text in the human layer"))
    else:
        hit = _starts_with_any(_strip_markup(first[1]), config["preambles"])
        rules.append(_rule("COM-01", "FAIL" if hit else "PASS", "script", [_evidence(*first)] if hit else [], f"preamble: {hit}" if hit else ""))

    # COM-02 two layers
    non_empty = sum(1 for _, l in all_layers if l.strip())
    if non_empty > th["two_layers_min_lines"] and not has_technical:
        rules.append(_rule("COM-02", "FAIL", "script", [], f"{non_empty} lines with no technical-layer heading"))
    elif has_technical and not any(l.strip() for _, l in technical):
        rules.append(_rule("COM-02", "WARN", "script", [], "empty technical layer"))
    else:
        rules.append(_rule("COM-02", "PASS", "script", []))

    # COM-03 five bullets maximum (numbered lists are steps and do not count)
    top_bullets = [(n, l) for n, l in human if _UNORDERED.match(l)]
    if len(top_bullets) > th["max_top_level_bullets"]:
        rules.append(_rule("COM-03", "FAIL", "script", [_evidence(n, l) for n, l in top_bullets[th["max_top_level_bullets"]:]], f"{len(top_bullets)} top-level bullets"))
    else:
        rules.append(_rule("COM-03", "PASS", "script", []))

    # COM-04 next step, in the human layer
    rules.append(_marker_rule("COM-04", kind, config["types_requiring_next_step"], config["next_step_markers"], human, config["empty_marker_values"]))

    # COM-05 short sentences (human layer, no headings or tables)
    warns: list[dict] = []
    fails: list[dict] = []
    for n, l in human:
        if not l.strip() or _HEADING.match(l) or l.lstrip().startswith("|"):
            continue
        for sentence in _SENTENCE_END.split(_strip_markup(l)):
            words = len(sentence.split())
            if words > th["sentence_fail_words"]:
                fails.append(_evidence(n, sentence))
            elif words > th["sentence_warn_words"]:
                warns.append(_evidence(n, sentence))
    rules.append(_rule("COM-05", "FAIL" if fails else ("WARN" if warns else "PASS"), "script", fails + warns))

    # COM-06 no filler; if the sentence warns about something irreversible, it warns instead of failing (it gets rewritten, not deleted)
    hits = [(n, l, m) for n, l in all_layers for m in [_contains_any(l, config["fillers"])] if m]
    guarded = [(n, l, m) for n, l, m in hits if _contains_any(l, irreversible)]
    plain = [(n, l, m) for n, l, m in hits if not _contains_any(l, irreversible)]
    status = "FAIL" if plain else ("WARN" if guarded else "PASS")
    note = ", ".join(sorted({m for _, _, m in hits}))
    if guarded:
        note += " | the filler accompanies an irreversible warning: rewrite the sentence, keep the warning"
    rules.append(_rule("COM-06", status, "script", [_evidence(n, l) for n, l, _ in plain + guarded], note))

    # COM-08 human's language (human layer, outside quotes and code)
    if lang in config["stopwords"]:
        body = " ".join(_QUOTED.sub(" ", l) for _, l in human)
        words = [w.lower() for w in _WORD.findall(body)]
        counts = {code: sum(1 for w in words if w in set(config["stopwords"][code])) for code in sorted(config["stopwords"])}
        rival = max((c for c in counts if c != lang), key=lambda c: counts[c])
        mismatch = counts[rival] > counts[lang] and counts[rival] >= th["lang_min_hits"]
        rules.append(_rule("COM-08", "FAIL" if mismatch else "PASS", "script", [], "stopwords " + " ".join(f"{c}={counts[c]}" for c in counts)))
    else:
        rules.append(_rule("COM-08", "SKIP", "script", [], "no --lang, or a language with no stopword list"))

    # COM-09 epistemic tag per unit of the technical layer
    if not has_technical:
        rules.append(_rule("COM-09", "SKIP", "script", [], "no technical layer"))
    else:
        units = _units(technical)
        untagged = [(n, u) for n, u in units if not _valid_tag(u, allowed) and not _starts_with_any(_strip_markup(u), markers) and not _strip_markup(u).startswith("|")]
        header_rows = [(n, u) for n, u in units if _strip_markup(u).startswith("|")][:1]
        untagged += [(n, u) for n, u in units if _strip_markup(u).startswith("|") and (n, u) not in header_rows and not _valid_tag(u, allowed)]
        unknown = [(n, u, t) for n, u in units for t in _unknown_tags(u, allowed)]
        note = ""
        if unknown:
            note = "tag outside the vocabulary: " + ", ".join(sorted({t for _, _, t in unknown}))
        status = "FAIL" if untagged or unknown else "PASS"
        rules.append(_rule("COM-09", status, "script", [_evidence(n, u) for n, u in untagged] + [_evidence(n, u) for n, u, _ in unknown], note))

    # COM-10 what was not tested, in the human layer
    rules.append(_marker_rule("COM-10", kind, config["types_requiring_not_tested"], config["not_tested_markers"], human, config["empty_marker_values"]))

    # COM-11 no closing that repeats
    closers = [(n, l) for n, l in all_layers if _starts_with_any(_strip_markup(l), config["closing_repeats"])]
    rules.append(_rule("COM-11", "FAIL" if closers else "PASS", "script", [_evidence(n, l) for n, l in closers]))

    # COM-12 analogy with a mapping and a limit (heuristic, warns)
    missing: list[dict] = []
    for i, (n, l) in enumerate(all_layers):
        if not _contains_any(l, config["analogy_markers"]):
            continue
        window = all_layers[i : i + th["analogy_window_lines"] + 1]
        if not any(_contains_any(wl, config["analogy_limit_markers"]) for _, wl in window):
            missing.append(_evidence(n, l))
    rules.append(_rule("COM-12", "WARN" if missing else "PASS", "script", missing, "analogy with no declared limit" if missing else ""))

    # COM-14 personal language only for the declared interlocutor
    if audience != "public":
        rules.append(_rule("COM-14", "SKIP", "script", [], "non-public audience"))
    elif not personal_terms:
        rules.append(_rule("COM-14", "SKIP", "script", [], "no list of personal terms (--personal): not checked"))
    else:
        pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in personal_terms) + r")(?![\w])", re.IGNORECASE)
        leaks = [(n, l) for n, l in all_layers if pattern.search(l)]
        rules.append(_rule("COM-14", "FAIL" if leaks else "PASS", "script", [_evidence(n, l) for n, l in leaks]))

    # COM-15 minimum format
    format_fails: list[dict] = []
    format_warns: list[dict] = []
    for n, l in all_layers:
        heading = _HEADING.match(l)
        if heading and len(heading.group(1)) in (1, 4, 5, 6):
            format_fails.append(_evidence(n, l))
        if "—" in l:
            format_fails.append(_evidence(n, l))
        elif "–" in l:
            format_warns.append(_evidence(n, l))
    note = ""
    if open_fence:
        format_fails.append({"line": 0, "text": "unclosed ``` fence: what comes after it was not checked"})
        note = "unclosed fence"
    bold_total = sum(len(_BOLD.findall(l)) for _, l in human)
    human_lines = max(1, sum(1 for _, l in human if l.strip()))
    bold_cap = th["max_bold_per_10_lines"] * ((human_lines + 9) // 10)
    if bold_total > bold_cap:
        format_warns.append({"line": 0, "text": f"{bold_total} bold spans in {human_lines} lines (cap {bold_cap})"})
        note = (note + "; " if note else "") + "bold spans over the cap"
    rules.append(_rule("COM-15", "FAIL" if format_fails else ("WARN" if format_warns else "PASS"), "script", format_fails + format_warns, note))

    # COM-18 irreversible things surface in the human layer
    if not has_technical:
        rules.append(_rule("COM-18", "SKIP", "script", [], "no technical layer"))
    else:
        human_text = " ".join(l for _, l in human).lower()
        hidden = [(n, l, m) for n, l in technical for m in [_contains_any(l, irreversible)] if m and m not in human_text]
        rules.append(_rule("COM-18", "FAIL" if hidden else "PASS", "script", [_evidence(n, l) for n, l, _ in hidden], ("only in the technical layer: " + ", ".join(sorted({m for _, _, m in hidden}))) if hidden else ""))

    for rule_id in sorted(PROPOSED):
        rules.append(_rule(rule_id, "SKIP", "reviewer", [], PROPOSED[rule_id]))

    for rule in rules:
        if allow and rule["id"] in allow and rule["status"] == "FAIL":
            rule["status"] = "WARN"
            rule["note"] = (rule.get("note", "") + " | " if rule.get("note") else "") + "FAIL downgraded to WARN by the owner's --allow"

    rules.sort(key=lambda r: r["id"])
    statuses = [r["status"] for r in rules]
    summary = {s: statuses.count(s) for s in ("PASS", "WARN", "FAIL", "SKIP")}
    return {
        "allow": sorted(allow or []),
        "audience": audience or "",
        "lang": lang or "",
        "layers": {
            "human_lines": sum(1 for _, l in human if l.strip()),
            "technical_lines": sum(1 for _, l in technical if l.strip()),
            "technical_heading": has_technical,
            "code_fence_lines": sum(1 for l in lines if l.strip().startswith("```")),
        },
        "rules": rules,
        "summary": summary,
        "type": kind or "",
        "verdict": "FAIL" if summary["FAIL"] else "PASS",
    }


def load_personal(path: Path) -> list[str]:
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("personal_terms", []))


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent / "config"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="markdown file with the reply, or - for stdin")
    parser.add_argument("--type", dest="kind", choices=TYPES)
    parser.add_argument("--lang")
    parser.add_argument("--audience", choices=["public", "owner"])
    parser.add_argument("--allow", action="append", default=[], metavar="COM-xx", help="downgrades that FAIL to WARN; stays recorded in the output")
    parser.add_argument("--config", default=str(here / "output-lint.json"))
    parser.add_argument("--personal", default=str(here / "output-lint.personal.json"), help="list of personal terms for COM-14; if missing, COM-14 comes out SKIP")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = check(text, config, args.kind, args.lang, args.audience, load_personal(Path(args.personal)), args.allow)
    result["config_sha"] = _sha(config_path)
    result["tool_sha"] = _sha(Path(__file__).resolve())
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    if result["verdict"] == "FAIL":
        for rule in result["rules"]:
            if rule["status"] == "FAIL":
                print(f"FAIL {rule['id']}: {rule.get('note') or (rule['evidence'][0]['text'] if rule['evidence'] else '')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
