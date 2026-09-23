#!/usr/bin/env python3
"""Validates a change card in Markdown against schemas/change-card.schema.json.

Expected format per field: `**<Label>**: <value>[ [Tag]]` (see
config/change-card.template.md). 9 fields with an English label; 7 of
them must end in an epistemic tag in brackets
([Medido]/[Probado]/[Inferido]/[Asumido]/[Desconocido]): Invariant and
Ticket are exempt from the tag but have their own shape validation.

The Invariant token is `<invariant_prefix>-NN` (INV by default, see
config/project.json:invariant_prefix) plus any id listed in
config/project.json:extra_invariant_tokens (ARCH-006 by default): both
configurable because each project numbers its own domain invariants
differently.

Usage:
    lib/change_card_validator.py [--config <project.json>] [--extract] <file|->

Output: JSON on stdout with {verdict, routing, fields_found, fields_missing,
errors, epistemic_coverage}. `routing` is "opus" if "For what" or "What it
risks" fall under the project's critical properties (by default: everything
except Auditability and UX), otherwise "sonnet": so the orchestrator skill
reads the adversary's lane from the card itself instead of trusting prose.
Exit code 1 on FAIL, except with --extract (best-effort, never fails: it
reads a commit body without blocking anything).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline  # noqa: E402

DEFAULT_PROJECT_CONFIG = TOOLS_ROOT / "config" / "project.json"
DEFAULT_INVARIANT_PREFIX = "INV"
DEFAULT_EXTRA_INVARIANT_TOKENS: tuple[str, ...] = ("ARCH-006",)

REQUIRED_FIELDS = (
    "Why", "For what", "What it risks", "When", "How",
    "How far", "How we'll know", "Invariant", "Ticket",
)
TAG_EXEMPT_FIELDS = frozenset({"Invariant", "Ticket"})
VALID_TAGS = frozenset({"Medido", "Probado", "Inferido", "Asumido", "Desconocido"})
# Domain-neutral defaults: a project with no config/project.json:property_order
# of its own gets this generic hierarchy instead. A payments-style project
# (or any other domain) declares its own in config/project.json.
FOR_WHAT_VALUES = frozenset({
    "Data integrity", "State correctness", "Identity/uniqueness", "Auditability",
    "Recoverability", "Security", "Performance", "UX",
})
# Adversarial round: Invariant no longer looks only at "For what". If EITHER
# of the two risk fields falls in this set, a real invariant is required
# (neither can be covered up by a 'none' from the other).
CRITICAL_ROUTING_SET = frozenset({
    "Data integrity", "State correctness", "Identity/uniqueness",
    "Recoverability", "Security", "Performance",
})
DEFAULT_FOR_WHAT_VALUES = FOR_WHAT_VALUES
DEFAULT_CRITICAL_ROUTING_SET = CRITICAL_ROUTING_SET
# 'n/a' in Invariant is only accepted when BOTH fields explicitly declare
# there is nothing to protect. 'none' is the literal value "What it risks"
# uses for that (it has no closed vocabulary like "For what", so any free
# text does NOT count as "no risk": it has to say it with that word).
INVARIANT_NA_ALLOWED_SET = frozenset({"Auditability", "UX", "none"})

TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
TAG_SUFFIX_RE = re.compile(r"^(?P<text>.*?)\s*\[(?P<tag>[^\]]*)\]\s*$")

_LABEL_ALTERNATION = "|".join(re.escape(label) for label in REQUIRED_FIELDS)
# The [\-\*\s]* prefix already handles bullets ("- **Field**: ..." or
# "* **Field**: ...") thanks to the regex's normal backtracking: no
# separate branch is needed.
FIELD_LINE_RE = re.compile(r"^[\-\*\s]*\*\*(?P<label>" + _LABEL_ALTERNATION + r")\*\*\s*:\s*(?P<value>.*)$")
_FIELD_START_TOKEN_RE = re.compile(r"\*\*(?:" + _LABEL_ALTERNATION + r")\*\*\s*:")

CHANGE_CARD_HEADING_RE = re.compile(r"^#+.*change card.*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^#+\s")


def load_project_config(path: Path | None) -> dict:
    config_path = path or DEFAULT_PROJECT_CONFIG
    if not config_path.exists():
        return {}
    return baseline.load_json(config_path)



def properties_from_config(config: dict) -> tuple[frozenset[str], frozenset[str]]:
    """Allowed 'For what' values and the critical (routing) set, from
    config/project.json:property_order and critical_properties; the built-in
    domain-neutral defaults apply when the project declares nothing."""
    order = config.get("property_order")
    if not order:
        return DEFAULT_FOR_WHAT_VALUES, DEFAULT_CRITICAL_ROUTING_SET
    critical = config.get("critical_properties") or [p for p in order if p not in ("Auditability", "UX")]
    return frozenset(order), frozenset(critical)


def configure_properties(config: dict) -> None:
    """Rebinds the module-level property sets from the project config so the
    field checks and the routing use the project's own hierarchy."""
    global FOR_WHAT_VALUES, CRITICAL_ROUTING_SET, RECOGNIZED_LEADING_TOKENS
    FOR_WHAT_VALUES, CRITICAL_ROUTING_SET = properties_from_config(config)
    RECOGNIZED_LEADING_TOKENS = FOR_WHAT_VALUES | {"none"}


