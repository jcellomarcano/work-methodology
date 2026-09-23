# Round context pack (`round/000-context.md`, cap 40 lines)

Filled in by the orchestrator before the first brief. It's the only thing every agent in the round gets as
its first INPUT; the rest is read on demand within the brief's `scope`. Paths, never pasted content.

```
ROUND: <id, e.g. tc2p-R2>
REPO: <path> @ <base sha>            # the sha comes from `git rev-parse`, never typed by hand
BRANCH: <working branch>             # and its base (develop, or the tip of the gstack pile)
CHANGE CARD: round/001-change-card.md # validated: verdict PASS, routing <opus|sonnet>
INVARIANTS: INV-xx, INV-yy           # the ones the card declares; text in invariants.md
CRITICAL PATHS: <config/project.json paths the change touches, or "none">
RISK: <exempt|low|medium|high> (<reasons from rdd_risk.py>)   # written by receipt_start, not editable
LENSES: <receipt lenses, or "none">
RECEIPT: out/rdd/<tree_sha>.receipt.json
EVIDENCE (precomputed, read-only):
  - out/<sha>/cartography.json      # module map
  - round/002-comments.json         # comment_gate.py
  - <other script JSON>
MOULD: <file or module being copied, e.g. payment/vendor-a/...>
VOCABULARY: <5 fixed project terms: gateway, session, kernel, master, PoS>       # PoS = point of sale, a domain term, not a company
NOT IN SCOPE: <what the card leaves out, one line>
BUDGET PER ROLE: cartographer 40k · proposer 60k · adversaries 60k · judge 30k · verifier 40k · reviewers 15k
ROUND DIR: round/                   # numbered files NNN-<role>-<subject>.{md,json}
```

Rules: one line per field; if a field doesn't fit on a line, it's a path to a file. The pack isn't edited
during the round; a change to the tree or the card opens a new receipt (`rdd_receipt.py` applies it).
