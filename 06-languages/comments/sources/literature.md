# Sources · literature

Evidence dossier, no line cap. Literal quotations in their original language. Read on 18-sep-2026.
Tags: [Measured] read on the page; [Inferred] snippet only; [Unknown] not verifiable. B# ids are cited
from `../010-research.md` and `../011-proposed-rules.md`.

The three books are paid. None was bought for this round. Two of the three authors publish their
positions on comments in the open, in a repository they co-wrote, so the load-bearing quotations come
from there and are [Measured] on that page, not on the printed page.

Topics: (a) what a comment is for · (b) interface documentation · (c) redundant block tags ·
(d) where the authors disagree.

## 1. Evidence table

| Id | Source | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|---|
| B1 | Robert C. Martin, *Clean Code* p. 54, as quoted in Ousterhout's `aposd-vs-clean-code` | a | "The proper use of comments is to compensate for our failure to express ourselves in code. Note that I use the word failure. I meant it. Comments are always failures. We must have them because we cannot always figure out how to express ourselves without them, but their use is not a cause for celebration... Every time you write a comment, you should grimace and feel the failure of your ability of expression." | https://github.com/johnousterhout/aposd-vs-clean-code | [Measured] on that page; the printed book was not read |
| B2 | Robert C. Martin, same page, replying about the same chapter | a | "That chapter begins with these words: *Nothing can be quite so helpful as a well placed comment.* It goes on to say that comments are a *necessary* evil." | = B1 | [Measured] |
| B3 | John Ousterhout, same page, counting the chapter | a | "Chapter 4 spends 4 pages talking about good comments, followed by 15 pages talking about bad comments." | = B1 | [Measured] |
| B4 | Robert C. Martin, same page | c | "I'm not opposed to Javadocs as a rule; but I write them only when absolutely necessary. I also have an aversion for descriptions and `@param` statements that are perfectly obvious from the method signature." | = B1 | [Measured] |
| B5 | Robert C. Martin, same page | a | "Another way to say this is that the best comments tell me something surprising and verifiable about the code. The worst are those that waste my time telling me something obvious, or incorrect." | = B1 | [Measured] |
| B6 | John Ousterhout, same page | a | "The second general reason for comments is for important information that is not obvious from the code." | = B1 | [Measured] |
| B7 | Ousterhout and Martin, same page, Comments Summary | a | "We agree that implementation code only needs comments when the code is nonobvious. Although neither of us argues for a large number of implementation comments, I'm more likely to see value in them than you do." | = B1 | [Measured] |
| B8 | Ousterhout and Martin, same page, Comments Summary | b | "I believe that it is not possible to define interfaces and create abstractions without a lot of comments. You agree for public APIs, but see little need to comment interfaces that are internal to the team." | = B1 | [Measured] |
| B9 | Ousterhout and Martin, same page, Comments Summary | d | "I would probably write 5-10x more lines of comments for a given piece of code than you would." / "Overall, we struggled to find areas of agreement on this topic." | = B1 | [Measured] |
| B10 | John Ousterhout, Stanford book page | d | "I have added subsections in two chapters to compare the book's design philosophy with that of Robert Martin's Clean Code (we have significant differences of opinion on topics such as the length of methods and the role of comments)." | https://web.stanford.edu/~ouster/cgi-bin/book.php | [Measured] |
| B11 | *Effective Kotlin*, Leanpub table of contents | b | "Chapter 4: Abstraction design" contains "Item 30: Define contracts with documentation" and "Item 31: Respect abstraction contracts". | https://leanpub.com/effectivekotlin | [Measured] on the publisher's table of contents; the item body is paid and was not read, so its content is [Unknown] |
| B12 | *A Philosophy of Software Design*, chapters 12 and 13 | a | Chapter 13 is reported as "Comments Should Describe Things that Aren't Obvious from the Code". No primary listing was obtained: the author's public extract (`aposd2ndEdExtract.pdf`, 13.9 MB) is a scan with no text layer, and the library scan of the table of contents would not convert. | https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf | [Inferred] from secondary search results; not load-bearing anywhere in this round |

## 2. Where they agree

- A comment must carry something the reader cannot recover from the code: B5, B6, B7.
- Implementation comments are for the non-obvious only: B7, agreed by both authors in one sentence.
- A `@param` that repeats the signature is waste: B4. This is the *Clean Code* author agreeing with the
  Kotlin coding conventions (K5).
- Public interfaces need documentation: B8, where the disagreement is about internal interfaces only.

## 3. Where they differ

- The value of a comment. *Clean Code* frames every comment as a failure of expression (B1); Ousterhout
  calls that stigmatising and writes five to ten times more of them (B9).
- Internal interfaces. Ousterhout documents them; Martin sees little need (B8).
- Trust. Martin treats every comment as potential misinformation until cross-checked (B5); Ousterhout
  trusts comments so he can read less code (B9 context).

## 4. Not verifiable

- *Clean Code* chapter 4 was not read in print. B1 is the text as quoted, with a page number, on a page
  its own author co-wrote and never disputed there.
- *Effective Kotlin* Item 30 body is paid. Only its title and chapter are [Measured] (B11).
- *A Philosophy of Software Design* chapters 12 and 13 are [Inferred] (B12) and carry no rule in this round.