def invariant_prefix_from_config(config: dict) -> str:
    return config.get("invariant_prefix") or DEFAULT_INVARIANT_PREFIX


def extra_invariant_tokens_from_config(config: dict) -> tuple[str, ...]:
    tokens = config.get("extra_invariant_tokens")
    if tokens is None:
        return DEFAULT_EXTRA_INVARIANT_TOKENS
    return tuple(tokens)


def _extract_card_section(text: str) -> str:
    """A change card is almost never the whole document: it lives under a
    heading like '## Change Card' inside a larger doc. Trims from
    there to the next heading (or EOF) so continuation-line joining does
    not swallow the rest of the document. If there is no heading with
    'change card', `text` is assumed to ALREADY be the whole card
    (backward compatibility: standalone cards in a commit body)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if CHANGE_CARD_HEADING_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return text
    end = len(lines)
    for j in range(start, len(lines)):
        if HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _split_multi_field_line(line: str) -> list[str]:
    """'**Invariant**: n/a. **Ticket**: no ticket.' are two fields on one
    line (seen in real hand-written cards): split into two sub-lines, one
    per '**Field**:' that appears."""
    starts = [m.start() for m in _FIELD_START_TOKEN_RE.finditer(line)]
    if len(starts) <= 1:
        return [line]
    return [line[starts[i]:starts[i + 1] if i + 1 < len(starts) else len(line)] for i in range(len(starts))]


def _strip_trailing_sentence_punct(value: str) -> str:
    """A trailing '.' or ')' (typical of splitting 'n/a. **Ticket**...'
    in two, or of a sentence that follows after the tag) is not part of
    the value."""
    value = value.rstrip()
    if value.endswith((".", ")")):
        value = value[:-1].rstrip()
    return value


def parse_fields(text: str) -> tuple[dict, list[str]]:
    """Extracts {label: raw_value}. Joins continuation lines (a non-empty
    line that does not open a new field gets appended, with a space, to
    the field still open) and splits several fields sharing one line.
    Also returns errors for a duplicate label (keeps the first
    occurrence, like a form that does not allow repeating a field)."""
    text = _extract_card_section(text)
    fields: dict[str, str] = {}
    errors: list[str] = []
    current_label: str | None = None

    exploded_lines: list[str] = []
    for line in text.splitlines():
        exploded_lines.extend(_split_multi_field_line(line))

    for line in exploded_lines:
        match = FIELD_LINE_RE.match(line)
        if match:
            label = match.group("label")
            value = _strip_trailing_sentence_punct(match.group("value").strip())
            if label in fields:
                errors.append(f"duplicate field: {label}")
                current_label = None
                continue
            fields[label] = value
            current_label = label
            continue

        stripped = line.strip()
        if not stripped or current_label is None:
            continue  # blank line, or prose before/outside any field: no-op
        fields[current_label] = _strip_trailing_sentence_punct(f"{fields[current_label]} {stripped}".strip())

    return fields, errors


RECOGNIZED_LEADING_TOKENS = FOR_WHAT_VALUES | {"none"}
_LEADING_PROPERTY_SEPARATORS = ",;:("


def _split_leading_property(text: str, candidates: frozenset) -> tuple[str | None, str | None]:
    """If `text` is exactly one of `candidates`, returns it as-is (with
    no note). If it STARTS with one of `candidates` followed (after an
    optional space) by one of ',', ';', ':' or '(', splits the
    recognized property from the free explanation that follows: "UX,
    more ceremony per change" is UX with a note, but "UX from the team,
    more ceremony" does NOT count (there is a word in between, not
    punctuation): that is left unrecognized on purpose, and (None, None)
    tells the caller to treat all of `text` as whatever it needs to
    treat it as."""
    if text in candidates:
        return text, None
    for token in sorted(candidates, key=len, reverse=True):
        match = re.match(re.escape(token) + r"\s*([" + re.escape(_LEADING_PROPERTY_SEPARATORS) + r"])(.*)$", text)
        if match:
            return token, match.group(2).strip()
    return None, None


def _validate_tagged_field(label: str, raw_value: str) -> list[str]:
    """For one of the 7 fields with a mandatory tag: splits text and tag,
    validates the tag and (only for 'For what') the value itself.
    `raw_value` arrives from parse_fields() already without trailing
    sentence punctuation."""
    errors = []
    match = TAG_SUFFIX_RE.match(raw_value)
    if not match:
        errors.append(f"{label}: missing the epistemic tag at the end (e.g. [Medido])")
        return errors

    text, tag = match.group("text").strip(), match.group("tag").strip()
    if tag not in VALID_TAGS:
        errors.append(f"{label}: invalid epistemic tag '[{tag}]'")
    if not text:
        errors.append(f"{label}: the field is empty")

    if label == "For what":
        leading, _note = _split_leading_property(text, FOR_WHAT_VALUES)
        if leading is None:
            errors.append(f"For what: value '{text}' is not in the allowed list")
    return errors


def _field_text(raw_value: str) -> str:
    """A field's text without its epistemic tag, best-effort: if the tag
    is missing or malformed (broken card) returns the raw value instead
    of crashing, because routing/Invariant must still be evaluable."""
    match = TAG_SUFFIX_RE.match(raw_value)
    return match.group("text").strip() if match else raw_value.strip()


def _routing_category(field_text: str) -> str:
    """Reduces the already-untagged text to the recognized property if
    the field carries 'property<separator>note' (e.g. "What it risks"="none;
    it's a document"); if it does not match that pattern, returns the
    full text, which simply won't be a member of any category set."""
    leading, _note = _split_leading_property(field_text, RECOGNIZED_LEADING_TOKENS)
    return leading if leading is not None else field_text


def _is_valid_invariant_token(token: str, invariant_prefix: str, extra_tokens: tuple[str, ...]) -> bool:
    token_re = re.compile(r"^" + re.escape(invariant_prefix) + r"-\d{2}$")
    return bool(token_re.match(token)) or token in extra_tokens


def _validate_invariant(
    raw_value: str, for_what_text: str, what_it_risks_text: str,
    invariant_prefix: str, extra_tokens: tuple[str, ...],
) -> list[str]:
    errors = []
    value = raw_value.strip()
    if value.lower() == "n/a":
        both_safe = (
            for_what_text in INVARIANT_NA_ALLOWED_SET
            and what_it_risks_text in INVARIANT_NA_ALLOWED_SET
        )
        if not both_safe:
            errors.append(
                "Invariant: 'n/a' is only accepted when both For what AND What it risks "
                "are Auditability, UX, or 'none'"
            )
        return errors

    tokens = [t.strip() for t in value.split(",") if t.strip()]
    if not tokens or not all(_is_valid_invariant_token(t, invariant_prefix, extra_tokens) for t in tokens):
        extra_desc = " or ".join(extra_tokens) if extra_tokens else "none configured"
        errors.append(
            f"Invariant: invalid format '{value}' "
            f"(expected 'n/a', {invariant_prefix}-NN[,{invariant_prefix}-NN...] or {extra_desc})"
        )
    return errors


def _validate_ticket(raw_value: str) -> list[str]:
    value = raw_value.strip()
    if value.lower() == "no ticket":
        return []
    if TICKET_RE.match(value):
        return []
    return [f"Ticket: '{value}' is neither a valid Jira key (e.g. DEV-123) nor 'no ticket'"]


def validate(text: str, invariant_prefix: str | None = None, extra_invariant_tokens: tuple[str, ...] | None = None) -> dict:
    if invariant_prefix is None:
        invariant_prefix = DEFAULT_INVARIANT_PREFIX
    if extra_invariant_tokens is None:
        extra_invariant_tokens = DEFAULT_EXTRA_INVARIANT_TOKENS

    fields, errors = parse_fields(text)
    fields_found = sorted(fields)
    fields_missing = sorted(set(REQUIRED_FIELDS) - set(fields))

    tagged_ok = 0
    tag_required_fields = [f for f in REQUIRED_FIELDS if f not in TAG_EXEMPT_FIELDS]

    # First pass: validates tag + closed vocabulary for each tagged field.
    per_field_errors: list[str] = []
    for label in tag_required_fields:
        if label not in fields:
            continue
        field_errors = _validate_tagged_field(label, fields[label])
        if not field_errors:
            tagged_ok += 1
        per_field_errors.extend(field_errors)

    # routing/Invariant look at the raw text of the two risk fields,
    # best-effort (even if the epistemic tag is missing or misplaced): a
    # broken card must still be able to say "this is critical, route to the
    # adversary". _routing_category reduces "property, free note" to the
    # property alone.
    for_what_text = _routing_category(_field_text(fields.get("For what", "")))
    what_it_risks_text = _routing_category(_field_text(fields.get("What it risks", "")))
    routing = "opus" if (for_what_text in CRITICAL_ROUTING_SET or what_it_risks_text in CRITICAL_ROUTING_SET) else "sonnet"

    if "Invariant" in fields:
        per_field_errors.extend(_validate_invariant(
            fields["Invariant"], for_what_text, what_it_risks_text, invariant_prefix, extra_invariant_tokens
        ))
    if "Ticket" in fields:
        per_field_errors.extend(_validate_ticket(fields["Ticket"]))

    all_errors = errors + per_field_errors
    verdict = "PASS" if not fields_missing and not all_errors else "FAIL"

    return {
        "verdict": verdict,
        "routing": routing,
        "fields_found": fields_found,
        "fields_missing": fields_missing,
        "errors": sorted(all_errors),
        "epistemic_coverage": {
            "tag_required_fields": len(tag_required_fields),
            "tagged_ok": tagged_ok,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="config/project.json (invariant_prefix, extra_invariant_tokens)")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("source", help="path to the file, or '-' for stdin")
    args = parser.parse_args(argv)

    project_config = load_project_config(Path(args.config) if args.config else None)
    configure_properties(project_config)
    invariant_prefix = invariant_prefix_from_config(project_config)
    extra_invariant_tokens = extra_invariant_tokens_from_config(project_config)

    text = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    result = validate(text, invariant_prefix, extra_invariant_tokens)
    if args.extract:
        result["extract_mode"] = True

    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))

    if args.extract:
        return 0
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
