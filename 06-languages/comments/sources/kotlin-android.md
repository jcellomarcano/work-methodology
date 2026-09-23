# Sources · Kotlin and Android official documentation

Evidence dossier, no line cap. Literal quotations in their original language. Read on 18-sep-2026 with
WebFetch and with `curl` for the negative checks. Tags: [Measured] read on the page; [Inferred] snippet
only; [Unknown] not verifiable. K# ids are cited from `../010-research.md` and
`../011-proposed-rules.md`.

Topics: (a) what KDoc is · (b) the summary fragment · (c) block tags · (d) markup and links ·
(e) where documentation is required · (f) action tags (TODO, FIXME).

## 1. Evidence table

| Id | Source | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|---|
| K1 | Kotlin docs, "Document Kotlin code: KDoc", KDoc syntax | a | "The language used to document Kotlin code (the equivalent of Java's Javadoc) is called KDoc. In essence, KDoc combines Javadoc's syntax for block tags (extended to support Kotlin's specific constructs) and Markdown for inline markup." | https://kotlinlang.org/docs/kotlin-doc.html | [Measured] |
| K2 | Kotlin docs, KDoc syntax | b | "By convention, the first paragraph of the documentation text (the block of text until the first blank line) is the summary description of the element, and the following text is the detailed description." | = K1 | [Measured] |
| K3 | Kotlin docs, Inline markup | d | "For inline markup, KDoc uses the regular Markdown syntax, extended to support a shorthand syntax for linking to other elements in the code." | = K1 | [Measured] |
| K4 | Kotlin docs, Block tags | c | "@param Documents a value parameter of a function or a type parameter of a class, property, or function." / "@return Documents the return value of a function." / "@throws ... Documents an exception which can be thrown by a method." / "@property Documents the property of a class which has the specified name." / "@constructor Documents the primary constructor of a class." | = K1 | [Measured] |
| K5 | Kotlin coding conventions, "Documentation comments" | c | "Generally, avoid using @param and @return tags. Instead, incorporate the description of parameters and return values directly into the documentation comment, and add links to parameters wherever they are mentioned. Use @param and @return only when a lengthy description is required which doesn't fit into the flow of the main text." | https://kotlinlang.org/docs/coding-conventions.html#documentation-comments | [Measured] |
| K6 | Kotlin coding conventions, "Documentation comments" | b | "For longer documentation comments, place the opening `/**` on a separate line and begin each subsequent line with an asterisk" / "Short comments can be placed on a single line" | = K5 | [Measured] |
| K7 | Android Kotlin style guide, 7.2 Summary fragment | b | "Each KDoc block begins with a brief summary fragment. This fragment is very important: it is the only part of the text that appears in certain contexts such as class and method indexes." | https://developer.android.com/kotlin/style-guide | [Measured] |
| K8 | Android Kotlin style guide, 7.2 Summary fragment | b | "... a noun phrase or verb phrase, not a complete sentence. It does not begin with "A `Foo` is a...", or "This method returns...", nor does it have to form a complete imperative sentence like "Save the record.". However, the fragment is capitalized and punctuated as if it were a complete sentence." | = K7 | [Measured] (the elided opening clause carries a dash in the source) |
| K9 | Android Kotlin style guide, 7.1 Formatting | b | "The basic form is always acceptable. The single-line form may be substituted when the entirety of the KDoc block (including comment markers) can fit on a single line. Note that this only applies when there are no block tags such as `@return`." | = K7 | [Measured] |
| K10 | Android Kotlin style guide, 7.1 Block tags | c | "Any of the standard "block tags" that are used appear in the order `@constructor`, `@receiver`, `@param`, `@property`, `@return`, `@throws`, `@see`, and these never appear with an empty description. When a block tag doesn't fit on a single line, continuation lines are indented 4 spaces from the position of the `@`." | = K7 | [Measured] |
| K11 | Android Kotlin style guide, 7.3 Usage | e | "At the minimum, KDoc is present for every `public` type, and every `public` or `protected` member of such a type, with a few exceptions noted below." | = K7 | [Measured] |
| K12 | Android Kotlin style guide, 7.3.1 Exception: self-explanatory functions | e | "KDoc is optional for "simple, obvious" functions like `getFoo` and properties like `foo`, in cases where there really and truly is nothing else worthwhile to say but "Returns the foo"." / "It is not appropriate to cite this exception to justify omitting relevant information that a typical reader might need to know." | = K7 | [Measured] |
| K13 | Android Kotlin style guide, 7.3.2 Exception: overrides | e | "KDoc is not always present on a method that overrides a supertype method." | = K7 | [Measured] |
| K14 | Android Kotlin style guide, 7.1.1 Paragraphs | b | "... appears between paragraphs, and before the group of block tags if present." | = K7 | [Measured] (the elided clause carries dashes in the source) |
| K15 | Negative check on the three pages above | f | The strings `TODO` and `FIXME` do not appear on any of the three pages. Method: `curl -sL <url> \| rg -o -i "TODO[^<]{0,80}\|FIXME[^<]{0,80}"`, run 18-sep-2026, zero matches on each. | K1, K5, K7 | [Measured] |

