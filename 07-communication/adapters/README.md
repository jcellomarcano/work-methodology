# Adapters per provider

The block is one (`../identidad.es.md` / `../identity.en.md`); the adapter is the thin wrapper each provider
needs. Differences documented per provider from its official guide (read, not measured by this kit), with the
quote id in `../sources/proveedores.md`:

| Aspect | Claude | GPT / Codex | Gemini |
|---|---|---|---|
| Where the block goes in the API | `system` parameter (A1, A30) | `developer` message, Identity section (O1, O2, O3) | `system_instruction` (G1, G2) |
| Project file | `CLAUDE.md`, imported with `@` (A23, A29) | `AGENTS.md`, no import syntax: the block is pasted in and regenerated with the command below (O27, O29) | `GEMINI.md`, imported with `@` (G19, G21) |
| Length control | prompt only; effort does not change length (A13) | `verbosity` parameter low/medium/high (O9, O18) plus in-prompt override (O10) | prompt-level constraint, `Verbosity: Low` (G9); direct by default (G8) |
| Default markdown | mirrors the prompt (A7) | none in the API (O11); adherence decays in long conversations (O13) | per instruction (G4, G5) |
| Delimiters | consistent XML (A3, A4) | markdown or XML, JSON worse (O21, O22) | XML or markdown (G7) |
| Positive or negative | say what to do (A6) | no rule; contradictions are costly (O16) | accepts both (G13) |
| File in context | user message after the system one, no guarantee (A30) | not documented | not documented |

What the three have in common, and why the block is vendor-agnostic: explicit, verifiable instructions (A14,
A26, O6, G11), no contradictions (A27, O16, O26), format requested in the positive, conciseness requested
explicitly (A12, A13, O10, G8), examples that fix the format (A5, O2, G18) and a short instructions file (A24,
O30, G21).

Local open models (Ollama, Llama, Qwen, Mistral): not investigated this round; the block should work as the
`SYSTEM` of a Modelfile, but that stays `[Desconocido]` until measured.

## Regenerating `AGENTS.md` when the block changes

From the kit root, the file is the header plus the English block, with no manual editing:

```
{ cat 07-communication/adapters/AGENTS.head.md; echo; echo "<identity>"; cat 07-communication/identity.en.md; echo "</identity>"; } > 07-communication/adapters/AGENTS.md
```
