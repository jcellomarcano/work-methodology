# Fixed-template brief (between agents, terse English)

```
ROLE: <generic-proposer | generic-challenger | ...>
OBJECTIVE: <one verifiable sentence: an outcome, not an activity>
SPECS: odd/tasks/<feature>.md#S1, odd/tasks/<feature>.md#S3
ACCEPTANCE: <the exact command, test or file check that proves it>
INPUTS: <paths only, never pasted content>
SCOPE: <globs it may edit; read scope>
ALREADY READ: <path:lines the parent read, a few words on each>
CONSTRAINTS: <what stays untouched; contract forbidden_paths>
OUTPUT: <schema output_write validates>; JSON only, no prose
STOP: acceptance passes, budget deny, or a blocking unknown
BUDGET: max_context_tokens=60000 (roster entry, else contract); max_tool_calls=40
EVIDENCE: cite the code STATEMENT at file:line@sha, never a comment; tag every claim
          Measured|Tested|Inferred|Assumed|Unknown; truncated=true if the budget ends first
```

Rules: SPECS holds S# references only; the harness quotes each line from the file, the brief never
paraphrases it, and the report returns a verdict per S#. Schema by reference. Never reword the brief.
`lib/brief_check.py` checks it; save it as `NNN-brief-<role>.md` in the round's directory.
