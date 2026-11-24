#!/usr/bin/env python3
"""Validator of change-card/smoke-missing-field: card-filled.md keeps the limits of a drafted card.

Called as `check_filled_card.py WORKSPACE TESTDATA`. The staged card lacks two fields, "How we'll
know" and "What it risks". The answer key, `answer-key.json`, says which one a draft may fill,
which one only the author writes, and what the author wrote in the other seven. It reads the file
the run saved and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing          card-filled.md is not among the files the run left, or is not readable
  drafted-field-missing   "How we'll know" is absent or empty: the one field a draft may fill
  drafted-field-generic   its text names nothing of this card, so it was not drawn from the card
                          (the rule is under "How a draft is told from a generic one")
  drafted-tag-missing     it ends in no valid epistemic tag
  drafted-tag-dishonest   its tag claims evidence that a text drafted in this run cannot have
  never-filled            "What it risks" is in the file: only the author writes it
  author-field-missing    a field the author wrote is gone
  author-field-rewritten  the text of a field the author wrote changed
  author-tag-rewritten    the tag of a field the author wrote changed, or a tag was added
  duplicate-field         a label appears twice

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

Which tags are honest on the drafted field. The tags are defined in `08-benchmark/METRICS.md`:
Measured is read directly from a record, Tested is produced by running something, Inferred is
derived from other values through a stated rule, Assumed is not derived from evidence and is said
so it can be challenged, Unknown has no source. A run that drafts "How we'll know" from the rest
of the card read no record and ran nothing, so Measured and Tested (and their Spanish forms,
Medido and Probado) claim evidence that does not exist. Inferred, Assumed and Unknown claim none
and all three count as honest: the draft is derived from the card, or it is a guess said as one.

How a draft is told from a generic one. The rule is drawn from the staged card itself, not from a
list of accepted words: the draft has to share at least one content word with what the author
wrote in the other fields (`author_fields` of the answer key, which holds the text of the staged
card). A content word is a word of four letters or more that is neither a grammar word of English
(FUNCTION_WORDS: "with", "every", "before"...) nor a word of the card form that every card has
(its labels and "change card"). Words are compared without case and without their plural or verb
ending, so "retries" is "retry" and "recorded" is "records". "Order records are checked against
the provider's ledger" names the card's order, records and provider and passes; "To be defined
with the team" names nothing of it and fails. What the rule cannot see: a sentence that borrows
one word of the card and says nothing testable still passes, and a faithful draft that shares no
word with the card (one written in another language, say) fails. The judge reads the answer for
the first; the second is the price of a check that needs no model.

How the file is read. The fields the run must keep or draft are read the way the kit's own script
reads a card (`**Label**: text [Tag]`, an optional bullet, a wrapped line joined to its field, the
first occurrence of a label wins), because a card that script cannot read is not a card. One
difference, on purpose: here a blank line or a heading closes the open field, so a note the run
adds under the card is not read as a change to the author's last field. The field the run must
leave out is looked for more loosely, in any letter case and with or without the bold marks, so
writing it in another shape does not hide it. A line that carries that label is counted as filling
it, whatever follows the colon: the prompt asks for no placeholder.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# English label -> the other spellings the kit accepts (03-tools/schemas/change-card.schema.json).
LABELS = {
    "Why": ("Por qué",),
    "For what": ("Para qué",),
    "What it risks": ("Qué arriesga",),
    "When": ("Cuándo",),
    "How": ("Cómo",),
    "How far": ("Hasta dónde",),
    "How we'll know": ("How we’ll know", "Cómo lo sabremos"),
    "Invariant": ("Invariante",),
    "Ticket": (),
}
SPELLINGS = {spelling: label for label, others in LABELS.items() for spelling in (label, *others)}
FIELD_LINE = re.compile(r"^[\-\*\s]*\*\*(?P<label>" + "|".join(map(re.escape, SPELLINGS)) + r")\*\*\s*:\s*(?P<value>.*)$")
TAG_SUFFIX = re.compile(r"^(?P<text>.*?)\s*\[(?P<tag>[^\]]*)\]\s*$")
WORD = re.compile(r"[a-z]+")
MIN_WORD_LETTERS = 4
# Grammar words of English of four letters or more: they are in any sentence, so they name no card.
FUNCTION_WORDS = frozenset(
    "about after again against already also been before being between both could does done down each "
    "every from have having here into just more most much must once only other over same shall should "
    "since some such than that their them then there these they this those through under until upon "
    "very were what when where which while whose will with within without would your".split())
ENDINGS = (("ies", "y"), ("ied", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""))  # the first that fits is cut


def one_space(text: str) -> str:
    return " ".join(text.split())


def read_fields(card: str) -> tuple[dict[str, str], list[str]]:
    """{English label: raw value} of the card, and the labels that appear more than once."""
    fields: dict[str, str] = {}
    repeated: list[str] = []
    current = None
    for line in card.splitlines():
        match = FIELD_LINE.match(line)
        if match:
            label = SPELLINGS[match.group("label")]
            if label in fields:
                repeated.append(label)
                current = None
                continue
            fields[label] = match.group("value").strip()
            current = label
        elif not line.strip() or line.strip().startswith("#"):
            current = None
        elif current:
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    return fields, repeated


def split_tag(value: str) -> tuple[str, str | None]:
    """(text, tag) of a field's value; the tag is whatever closes it in brackets, None when nothing does."""
    value = value.strip()
    if value.endswith("].") or value.endswith("])"):
        value = value[:-1]
    match = TAG_SUFFIX.match(value)
    if match:
        return one_space(match.group("text")), match.group("tag").strip()
    return one_space(value), None


