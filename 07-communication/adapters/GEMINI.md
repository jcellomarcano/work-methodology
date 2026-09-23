# Communication with people (Gemini CLI adapter · v2)

How you talk to humans is defined by the block imported below; how you talk to other agents,
`00-principles/agent-protocol.md`. Gemini CLI concatenates the `GEMINI.md` files it finds (G20) and
supports importing files with `@` (G21).

@../identidad.es.md

Gemini-specific rules, measured against the official guide (`../sources/proveedores.md`):
- API: the block goes in `system_instruction` (G1, G2), with `<constraints>Verbosity: Low</constraints>` as
  a constraints block (G9); detail is requested explicitly, because the default is direct (G8).
- Format: XML or markdown headings as delimiters, used consistently (G7); this adapter uses `##` headings.
- Long context first and the question at the end (G15), with a bridge sentence ("Based on the information
  above...") before the question (G17).
- Examples set the format (G18): one example per reply type lives in `../templates.md`.
- Check: `python3 03-tools/lib/output_lint.py <reply.md> --type <type> --lang <es|en|ca|de> --audience public` from the kit root.
