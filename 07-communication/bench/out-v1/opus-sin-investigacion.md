# The "split-attention effect" and technical documentation

Before starting, a clarification on where everything I'm about to say comes from, because I think it matters more to you than the explanation itself: **I have not read the article**. The three quotes I use are the ones you gave me; I reproduce them literally and attribute them to Sweller, van Merriënboer and Paas (2019), but I have not been able to verify either their exact wording or their context in the original. Everything else, the plain-language explanation and, above all, the implications for writing documentation, is my own reasoning, not the article's. I'll mark which is which as I go.

## What it is, in one sentence

*[My explanation, built on the quote]* The split-attention effect occurs when, to understand something, the reader has to join in their head two pieces of information that are kept apart: a diagram here and the text explaining it there, a code snippet up top and the description of its parameters three screens down. Neither piece makes sense on its own. The reader goes back and forth, holding one in memory while searching for the other, and that back-and-forth consumes mental effort that isn't spent learning.

*[Literal quote from source (1), exactly as you gave it to me]*

> "Learners must mentally integrate two sources of information in order to understand the solution, a process that yields a high cognitive load and hampers learning."

In other words: the learner has to mentally integrate two sources of information to understand the solution, and that process generates a high cognitive load that hampers learning. The key is in the verb *integrate*: the cost isn't produced by the information itself, but by the added task of joining it together.

## Why "more information" isn't the same as "better explained"

*[Literal quote from source (2), on the redundancy effect]*

> "only presenting the diagram was superior to presenting both sources of information together."

*[My interpretation]* Here's the counterintuitive part, and it's the bit that usually surprises documentation writers the most. When the diagram already explains itself, adding text that says the same thing **worsens** the result: presenting only the diagram worked better than presenting both sources together. Adding material that repeats what's already there isn't a harmless extra; the reader can't know in advance that it's redundant, so they process it, compare it, and pay the cost. Watch this nuance, which is mine and worth spelling out: this holds when one of the two sources is **self-sufficient**. When neither makes sense alone, the problem isn't redundancy but split attention, and the fix isn't to delete one, but to integrate them.

## Where that load comes from

*[Partial quote from source (3), on extraneous load]* Based on what you sent me, the article places extraneous load, the load that doesn't come from the content's intrinsic difficulty, in how the information is presented: it is determined by

> "how the information is presented and what the learner is required to do by the instructional procedure."

*[My comment]* This is what turns the issue into a writing problem, not a matter of the reader's intelligence. The subject's own difficulty (a distributed architecture is intrinsically complex) can't be lowered without lying. But the load your way of presenting it adds, and the tasks your document forces the reader to do to follow you, that part is entirely yours. And that's where it's won or lost.

## What it implies for writing technical documentation

*[This whole section is my extrapolation. The article, as far as the quotes I have reach, deals with instruction and learning in general, not software documentation. Treat it as reasoned advice, not a finding of the study.]*

- **Integrate instead of juxtaposing.** Labels inside the diagram, not in a separate caption. Comments inside the code block, not in a paragraph afterward that forces looking up and down. A parameter's explanation next to the parameter.
- **What belongs together, keep together.** If the reader needs A and B at the same time, don't split them with a page break, a collapsible section, or a link. Every jump is a mental integration you're charging them for.
- **Delete the repetition when one version is already enough.** A clear diagram followed by a paragraph that narrates it step by step is usually worse than the diagram alone. It hurts to delete your own text; do it anyway.
- **Reference duplication is different.** Repeating a fact in a lookup table read in isolation isn't the same as repeating it twice in a row within a linear explanation. The criterion is what the reader is doing at that moment, not whether the words match.
- **Measure by what the document forces the reader to do.** A good review question: how many times does the reader have to jump from one place to another to understand this section? Every jump avoided is extraneous load you're giving back so they can focus on understanding the actual content.

## What I can't claim

*[Limits, mine]* I don't know whether the article uses exactly these words, or in which paragraph, because I haven't read it; I'm trusting your transcription. I also don't know what specific experiments back the sentence about the diagram, or with what materials or what population, so I can't tell you how much it generalizes to technical documentation read by professionals, which is a fairly different context from a student solving a problem under supervision. If this is going to support a team decision or be cited in something published, verify the three quotes against the original at https://link.springer.com/article/10.1007/s10648-019-09465-5 before using them.
