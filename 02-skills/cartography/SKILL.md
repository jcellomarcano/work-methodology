---
name: cartography
description: Maps the repo as it stands (modules, LOC, hotspots, boundaries, merge collisions) via cartography.sh; the model reads reuse and merge candidates. Use it to open an audit or size a module before touching it.
version: 1.0.0
triggers:
  - repo cartography
  - repo snapshot
  - how big is this module
  - what collides with the integration branch
  - boundary map
allowed-tools: [Read, mcp__metodo__cartography]
---

**IRON LAW**: the `cartography` tool measures, you interpret. No number the script did not print goes into the table.

## Input

`<repo>`: path to the repo to photograph.

## Steps

1. `mcp__metodo__cartography` on `<repo>`; read `shape_summary`, `dep_summary`, `hotspots`, and `merge_conflict_simulation` exactly as the tool returns them.
2. If the response arrives with `truncated_inline: true`, read the `.md` that `out_md` points to; do not call the tool again.
3. If you are feeding this to `generic-cartographer`, pass it the `out/<repo_sha>/cartography.json` path as the brief's `EVIDENCE`; the agent does not run the cartography again on its own.

## What the model may add

Interpretation of reuse, obsolescence, and merge candidates from the hotspots and boundaries already measured. It never invents an LOC or a boundary the script did not report.

## Output

Module / LOC / hotspot / boundaries table, plus the `claims` if `generic-cartographer` is invoked on this output.

## Escalate to the owner

- `dep_boundaries` flags a new cycle, distinct from the ones already known and documented in `config/project.json`.
- The merge simulation collides on one of the shared build files declared in `config/project.json` (`shared_build_files`).
