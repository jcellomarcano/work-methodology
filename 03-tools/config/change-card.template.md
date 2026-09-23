## Change Card

**Why**: <text explaining the reason> [Medido]
**For what**: <one of the properties declared in config/project.json:property_order (example: Data integrity, State correctness, Identity/uniqueness, Auditability, Recoverability, Security, Performance, UX)> [Medido]
**What it risks**: <text, or "none" if there is genuinely nothing to protect> [Probado]
**When**: <text> [Medido]
**How**: <text> [Probado]
**How far**: <text> [Asumido]
**How we'll know**: <text> [Probado]
**Invariant**: <<invariant_prefix>-NN[,<invariant_prefix>-NN...] (prefix from config/project.json, INV by default) or an extra_invariant_tokens from config/project.json; "n/a" ONLY if For what AND What it risks are Auditability/UX/"none">
**Ticket**: <DEV-123 or "no ticket">
