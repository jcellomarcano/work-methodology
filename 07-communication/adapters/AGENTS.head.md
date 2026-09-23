# Communication with people (OpenAI Codex / GPT adapter · v2)

How you talk to humans is defined by the block below; how you talk to other agents, by
`00-principles/agent-protocol.md`. Codex concatenates AGENTS.md files from the root down and the closest
one wins (O28, O29), so this file adds nothing that the block already covers. The block is a generated copy of
`../identity.en.md` (AGENTS.md has no import syntax, O27); regenerate it with the command in `README.md`.

GPT-specific rules, documented in the official guides (`../sources/proveedores.md`):
- API: set `verbosity: low` as the global default (O9, O18, O19) and override in-prompt only for the
  technical layer when the person asks for detail (O10).
- GPT-5 emits no markdown by default (O11): the block asks for minimal markdown explicitly, and the
  instruction is repeated every 3-5 turns in long conversations (O13).
- Contradictions cost reasoning tokens (O16) and the last instruction wins (O26).
- XML tags around the block improve adherence (O14, O21).
- Check: `python3 03-tools/lib/output_lint.py <reply.md> --type <type> --lang <es|en|ca|de> --audience public` from the kit root.
