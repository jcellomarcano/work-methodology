# Fixed-template brief (between agents, terse English)

```
ROLE: <generic-cartographer | generic-proposer | generic-challenger | ...>
OBJECTIVE: <one verifiable sentence>
INPUTS: <paths only; never pasted content>
  - /path/to/repo (read-only unless ROLE may_write)
  - /path/to/round/NNN-previous-handoff.json
CONSTRAINTS: <what must not be touched; read scope; forbidden_paths from contract>
OUTPUT: <schema path, e.g. 03-tools/schemas/findings.schema.json>; JSON only, no fences, no prose
STOP: <the condition that ends the task, e.g. "every .kt under src/main listed" or "N tool calls">
BUDGET: max_context_tokens=<from contract>; max_tool_calls=<N>
EVIDENCE: cite the code STATEMENT at file:line@sha, never a comment; tag every claim
          Medido|Probado|Inferido|Asumido|Desconocido; set truncated=true if the budget ends first
```

Rules: the brief doesn't restate the schema, it references it. The agent doesn't reword the brief. Zero
findings is a legitimate output. The orchestrator saves the brief as `NNN-brief-<role>.md` in the round's
directory.
