Sure, let me explain it relying only on what we have literally quoted from Sweller, van Merriënboer and Paas (2019).

**What the split-attention effect is**

It happens when two sources of information (for example, a text and a diagram, or a code snippet and its explanation) are separated physically or in time, and the reader needs to integrate them mentally to understand the content. Per the source: "Learners must mentally integrate two sources of information in order to understand the solution, a process that yields a high cognitive load and hampers learning." (literal quote, source 1). In other words: the very act of searching for, relating, and combining scattered information consumes cognitive resources that should go toward understanding the content, and that's why learning suffers.

**A related effect: redundancy**

The same authors document a relevant, and somewhat counterintuitive, finding about what happens when two sources could already be integrated visually without help from additional text: "only presenting the diagram was superior to presenting both sources of information together." (literal quote, source 2). This points to adding redundant text to a diagram that's already understandable on its own not necessarily helping, and in the cited study it even turned out worse than presenting only the diagram.

**Where that load comes from**

The authors attribute this kind of load to what they call extraneous load, which, as they define it, is determined by "how the information is presented and what the learner is required to do by the instructional procedure." (literal quote, source 3). In other words, it isn't a property of the content itself (that would be intrinsic load), but of the instructional design: how the information is presented and what the reader is required to do to put the pieces together.

**What it implies for writing technical documentation**

From here on I'm no longer quoting literally, but drawing consequences from those three statements. I'm marking the epistemic status of each one because I haven't read the full article, I'm only working with the three quotes you gave me, so it's up to me to decide how to label them:

- **Derived directly from quote (1):** if in your documentation you separate code from its explanation, or an architecture diagram from the steps that describe it, forcing the reader to jump their gaze between the two, you're imposing that extra mental-integration work on them. For a reader who doesn't know the topic, that cost weighs more, because they have no prior knowledge to fill the connection with little effort.
- **Derived directly from quote (2):** don't assume text + diagram is always better than either one alone. If a diagram already conveys the idea on its own, adding a parallel textual explanation can be redundant and even counterproductive instead of reinforcing it. Careful: this is a finding by the authors in the context of their own study, not necessarily a universal rule for every kind of technical documentation, with the quotes I have I can't say under what conditions it generalizes.
- **Derived directly from quote (3):** since extraneous load depends on "how" something is presented and not on the content itself, it's a load that you, as the writer, control almost entirely through formatting decisions: where you place each annotation, how close an explanation sits to what it explains, how much the reader has to "search."
- **My own inference, not literally backed by the quotes given:** as a practical consequence, I'd recommend physically integrating (same place, same moment) the explanatory text and the visual or code element it refers to, for example, inline comments instead of end notes, or labels inside the diagram itself instead of a separate caption. This is a reasonable extension of the principle, but it isn't taken verbatim from the source nor verified by me in the original article.

In short: if your reader doesn't know the topic, any separation between elements that must be interpreted together imposes an avoidable cognitive load, and in some cases it's not even worth duplicating the information in two formats, sometimes a single well-designed element communicates better than the sum of two.
