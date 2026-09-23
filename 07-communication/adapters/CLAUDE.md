# Communication with people (Claude Code adapter · v2)

How you talk to humans is defined by the block imported below; how you talk to other agents,
`00-principles/agent-protocol.md`. This file does not repeat the block: it imports it.

@../identidad.es.md

Claude-specific rules, measured against the official guide (`../sources/proveedores.md`):
- This file arrives as a user message after the system prompt, with no strict guarantee (A30): in the API
  the block goes in the `system` parameter, not here.
- Conciseness: requested explicitly, because effort does not change the visible length (A13). By default,
  reply length is proportional to the question; the technical layer grows on demand.
- Markdown from the prompt is mirrored in the output (A7): this adapter uses the minimum.
- After using tools, a brief summary of the work done (A19), in the "status" shape from `../templates.md`.
- Check: `python3 03-tools/lib/output_lint.py <reply.md> --type <type> --lang <es|en|ca|de> --audience public` from the kit root.
