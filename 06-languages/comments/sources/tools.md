# Sources · tooling

Evidence dossier, no line cap. Literal quotations in their original language. Read on 18-sep-2026 with
WebFetch, `curl` and the GitHub API. Tags: [Measured] read on the page; [Inferred] snippet only;
[Unknown] not verifiable. T# ids are cited from `../010-research.md` and `../011-proposed-rules.md`.

Topics: (a) detekt `comments` rule set · (b) detekt action tags · (c) iso-24495-code v0.6.2 ·
(d) the repo's own script.

## 1. Evidence table

| Id | Source | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|---|
| T1 | detekt, Comments rule set, intro | a | "This rule set provides rules that address issues in comments and documentation of the code." | https://detekt.dev/docs/rules/comments/ | [Measured] |
| T2 | detekt, UndocumentedPublicFunction | a | "This rule will report any public function which does not have the required documentation." Active by default: **No**. | = T1 | [Measured] |
| T3 | detekt, UndocumentedPublicClass | a | "This rule reports public classes, objects and interfaces which do not have the required documentation." Active by default: **No**. | = T1 | [Measured] |
| T4 | detekt, UndocumentedPublicProperty | a | "This rule will report any public property which does not have the required documentation." Active by default: **No**. | = T1 | [Measured] |
| T5 | detekt, OutdatedDocumentation | a | "This rule will report any class, function or constructor with KDoc that does not match the declaration signature." Active by default: **No**. | = T1 | [Measured] |
| T6 | detekt, EndOfSentenceFormat | a | "This rule validates the end of the first sentence of a KDoc comment." Active by default: **No**. | = T1 | [Measured] |
| T7 | detekt, DocumentationOverPrivateFunction / DocumentationOverPrivateProperty | a | "This rule reports documentation that has been added to private functions." / "This rule reports documentation above private properties." Active by default: **No**. | = T1 | [Measured] |
| T8 | detekt, AbsentOrWrongFileLicense | a | "This rule will report every Kotlin source file which doesn't have the required license header." Active by default: **No**. | = T1 | [Measured] |
| T9 | detekt, comments rule set, full inventory | a | The page lists exactly ten rules: AbsentOrWrongFileLicense, DeprecatedBlockTag, DocumentationOverPrivateFunction, DocumentationOverPrivateProperty, EndOfSentenceFormat, KDocReferencesNonPublicProperty, OutdatedDocumentation, UndocumentedPublicClass, UndocumentedPublicFunction, UndocumentedPublicProperty. None is active by default. `CommentOverridingMethod` is not among them. | = T1 | [Measured] |
| T10 | detekt, ForbiddenComment (style rule set, not comments) | b | "This rule allows to set a list of comments which are forbidden in the codebase and should only be used during development. Offending code comments will then be reported." Active by default: **Yes**. | https://detekt.dev/docs/rules/style/ | [Measured] |
| T11 | detekt, ForbiddenComment defaults | b | "# Repeat the default configuration if it's still needed." followed by: `reason: 'Forbidden FIXME todo marker in comment, please fix the problem.' value: 'FIXME:'` / `reason: 'Forbidden STOPSHIP todo marker in comment, please address the problem before shipping the code.' value: 'STOPSHIP:'` / `reason: 'Forbidden TODO todo marker in comment, please do the changes.' value: 'TODO:'` | = T10 | [Measured] |
| T12 | detekt, ForbiddenComment, allowedPatterns | b | "ignores comments which match the specified regular expression. For example `Ticket\|Task`." | = T10 | [Measured] |
| T13 | detekt, ForbiddenComment, matching semantics | b | "KDoc comments are not split up, the regex will be applied to the whole comment." / "The regex will be searched using "contains" semantics not "matches", so partial comment matches will flag forbidden comments." | = T10 | [Measured] |
| T14 | iso-24495, release tags | c | The API returns nine tags: `v0.6.2, v0.6.1, v0.6.0, v0.5.0, v0.4.1, v0.4.0, v0.3.1, v0.3.0, measurements-2026-08-22g`. `v0.6.2` is the newest, so the pin in `generic-comment-gate.md` is current. Method: `GET https://api.github.com/repos/GaZmagik/iso-24495/tags`, 18-sep-2026. | https://github.com/GaZmagik/iso-24495/tags | [Measured] |
| T15 | iso-24495-code v0.6.2, front matter | c | `name: iso-24495-code` / `metadata: version: "0.6.2"` / `iso-standard: "ISO 24495-1:2023"` / `iso-status: "published, applied by analogy to source code"` | https://raw.githubusercontent.com/GaZmagik/iso-24495/v0.6.2/skills/iso-24495-code/SKILL.md | [Measured] |
| T16 | iso-24495-code v0.6.2, scope | c | "**This is an interpretation of ISO 24495-1 applied by analogy, not a conformance claim.**" | = T15 | [Measured] |
| T17 | iso-24495-code v0.6.2, rule 4 | c | "A comment earns its place when it records something a reader cannot recover from the code: a reason, a constraint, a rejected alternative, a bug it guards against." / "**Delete a comment that merely restates the line beneath it**, and delete commented-out code." | = T15 | [Measured] |
| T18 | iso-24495-code v0.6.2, rule 4 | c | "This is not a rule against documentation. An interface comment tells a caller what a function returns, when it returns nothing, and what it throws. That is the reader's work being done for them, so it belongs there even when the body makes it obvious." | = T15 | [Measured] |
| T19 | iso-24495-code v0.6.2, rule 3 | c | "**Use one name for one concept throughout.** If it is a `token` here it is not a `lexeme` three functions later. Elegant variation confuses code exactly as it confuses prose." | = T15 | [Measured] |
| T20 | iso-24495-code v0.6.2, rule 6 | c | "Where two constructions are equally correct, use the one a competent reader understands without pausing. Cleverness that needs a comment to explain it has already failed." | = T15 | [Measured] |
| T21 | iso-24495-code v0.6.2, "What this skill does not do" | c | "It does not require comments. A file with no comments and clear names is fine." | = T15 | [Measured] |
| T22 | iso-24495-code v0.6.2, negative check on prose limits | c | The file contains no sentence-length number. Method: `rg -n "sentence\|word\|15\|20\|30" -i` over the fetched file, 18-sep-2026; the only numeric hit is "30 generated implementations" in rule 1's measurement note. | = T15 | [Measured] |
| T23 | iso-24495 README, roadmap | c | "Plain-language checks on script comments were once planned for this release. That plan is cancelled. Comments are fragments, and checking them well would cost more machinery than the advice is worth." | https://github.com/GaZmagik/iso-24495 | [Measured] |
| T24 | `comment_gate.py`, module docstring | d | "This is the deterministic half of the comment gate (DOC-001): this script says WHAT new comments exist, where, how big they are, and what shape they have; the `generic-comment-gate` agent decides whether they deserve to exist and `generic-mechanic` applies the decision. No verdict comes out of here, only facts." | lib/comment_gate.py:4 | [Measured] (repo file) |
| T25 | `comment_gate.py`, constants | d | `MARKER = "NEEDS-COMMENT"` / `MAX_SENTENCE_WORDS = 30` / `RESTATES_RATIO = 0.6` | lib/comment_gate.py:49 | [Measured] (repo file) |
| T26 | `comment_gate.py`, flag vocabulary | d | The `_flags` function emits exactly: `commented_out_code`, `narrates_diff`, `restates_code`, `non_english`, `has_secret_shape`, `too_long`. Nothing about KDoc shape or action tags. | lib/comment_gate.py:302 | [Measured] (repo file) |
| T27 | `comment_gate.py`, KDoc detection | d | `kind = "kdoc" if stripped.startswith("/**") and not stripped.startswith("/**/") else "block"`; `kdoc_candidate` is set from `DECLARATION_RE`, which excludes `private`. | lib/comment_gate.py:232, :341 | [Measured] (repo file) |

## 2. Where they agree

- A comment that restates the line below it is a defect: T17, and the script's `restates_code` flag (T26).
- Interface documentation is not a comment and survives the "delete what restates" rule: T18.
- Action tags left in the tree are debt, and tooling expects them to carry a tracker reference:
  T10, T11, T12.

## 3. Where they differ

- Presence. detekt ships presence rules for public classes, functions and properties (T2, T3, T4); the
  iso-24495-code skill says the opposite, that no file is required to have comments (T21).
- Default posture. Every detekt `comments` rule is off by default (T9), so detekt ships no opinion until
  a team turns one on. ForbiddenComment is the exception and is on (T10).
- Prose limits. The rulebook embedded in `generic-comment-gate.md` attributes "sentences average 15 to
  20 words, none over 30" to ISO 24495-1. The v0.6.2 code skill carries no such number (T22) and the
  project that publishes it cancelled comment prose checks on the grounds that comments are fragments
  (T23). The 30-word cap in the script (T25) is therefore a house threshold with no cited parent.

## 4. Not verifiable

The paid text of ISO 24495-1:2023 was not read; T15 to T23 quote the skill that interprets it, which
says itself that it is an interpretation and not a conformance claim (T16).