## 2. Annex: Google sibling style guides (not Kotlin, not Android)

Cited only because K15 shows the Kotlin and Android documents are silent on action tags. The Android
Kotlin style guide is a Google document, so its siblings are the nearest official text, but they govern
other languages. Weigh them as such.

| Id | Source | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|---|
| K16 | Google Java Style Guide, 4.8.6.2 TODO comments | f | "Use TODO comments for code that is temporary, a short-term solution, or good-enough but not perfect." / "A TODO comment begins with the word TODO in all caps, a following colon, and a link to a resource that contains the context, ideally a bug reference. A bug reference is preferable because bugs are tracked and have follow-up comments. Follow this piece of context with an explanatory string introduced with a hyphen `-`." / "The purpose is to have a consistent TODO format that can be searched to find out how to get more details." / "Avoid adding TODOs that refer to an individual or team as the context:" | https://google.github.io/styleguide/javaguide.html | [Measured] |
| K17 | Google C++ Style Guide, TODO Comments | f | "TODOs should include the string TODO in all caps, followed by the bug ID, name, e-mail address, or other identifier of the person or issue with the best context about the problem referenced by the TODO." / "Recommended styles are (in order of preference):" `// TODO: bug 12345678 - Remove this after the 2047q4 compatibility window expires.` ... `// TODO(bug 12345678): Update this list after the Foo service is turned down.` ... `// TODO(John): Use a "\*" here for concatenation operator.` | https://google.github.io/styleguide/cppguide.html | [Measured] |

## 3. Where they agree

- The first paragraph is the summary and carries the weight: K2, K7.
- Block tags are for what the prose cannot carry, and an empty tag is a defect: K5, K10.
- Markdown with backticks and bracket links is the markup: K1, K3.
- Documentation on public surfaces is the caller's work done for them: K11, with K12 and K13 as exceptions.
- An action tag needs a tracked identifier, not a person: K16, K17.

## 4. Where they differ

- Presence. Android requires KDoc on every public type and public or protected member (K11); the Kotlin
  coding conventions never state a presence requirement, only a shape (K5, K6).
- Shape of the summary. Android forbids a complete sentence and explicitly allows a noun phrase (K8);
  Kotlin says only that the first paragraph is the summary (K2) and sets no grammar.
- Block tags. Kotlin says "avoid" them (K5); Android lists their order and requires a description when
  present (K10). The two are compatible only if K10 is read as conditional.
- Action tags. Kotlin and Android say nothing (K15); Google's Java guide puts the identifier after the
  colon and its C++ guide ranks the parenthesised form third (K16, K17).

## 5. Not verifiable

Nothing in this file is [Inferred] or [Unknown]. Every quotation was fetched from the URL shown.
