# Sources · official prompting guides (Anthropic, OpenAI, Google)

Evidence dossier, no line cap. Literal quotations in their original language (protocol §3: never translated).
Read on 09-sep-2026 by a research agent with WebFetch. Tags: [Measured] read on the page;
[Inferred] from a search snippet only; [Unknown] not verifiable. Ids (A#, O#, G#) are cited
from `../research.md` and `../rules.md`.

Topics: (a) role/persona · (b) format and structure · (c) conciseness/length · (d) clarity · (e) important
first / summaries · (f) instruction files (CLAUDE.md, AGENTS.md, GEMINI.md) · (g) audience ·
(h) differences between model families.

## 1. Anthropic (Claude)

| Id | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|
| A1 | (a) | "Setting a role in the system prompt focuses Claude's behavior and tone for your use case. Even a single sentence makes a difference" | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices | [Measured] |
| A2 | (a)/(d) | "Think of Claude as a brilliant but new employee who lacks context on your norms and workflows." | = A1 | [Measured] |
| A3 | (b) | "XML tags help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs." | = A1 | [Measured] |
| A4 | (b) | "Use consistent, descriptive tag names across your prompts." | = A1 | [Measured] |
| A5 | (b) | "Wrap examples in `<example>` tags (multiple examples in `<examples>` tags) so Claude can distinguish them from instructions." | = A1 | [Measured] |
| A6 | (b)/(h) | "Tell Claude what to do instead of what not to do: Instead of: 'Do not use markdown in your response' Try: 'Your response should be composed of smoothly flowing prose paragraphs.'" | = A1 | [Measured] |
| A7 | (b)/(h) | "The formatting style used in your prompt may influence Claude's response style. If you are still experiencing steerability issues with output formatting, try matching your prompt style to your desired output style as closely as possible. For example, removing markdown from your prompt can reduce the volume of markdown in the output." | = A1 | [Measured] |
| A8 | (b) | "Use XML format indicators: Try: 'Write the prose sections of your response in <smoothly_flowing_prose_paragraphs> tags.'" | = A1 | [Measured] |
| A9 | (b)/(c) | "DO NOT use ordered lists (1. ...) or unordered lists (*) unless: a) you're presenting truly discrete items where a list format is the best option, or b) the user explicitly requests a list or ranking" | = A1 | [Measured] |
| A10 | (b)/(c) | "When writing reports, documents, technical explanations, analyses, or any long-form content, write in clear, flowing prose using complete paragraphs and sentences." | = A1 | [Measured] |
| A11 | (c) | "Claude's latest models have a more concise and natural communication style compared to previous models" | = A1 | [Measured] |
| A12 | (c) | "Less verbose: May skip detailed summaries for efficiency unless prompted otherwise" | = A1 | [Measured] |
| A13 | (c)/(h) | "Claude Opus 5 is an exception on verbosity: its default user-facing responses run longer than prior models', and raising or lowering effort does not reliably change visible response length." followed by "Prompt explicitly for conciseness instead." | = A1 | [Measured] |
| A14 | (d) | "Claude responds well to clear, explicit instructions. Being specific about your desired output can help enhance results." | = A1 | [Measured] |
| A15 | (d) | "Golden rule: Show your prompt to a colleague with minimal context on the task and ask them to follow it. If they'd be confused, Claude will be too." | = A1 | [Measured] |
| A16 | (d) | "Providing context or motivation behind your instructions, such as explaining to Claude why such behavior is important, can help Claude better understand your goals and deliver more targeted responses." | = A1 | [Measured] |
| A17 | (d) | "Provide instructions as sequential steps using numbered lists or bullet points when the order or completeness of steps matters." | = A1 | [Measured] |
| A18 | (e) | "Put longform data at the top: Place your long documents and inputs near the top of your prompt, above your query, instructions, and examples. This improves performance across all models." | = A1 | [Measured] |
| A19 | (e) | "After completing a task that involves tool use, provide a quick summary of the work you've done." | = A1 | [Measured] |
| A20 | (h) | "Claude's latest models are trained for precise instruction following and benefit from explicit direction to use specific tools." | = A1 | [Measured] |
| A21 | (h) | "Claude Opus 4.5 and Claude Opus 4.6 are also more responsive to the system prompt than previous models." | = A1 | [Measured] |
| A22 | (g) | "Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them." (the only mention of adapting to audience) | = A1 | [Measured] |
| A23 | (f) | "The more specific and concise your instructions, the more consistently Claude follows them." | https://code.claude.com/docs/en/memory | [Measured] |
| A24 | (f) | "**Size**: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." | = A23 | [Measured] |
| A25 | (f) | "**Structure**: use markdown headers and bullets to group related instructions. Claude scans structure the same way readers do: organized sections are easier to follow than dense paragraphs." | = A23 | [Measured] |
| A26 | (f) | "**Specificity**: write instructions that are concrete enough to verify. For example:" / "\"Use 2-space indentation\" instead of \"Format code properly\"" | = A23 | [Measured] |
| A27 | (f) | "**Consistency**: if two rules contradict each other, Claude may pick one arbitrarily." | = A23 | [Measured] |
| A28 | (f) | "Keep it to facts Claude should hold in every session: build commands, conventions, project layout, \"always do X\" rules." | = A23 | [Measured] |
| A29 | (f) | "Claude Code reads `CLAUDE.md`, not `AGENTS.md`. If your repository already uses `AGENTS.md` for other coding agents, create a `CLAUDE.md` that imports it so both tools read the same instructions without duplicating them." | = A23 | [Measured] |
| A30 | (f) | "CLAUDE.md content is delivered as a user message after the system prompt, not as part of the system prompt itself. Claude reads it and tries to follow it, but there's no guarantee of strict compliance, especially for vague or conflicting instructions." | = A23 | [Measured] |

## 2. OpenAI (GPT / Codex)

| Id | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|
| O1 | (a) | "`developer` messages provide the system's rules and business logic, like a function definition." | https://developers.openai.com/api/docs/guides/prompt-engineering | [Measured] |
| O2 | (a) | "A developer message will contain the following sections, usually in this order: Identity, Instructions, Examples, Context." | = O1 | [Measured] |
| O3 | (a)/(g) | "Identity: Describe the purpose, communication style, and high-level goals of the assistant." | = O1 | [Measured] |
| O4 | (b) | "Markdown headers and lists can be helpful to mark distinct sections of a prompt, and to communicate hierarchy to the model." | = O1 | [Measured] |
| O5 | (b) | "XML tags can help delineate where one piece of content (like a supporting document used for reference) begins and ends." | = O1 | [Measured] |
| O6 | (d) | "GPT models are fast, cost-efficient, and highly intelligent, but benefit from more explicit instructions." | = O1 | [Measured] |
| O7 | (d)/(h) | "A reasoning model is like a senior co-worker. You can give them a goal to achieve and trust them to work out the details." / "A GPT model is like a junior coworker. They'll perform best with explicit instructions to create a specific output." | = O1 | [Measured] |
| O8 | (e) | "Keep content that you expect to use over and over at the beginning of your prompt." | = O1 | [Measured] |
| O9 | (c)/(h) | "In addition to being able to control the reasoning_effort as in previous reasoning models, in GPT-5 we introduce a new API parameter called verbosity, which influences the length of the model's final answer, as opposed to the length of its thinking." | https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide | [Measured] |
| O10 | (c) | "GPT-5 is trained to respond to natural-language verbosity overrides in the prompt for specific contexts where you might want the model to deviate from the global default." | = O9 | [Measured] |
| O11 | (b)/(h) | "By default, GPT-5 in the API does not format its final answers in Markdown" | = O9 | [Measured] |
| O12 | (b) | "Use Markdown **only where semantically correct** (e.g., `inline code`, ```code fences```, lists, tables)." | = O9 | [Measured] |
| O13 | (b)/(h) | "Occasionally, adherence to Markdown instructions specified in the system prompt can degrade over long conversation" and recommends "appending a Markdown instruction every 3-5 user messages." | = O9 | [Measured] |
| O14 | (b)/(h) | "In Cursor's testing, using structured XML specs like <[instruction]_spec> improved instruction adherence on their prompts." | = O9 | [Measured] |
| O15 | (d) | "Like GPT-4.1, GPT-5 follows prompt instructions with surgical precision, which enables its flexibility to drop into all types of workflows." | = O9 | [Measured] |
| O16 | (d) | "Poorly-constructed prompts containing contradictory or vague instructions can be more damaging to GPT-5." / "it expends reasoning tokens searching for a way to reconcile the contradictions rather than picking one" | = O9 | [Measured] |
| O17 | (e) | "Finish by summarizing completed work distinctly from your upfront plan" | = O9 | [Measured] |
| O18 | (c) | "low → terse UX, minimal prose." / "medium (default) → balanced detail." / "high → verbose, great for audits, teaching, or hand-offs." | https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools | [Measured] |
| O19 | (c) | "Keep prompts stable and use the param rather than re-writing." | = O18 | [Measured] |
| O20 | (b) | "# Role and Objective # Instructions ## Sub-categories for more detailed instructions # Reasoning Steps # Output Format # Examples ## Example 1 # Context # Final instructions and prompt to think step by step" | https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide | [Measured] |
| O21 | (b)/(h) | "Markdown: We recommend starting here, and using markdown titles for major sections and subsections (including deeper hierarchy, to H4+)." / "XML: These also perform well, and we have improved adherence to information in XML with this model." | = O20 | [Measured] |
| O22 | (b)/(h) | "JSON is highly structured and well understood by the model particularly in coding contexts. However it can be more verbose, and require character escaping that can add overhead." | = O20 | [Measured] |
| O23 | (e) | "If you have long context in your prompt, ideally place your instructions at both the beginning and end of the provided context, as we found this to perform better than only above or below." | = O20 | [Measured] |
| O24 | (d)/(h) | "GPT-4.1 is trained to follow instructions more closely and more literally than its predecessors, which tended to more liberally infer intent." / "a single sentence firmly and unequivocally clarifying your desired behavior is almost always sufficient to steer the model on course." | = O20 | [Measured] |
| O25 | (c) | "Without specific instructions, some models can be eager to provide additional prose to explain their decisions, or output more formatting in responses than may be desired." | = O20 | [Measured] |
| O26 | (d) | "if there are conflicting instructions, GPT-4.1 tends to follow the one closer to the end of the prompt." | = O20 | [Measured] |
| O27 | (f) | "Think of AGENTS.md as a **README for agents**" / "AGENTS.md is just standard Markdown. Use any headings you like" | https://agents.md/ | [Measured] |
| O28 | (f) | "The closest AGENTS.md to the edited file wins" / "Commit messages or pull request guidelines, security gotchas, large datasets, deployment steps: anything you'd tell a new teammate belongs here too" | https://agents.md/ | [Measured] |
| O29 | (f) | "Codex concatenates files from the root down, joining them with blank lines." / "Files closer to your current directory override earlier guidance because they appear later in the combined prompt." | https://learn.chatgpt.com/docs/agent-configuration/agents-md | [Measured] |
| O30 | (f) | "Codex skips empty files and stops adding files once the combined size reaches the limit defined by `project_doc_max_bytes`." / "Keep rules concise, explain the behavior to flag and any safe path or exception." | = O29 | [Measured] |

## 3. Google (Gemini)

| Id | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|
| G1 | (a) | "You can guide the behavior of Gemini models with system instructions." / "Pass a `system_instruction` parameter to configure the model's behavior." | https://ai.google.dev/gemini-api/docs/text-generation | [Measured] |
| G2 | (a)/(e) | "Prioritize critical instructions: Place essential behavioral constraints, role definitions (persona), and output format requirements in the System Instruction or at the very beginning of the user prompt." | https://ai.google.dev/gemini-api/docs/prompting-strategies | [Measured] |
| G3 | (a) | "You are Gemini 3, a specialized assistant for [Insert Domain, e.g., Data Science]." / "<role>You are a helpful assistant.</role>" | = G2 | [Measured] |
| G4 | (b) | "You can give instructions that specify the format of the response. For example, you can ask for the response to be formatted as a table, bulleted list, elevator pitch, keywords, sentence, or paragraph." | = G2 | [Measured] |
| G5 | (b) | "Structure your response as follows: 1. **Executive Summary**: [Short overview] 2. **Detailed Response**: [The main content]" | = G2 | [Measured] |
| G6 | (b) | "While you can specify the format of simple JSON response objects using prompts, we recommend using Gemini API's structured output feature" | = G2 | [Measured] |
| G7 | (b)/(h) | "Use consistent structure: Employ clear delimiters to separate different parts of your prompt. XML-style tags (e.g., `<context>`, `<task>`) or Markdown headings are effective." | = G2 | [Measured] |
| G8 | (c)/(h) | "Control output verbosity: By default, Gemini 3 models provide direct and efficient answers. If you need a more conversational or detailed response, you must explicitly request it in your instructions." | = G2 | [Measured] |
| G9 | (c) | "<constraints>- Verbosity: [Specify Low/Medium/High]- Tone: [Specify Formal/Casual/Technical]</constraints>" | = G2 | [Measured] |
| G10 | (c) | "Summarize this text in one sentence" / "The list should have 5 items" | = G2 | [Measured] |
| G11 | (d) | "An effective and efficient way to customize model behavior is to provide it with clear and specific instructions." | = G2 | [Measured] |
| G12 | (d) | "Be precise and direct: State your goal clearly and concisely. Avoid unnecessary or overly persuasive language." | = G2 | [Measured] |
| G13 | (d) | "Specify any constraints on reading the prompt or generating a response." / "You can tell the model what to do and not to do." | = G2 | [Measured] |
| G14 | (d) | "You can include instructions and information in a prompt that the model needs to solve a problem, instead of assuming that the model has all of the required information." | = G2 | [Measured] |
| G15 | (e) | "Structure for long contexts: When providing large amounts of context (e.g., documents, code), supply all the context first. Place your specific instructions or questions at the very end of the prompt." | = G2 | [Measured] |
| G16 | (e) | "The order of the content in the prompt can sometimes affect the response. Try changing the content order and see how that affects the response." | = G2 | [Measured] |
| G17 | (e) | "Anchor context: After a large block of data, use a clear transition phrase to bridge the context and your query, such as 'Based on the information above...'" | = G2 | [Measured] |
| G18 | (b) | "Few-shot prompts are often used to regulate the formatting, phrasing, scoping, or general patterning of model responses." / "We recommend to always include few-shot examples in your prompts." | = G2 | [Measured] |
| G19 | (f) | "Context files, which use the default name `GEMINI.md`, are a powerful feature for providing instructional context to the Gemini model." / "You can use these files to give project-specific instructions, define a persona, or provide coding style guides." | https://geminicli.com/docs/cli/gemini-md/ | [Measured] |
| G20 | (f) | "It loads various context files from several locations, concatenates the contents of all found files, and sends them to the model." / "**Location:** `~/.gemini/GEMINI.md` (in your user home directory). **Scope:** Provides default instructions for all your projects." | = G19 | [Measured] |
| G21 | (f) | "You can break down large `GEMINI.md` files into smaller, more manageable components by importing content from other files using the `@file.md` syntax." | = G19 | [Measured] |
| G22 | (f) | "While `GEMINI.md` is the default filename, you can configure this in your `settings.json` file." / "To specify a different name or a list of names, use the `context.fileName` property." | = G19 | [Measured] |
| G23 | (a)-(e) | Vertex AI page (prompt design strategies): body could not be retrieved; section titles only. | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/prompts/prompt-design-strategies | [Unknown] |

## 4. Where they agree

- Explicit, specific instructions: A14, O6, G11, G12.
- Markdown and XML as valid prompt delimiters: A3, O4, O5, O21, G7.
- Long context first, question at the end: A18, G15; OpenAI at both ends (O23).
- Recent models are terse by default; conciseness or detail must be requested explicitly: A12, A13, O10, O11, G8.
- Contradictory instructions resolve arbitrarily or by recency: A27, O16, O26.
- The role lives in the system / developer / system_instruction layer: A1, O2, O3, G1, G2.
- Instruction files: plain markdown, concatenated, closest one wins: A23, O28, O29, G20; `@file` imports in Claude and Gemini (A29, G21).
- Short instruction files: A24 (< 200 lines), O30, G21.
- Examples regulate the format: A5, O2, G18.

## 5. Where they differ or contradict each other

- Positive versus negative framing: Anthropic asks for what to do (A6); Google allows "what to do and not to do" (G13).
- Mirroring the prompt's format in the output: only Anthropic documents this (A7); OpenAI recommends heavily markdown prompts (O21) while GPT-5 emits no markdown by default (O11).
- Verbosity mechanism: a three-level API parameter in OpenAI (O9, O18, O19); a constraints block in the prompt in Google (G9); prompt only in Anthropic (A13).
- Placement of instructions in long context: after the data (A18, G15) versus at both the start and the end (O23).
- Lists versus prose: Anthropic suppresses lists and bold text in its example (A9, A10); Google asks for numbered lists and bold text (G5); OpenAI asks for "semantically correct" markdown (O12).
- Where the project file lands in context: Anthropic states it (user message after the system prompt, no guarantee, A30); OpenAI and Google do not document it.

## 6. What none of them says

- Nothing on reading level or non-technical audience; the only documented adaptation is a text-to-speech case (A22); "communication style" (O3) and "Tone" (G9) are fields with no guidance.
- No numeric length cap for responses to humans (G10 are toy examples; O18 describes, does not prescribe).
- No "answer first" rule for the OUTPUT: the ordering guidance is about the prompt (A18, G2, G15, O23); summaries are post hoc and agentic (A19, O17).
- No guidance on when a table, prose, or a list is better for comprehension.
- Only OpenAI documents format drift in long conversations (O13).
- The CLAUDE.md / AGENTS.md / GEMINI.md files do not cover output style for humans (A28, O28, G19).

## 7. Verification notes

- The old docs.claude.com URLs redirect to platform.claude.com; three pages collapse into one (A1).
- platform.openai.com redirects to developers.openai.com; cookbook.openai.com to developers.openai.com/cookbook; Codex's AGENTS.md guide to learn.chatgpt.com.
- The Vertex AI page returned no body (G23).
- The Anthropic page read names "Claude Opus 5" and "Claude Fable 5.1"; the OpenAI one, "gpt-6-astra". They are quoted as read, without independent verification of those names.
- No table row rests on search snippets; all are [Measured] except G23.