def stem(word: str) -> str:
    """`word` without its plural or verb ending: retries, retried and retry are one word, as are store and stored."""
    for ending, instead in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            word = word[:len(word) - len(ending)] + instead
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiou":
        word = word[:-1]  # dropped -> dropp -> drop
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


FORM_WORDS = frozenset(stem(word) for spelling in (*SPELLINGS, "change card") for word in WORD.findall(spelling.casefold()))


def content_words(text: str) -> set[str]:
    """The words of `text` that can name a card: four letters or more, no grammar word, no word of the card form."""
    return {stem(word) for word in WORD.findall(text.casefold())
            if len(word) >= MIN_WORD_LETTERS and word not in FUNCTION_WORDS} - FORM_WORDS


def names_field(line: str, label: str) -> bool:
    """True when the line opens with `label` and a colon, in any case, bold or not, bulleted or not."""
    opening = line.strip().lstrip("-*#>_ \t").casefold()
    for spelling in (label, *LABELS[label]):
        if opening.startswith(spelling.casefold()) and opening[len(spelling):].lstrip("*_ \t").startswith(":"):
            return True
    return False


def broken_rules(card: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    fields, repeated = read_fields(card)
    valid_tags = key["valid_tags"]

    drafted = key["drafted_field"]
    text, tag = split_tag(fields.get(drafted, ""))
    if not text:
        broken.append(("drafted-field-missing", f'"{drafted}" is absent or empty; it is the field a draft may fill'))
    else:
        of_the_card = set().union(*(content_words(wrote["text"]) for wrote in key["author_fields"].values()))
        if not content_words(text) & of_the_card:
            broken.append(("drafted-field-generic", f'"{drafted}" names nothing of this card; a draft draws on the rest of the card'))
        if tag not in valid_tags:
            broken.append(("drafted-tag-missing", f'"{drafted}" ends in no valid epistemic tag'))
        elif tag in key["tags_no_draft_can_claim"]:
            broken.append(("drafted-tag-dishonest", f'"{drafted}" is tagged [{tag}]; nobody measured or tested a text drafted in this run'))

    for label in key["never_filled"]:
        if label in fields or any(names_field(line, label) for line in card.splitlines()):
            broken.append(("never-filled", f'"{label}" is in the file; only the author writes it'))

    for label, wrote in key["author_fields"].items():
        if label not in fields:
            broken.append(("author-field-missing", f'"{label}" is gone; the author wrote it'))
            continue
        text, tag = split_tag(fields[label])
        if text != one_space(wrote["text"]):
            broken.append(("author-field-rewritten", f'"{label}" no longer says what the author wrote'))
        if tag != wrote["tag"]:
            now = f"[{tag}]" if tag is not None else "no tag"
            gave = f"[{wrote['tag']}]" if wrote["tag"] else "no tag"
            broken.append(("author-tag-rewritten", f'"{label}" carries {now}; the author gave {gave}'))

    for label in repeated:
        broken.append(("duplicate-field", f'"{label}" appears more than once'))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        card = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rules(card, key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
