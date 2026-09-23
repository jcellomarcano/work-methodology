# Contrasted research · what a code comment must look like in Kotlin and Android

Finding: four source families (Kotlin and Android official docs, plain language, tooling, literature)
agree on three things only: a comment carries what the code cannot, interface documentation is a
different object from a comment, and a block tag that repeats the signature is waste. They do not agree
on presence: Android requires KDoc on every public member (K11), the Kotlin conventions require none,
detekt ships presence rules but turns all of them off (T9), and iso-24495-code says a file with no
comments is fine (T21). And nobody official says anything at all about `TODO` or `FIXME` in Kotlin: the
three pages the owner cited never contain those strings (K15). That is why DOC-002 governs shape, not
presence, and why DOC-003 borrows its format from a Google sibling guide and from detekt's own defaults.

Simile: a passport photo has rules about framing, not about who may have a passport. DOC-002 is the
framing rule. Who gets a passport is DOC-001's question and stays DOC-001's question. Unlike the photo,
here the framing rules come from two authorities that disagree, so the round writes down which one wins
and why.

Full evidence, with literal quotes, in `sources/` (ids K, L, T, B). Measurement in section 5. Everything
below is a reading of those quotes [Inferred], except where a tag says otherwise.

## 1. Where the four families agree

| Rule that emerges | Kotlin and Android | Plain language | Tooling | Literature |
|---|---|---|---|---|
| A comment carries what the code cannot | | L21 | T17 | B5, B6, B7 |
| Interface documentation is not a comment and survives the delete rule | K7, K11 | | T18 | B8 |
| A block tag that repeats the signature is waste | K5 | L21 | | B4 |
| The summary sits first and is the only part some readers see | K2, K7 | L5, L12, L32, L43 | | |
| An empty or stale block tag is a defect | K10 | | T5 | |
| Symbols get markup, not prose | K1, K3 | | | |
| One term per concept | | L22 | T19 | |
| Sentence length is bounded, not scored | | L29, L35, L41, L47, L48 | T23 | |
| An action tag needs a tracked identifier | K16 (tracked reference), K17 (identifier present) | | T11, T12 | |
| Cleverness that needs a comment has already failed | | | T20 | B1 (Martin's own concession) |

K17 allows a name or an e-mail as that identifier; only K16 says to avoid an individual, so "not a
person" rests on K16 alone.

## 2. Where they differ, and what we decided

| Tension | Who says what | Decision | Why |
|---|---|---|---|
| KDoc presence | Android requires it on every public type and public or protected member (K11), with exceptions (K12, K13); Kotlin sets no presence rule (K5, K6); iso-24495-code says none is required (T21); detekt has the rules but off (T2, T3, T4) | DOC-002 says nothing about presence. DOC-001's clause "KDoc on contracts" stays the only presence rule | Android's own exception K12 is a necessity test ("nothing else worthwhile to say but Returns the foo"), so Android and DOC-001 differ in default, not in criterion. Turning on a presence count would make the gate ask for text that K12 itself calls not worthwhile |
| Effective Kotlin "document public functions" | The owner cited "item 31 Document all public functions with KDoc". The publisher's table of contents has Item 30 "Define contracts with documentation" and Item 31 "Respect abstraction contracts" (B11) | The claim is dropped. No rule in this round rests on it | Both the number and the title were wrong, and the item body is paid and unread. A rule cannot cite a source nobody in the round has read |
| `@param` and `@return` | Kotlin says avoid them and inline the description (K5); Android orders them and forbids empty ones (K10); *Clean Code*'s author dislikes ones obvious from the signature (B4) | Omit unless the prose cannot carry it; when present, never empty | K5 and B4 agree across families. K10 is conditional: it governs tags that are used, not whether to use them |
| Verb-first summary | The owner asked for "one-sentence imperative summary starting with an active verb". Android says the opposite: the fragment is "a noun phrase or verb phrase, not a complete sentence" and "does not ... have to form a complete imperative sentence" (K8). Plain language prefers a present-tense, non-hidden verb (L49, L50) and verb-first headings (L33) | Verb first is the house default and is not enforced. What is enforced is the fragment: no "This method returns", no "A `Foo` is a", no full sentence | K8 names those two openers literally, so banning them cites Android rather than contradicting it. Enforcing verb-first would flag 27 of the 43 KDocs in the baseline, all of them Android-compliant (section 5) |
| detekt presence rules versus DOC-001 | UndocumentedPublicClass, UndocumentedPublicFunction, UndocumentedPublicProperty exist and are off by default (T2, T3, T4) | Not adopted. The repo does not run detekt today; `kotlin.md` lists detekt as a P2 better detector | A presence rule is satisfied by "Returns the foo", which `comment_gate.py` already flags as `restates_code` (T26). Two enforced rules would then disagree about one comment |
| Sentence length | The rulebook in `generic-comment-gate.md` attributes "average 15 to 20 words, none over 30" to ISO 24495-1. The v0.6.2 code skill contains no such number (T22), and the project cancelled comment prose checks because "Comments are fragments" (T23). Plain language says 25 (L29, L35, L41) or 15-20 (L45) | Keep the 30-word failure in `comment_gate.py` (T25). Relabel it a house threshold [Assumed]. Do not add a second threshold in this round | The number is already enforced and has flagged 2 comments in the baseline. The defect is the citation, not the value. No cited source supports 30: L45 says 15 to 20 and L29, L35 and L41 say 25. It is kept because the measured unit is not a sentence. `_clean_comment_text` joins every line of a comment with a space (`comment_gate.py:271`) and `SENTENCE_SPLIT_RE` splits on terminal punctuation (`:61`), so the flag measures the longest run without a full stop inside a merged comment block, and a 25 cap would fire on well-formed multi-line comments. Old code is out of scope anyway (T24), with one narrow exception the docstring states at `:10-12`: an existing comment re-enters when the diff adds a line to it |
| Action tag format | Kotlin and Android never mention TODO or FIXME (K15). Google's Java guide puts the id after the colon with a hyphen (K16). Google's C++ guide ranks `TODO(bug 12345678):` third and `TODO(John)` last (K17). detekt forbids the literal `TODO:`, `FIXME:` and `STOPSHIP:` by default (T11) and offers `allowedPatterns` for a ticket shape (T12) | `// TODO(DEV-123): ...`, the parenthesised form the owner proposed | K17 lists four recommended styles in order: `TODO: bug 12345678 - ...`, `TODO: example.com/... - ...`, `TODO(bug 12345678): ...`, `TODO(John): ...` [Measured]. Two of them avoid detekt's default forbidden literal `TODO:`; the parenthesised ticket form is the higher-ranked of the two, and the other, `TODO(John):`, is excluded by K16's avoid-individuals clause, not by detekt. K16 cannot be cited for this format: it mandates `TODO:` plus a link plus a hyphen, which DOC-003 forbids. K16 supports only "the tag carries a tracked reference" and "avoid an individual" |
| `FIXME` and `STOPSHIP` | The owner wanted `FIXME:` allowed. detekt forbids both by default (T11) | One tag only. `FIXME` and `STOPSHIP` do not land | A marker with no id is untracked work, and the gate cannot tell it from an ordinary comment. Two tags with the same meaning also break "one term per concept" (L22, T19). `HACK` and `XXX` were never real defaults either: detekt's page and Google's C++ guide show zero occurrences of both, so they are dropped from the vocabulary, the regex and the flag table too; the surviving tag words are exactly `TODO`, `FIXME`, `STOPSHIP`, all three sourced to T11 |
| Named owner in the tag | Google C++ allows a name or e-mail (K17); Google Java says "Avoid adding TODOs that refer to an individual" (K16) | Issue id only, never a person | The newer of the two Google texts says so, and a personal name in a shared repository ages worse than a ticket |

## 3. What nobody says (and why we impose it from outside)

- No official Kotlin or Android page says anything about `TODO` or `FIXME` (K15, [Measured] by a
  zero-match grep on all three pages). DOC-003 is therefore a house rule that borrows a Google sibling
  guide's shape (K16, K17) and detekt's default vocabulary (T11).
- Nobody bounds the length of a comment sentence. Plain language bounds prose sentences (L29, L45); the
  code skill deliberately declines to, because comments are fragments (T23). The 30-word cap is ours.
- Nobody says how a KDoc and a plain comment differ in enforcement. detekt's `comments` rules treat both
  as documentation; `comment_gate.py` distinguishes `kdoc` from `line` and `block` (T27) and DOC-002
  needs that split to exist.
- Nobody covers the transient marker. `NEEDS-COMMENT` (T25) is a proposer-to-gate handshake with no
  parent in any source family. DOC-003 must keep it separate from `TODO`, or the gate's verify mode
  starts deleting tracked work.
- Nobody measures comments on a diff. Every rule in every family is written for a file at rest. The
  script's "only comments the diff adds" scope (T24) is a house decision and is the reason old code is
  never re-flagged.

## 4. Rule design, decision by decision

| Decision | Sources |
|---|---|
| DOC-002 governs shape, never presence | K11 and K12 against T21; B8 (public interfaces only) |
| First sentence is a summary fragment | K2, K7, K8; L5, L15, L43 |
| Ban the two openers Android names, nothing else | K8 |
| Verb first is a default, not a check | K8 against L33, L49, L50 |
| Symbols in backticks, references in brackets | K1, K3 |
| `@param` and `@return` only when the prose cannot carry them | K5, B4 |
| A block tag present must carry a description | K10, T5 |
| Do not flag KDoc on a private declaration | T7 not adopted; DOC-001 is about the reader, and `DECLARATION_RE` already excludes `private` (T27) |
| Do not flag a missing KDoc on an override | K13 |
| One action tag, `TODO(DEV-###):` | K16, K17, T11, T12, T13 |
| No person's name in the tag | K16 |
| `NEEDS-COMMENT` stays a separate kind | T24, T25; generic-comment-gate protocol step 4 |
| 30-word cap kept, reattributed as a house threshold | T22, T23, T25; L29, L45 as the outside reference |
| No readability formula anywhere | L47, L48; T23 |

## 5. What was measured

Baseline over the last five merge commits into `origin/develop`, one run per merge, with
`python3 lib/comment_gate.py --repo <repo> --range <merge>^..<merge>`.
Merges: `d6a23219`, `e2052130`, `6a2a95e8`, `6ccd9f6c`, `d8cc5b2e`. All five exited 0.

Numbers the script printed [Measured]:

| Merge | total | kdoc | markers | flagged |
|---|---|---|---|---|
| d6a23219 | 0 | 0 | 0 | 0 |
| e2052130 | 0 | 0 | 0 | 0 |
| 6a2a95e8 | 0 | 0 | 0 | 0 |
| 6ccd9f6c | 0 | 0 | 0 | 0 |
| d8cc5b2e | 89 | 13 | 0 | 4 |
| total | 89 | 13 | 0 | 4 |

Widened to the seventeen independent merges reachable from `origin/develop` (three of the twenty
sampled are contained in `d8cc5b2e` and are not counted twice): 147 comments, 43 KDoc, 9 flags, 0 action
tags [Measured]. `aa03797c` alone adds 29 KDoc. Against that sample the proposed banned-opener regex
scores 0 true positives, and a hard verb-first rule would flag 27 KDocs that K8 declares correct, not 6.

Four of the five merges brought no new comment on the first-parent diff; they are master-into-develop
merges. `d8cc5b2e` is not one pull request: `git log --oneline d8cc5b2e1^..d8cc5b2e1` returns 37 commits
and `git log --oneline --merges` on the same range returns pull requests #208, #207, #206 and #204
[Measured]. The 89 comments are four pull requests over six days. The KDoc slice is narrower than that:
12 of the 13 come from one feature, `DsThemer`, in #204. The 89 comments split 76 `line` and 13 `kdoc`.
The 4 flagged are 2 `too_long` and 2 `narrates_diff`. Markers: 0, so DOC-003 costs nothing today.

Verb-first count, from the same JSON [Measured]: 7 of 13 KDoc first sentences start with a verb. Method:
I read the `text` field of every entry whose `kind` is `kdoc`, collapsed whitespace, split it with the
script's own `SENTENCE_SPLIT_RE`, took the first sentence's first word, and classified that word by
hand. Of the 7, five are third-person singular (`Coordinates`, `Applies` four times) and two are
imperative (`Register`, `Unregister`). The other 6 open with a noun phrase (`App-side implementation of
[DsThemer].`, `Contract exposed by ...`, `Text size multiplier ...`, `Global holder for ...`, `Safe
accessor: ...`, `Tag key used to ...`). None of the 13 opens with either form K8 bans. So a hard
verb-first rule would flag 6 of 13 KDocs that Android's own text declares correct, and the rule this
round proposes flags 0 of them.

One more number, counted the same way [Measured]: 10 of the 76 non-KDoc comments sit on a statement the
script marks `kdoc_candidate`, that is a public or internal declaration. A presence rule would demand
KDoc on all 10. That is the size of the noise the presence decision in section 2 avoids.

What stays unmeasured: whether any of these comments is actually useful to a reader. The script measures
shape. Nobody in this round read the annotated code to test comprehension.

## Verdict

The two new rules invent one thing and borrow the rest. DOC-002 borrows its whole shape from Android
section 7 and the Kotlin conventions (K2, K5, K7, K8, K9, K10), and its restraint from the fact that the
one family demanding presence (K11) publishes an exception that is DOC-001's own criterion (K12).
DOC-003 is the invention: no Kotlin or Android page mentions an action tag at all (K15), so the format
comes from a Google guide for other languages (K16, K17) and the vocabulary from the one detekt rule
that ships on (T11). The honest gaps: the owner's Effective Kotlin citation was wrong and is dropped
(B11); the 30-word cap has no parent standard and is relabelled, not changed (T22, T23); and the
baseline is one pull request, so the 16-of-43 verb count argues against a hard rule but cannot support
a threshold of its own.

## Follow-up

**FU-1, `NARRATES_DIFF_RE` false positives.** `comment_gate.py:62` matches `fix(?:ed)?` and `updated?`
case-insensitively at the start of the merged text, so it cannot tell an adjective or an imperative from
a diff narration. Measured on `d8cc5b2e1^..d8cc5b2e1`: 2 of 2 firings are false positives, `Fixed neutral
gradient used for the payment process screen background ...` and `Update only the purchase entry. A
Seglan offline refund may have queued additional states ...`. This is the incumbent DOC-001 detector, not
a DOC-002 or DOC-003 one, so it is out of scope for this round. It goes on the list as its own item, with
those two strings as its regression inputs.
