# metodo kit on agy

This repo runs the working-methodology kit. The kit's skills and roles were written for several runtimes, so
read their tool names this way here:

- `mcp__metodo__<tool>` is the kit's MCP server: call it with `call_mcp_tool`, server `metodo_metodo`, tool `<tool>`.
- A role `generic-<name>` is a subagent of this plugin: delegate with `invoke_subagent` and that name as `TypeName`.
- `Read`, `Edit`, `Write` and `Bash` are `read_file`, `edit_file`, `write_file` and `run_command`.

The plugin's hooks enforce the kit's guards. A deny names the rule it applies: report it in your output and let
the owner decide. Do not work around it, and never edit `.agents/` or `.claude/` from a subagent.
