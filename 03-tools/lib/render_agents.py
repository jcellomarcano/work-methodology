#!/usr/bin/env python3
"""Renders a kit role (01-roles/agents/generic-*.md plus its .contract.json)
into the agent format a runtime understands.

Both targets append the subagent core: the block of the kit's CONTEXT-PACK.md
between <!-- subagent-core:start --> and <!-- subagent-core:end -->, byte for
byte, under a "## Kit core" heading. It is the one source of the cold-start
rules every role shares (evidence tags, JSON output, budget deny, build files,
owner gates, no subagents), so no body copies them by hand.

    --target claude   the Claude Code file with __TOOLS_DEFAULT__ replaced and
                      the core appended. install-claude.sh renders with it.
    --target pi       pi frontmatter (name, description, tools as a YAML list
                      of lowercase built-ins), the body, the core and a
                      rendered contract section with what only the contract
                      knows (tool-call cap, forbidden and writable paths,
                      handoff targets): the kit's pi extension enforces only
                      part of it, so it also travels as prose. The last line
                      is a role marker (<!-- metodo-role: <name> -->) that
                      hooks/pi/metodo-hooks.ts reads to find the contract.

Usage:
    lib/render_agents.py --target pi <agent.md> [--tools-default EXPR] [--core-source FILE]
    lib/render_agents.py --target claude <agent.md> [--tools-default EXPR] [--core-source FILE]

Output goes to stdout, or to --out <file>.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_DEFAULT_TOKEN = "__TOOLS_DEFAULT__"
DEFAULT_TOOLS_EXPR = "$HOME/metodologia-de-trabajo/03-tools"

# pi built-ins are lowercase and there is no Glob: find covers it.
PI_TOOL_MAP = {
    "Read": "read",
    "Grep": "grep",
    "Glob": "find",
    "Edit": "edit",
    "Write": "write",
    "Bash": "bash",
    "LS": "ls",
}
MCP_PREFIX = "mcp__metodo__"
# hooks/pi/metodo-hooks.ts reads this line out of the system prompt and only
# accepts [A-Za-z0-9_-] names: a role name is a contract file stem.
ROLE_MARKER = "<!-- metodo-role: {name} -->"
CORE_SOURCE = Path(__file__).resolve().parent.parent.parent / "CONTEXT-PACK.md"
CORE_START = "<!-- subagent-core:start -->"
CORE_END = "<!-- subagent-core:end -->"
CORE_HEADING = "## Kit core"


def split_frontmatter(text: str) -> tuple[str, str]:
    """Returns (frontmatter, body). Raises when the file has no frontmatter:
    a role without one is a broken role, not a role with defaults."""
    if not text.startswith("---\n"):
        raise ValueError("the agent file does not open with a --- frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise ValueError("the agent file's frontmatter is not closed")
    return text[4:end + 1], text[end + 5:]


def frontmatter_field(frontmatter: str, key: str) -> str:
    """Reads one top-level scalar field. Enough for name/description/tools:
    the kit writes them on a single line and no role needs a YAML parser."""
    prefix = key + ":"
    for line in frontmatter.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def map_tools(claude_tools: list[str]) -> tuple[list[str], list[str]]:
    """Returns (pi tool names, dropped Claude names). MCP tools keep their
    full name: with toolPrefix "mcp" the adapter registers them as
    mcp__metodo__<tool>, so the name in the body is the real one."""
    kept: list[str] = []
    dropped: list[str] = []
    for tool in claude_tools:
        if tool.startswith(MCP_PREFIX):
            kept.append(tool)
        elif tool in PI_TOOL_MAP:
            kept.append(PI_TOOL_MAP[tool])
        else:
            dropped.append(tool)
    return kept, dropped


def load_core(source: Path = CORE_SOURCE) -> str:
    """The subagent core: the text between the two markers, without the
    newlines around it. A missing file or marker is an error, never an
    agent rendered without its cold-start rules."""
    if not source.is_file():
        raise ValueError(f"subagent core source not found: {source}")
    text = source.read_text(encoding="utf-8")
    start, end = text.find(CORE_START), text.find(CORE_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{source} has no {CORE_START} ... {CORE_END} section")
    core = text[start + len(CORE_START):end].strip("\n")
    if not core:
        raise ValueError(f"{source}: the subagent core section is empty")
    return core


def core_section(core: str) -> str:
    return f"{CORE_HEADING}\n\n{core}\n"


def contract_section(contract: dict) -> str:
    """What only the contract knows and the pi harness cannot enforce: the
    tool-call cap, forbidden and writable paths, handoff targets. The shared
    rules (budget deny, build files, output FAIL, delivery) live in the core,
    and the output_write call with its schema lives in the body: none is
    repeated here."""
    cap = contract.get("max_tool_calls")
    forbidden = list(contract.get("forbidden_paths") or [])
    may_write = [g for g in (contract.get("may_write") or []) if "<" not in g]
    targets = list(contract.get("handoff_targets") or [])
    writes_handoff = any(t.endswith("handoff_write") for t in (contract.get("tools") or []))

    lines = ["## Contract (partly enforced by the extension on this runtime)", ""]
    lines.append("On this runtime the kit's extension enforces only part of this contract mechanically. "
                 "Every rule below is yours to keep.")
    lines.append("")
    if cap:
        lines.append(f"- Budget: at most {cap} tool calls.")
    lines.append("- Forbidden paths: " + (", ".join(f"`{p}`" for p in forbidden) if forbidden else "none of its own") + ".")
    if may_write:
        lines.append("- May write: " + ", ".join(f"`{g}`" for g in may_write) + ", and nothing else.")
    else:
        lines.append("- May write: nothing outside the round directory this role is given.")
    if writes_handoff:
        handoff_to = ", ".join(f"`{t}`" for t in targets) if targets else "nobody (you are a terminal role)"
        lines.append(f"- Hand off to: {handoff_to}.")
    return "\n".join(lines) + "\n"


def render_claude(text: str, tools_default: str, core: str) -> str:
    return text.replace(TOOLS_DEFAULT_TOKEN, tools_default).rstrip("\n") + "\n\n" + core_section(core)


def render_pi(text: str, contract: dict, core: str) -> str:
    frontmatter, body = split_frontmatter(text)
    name = frontmatter_field(frontmatter, "name")
    description = frontmatter_field(frontmatter, "description")
    raw_tools = [t.strip() for t in frontmatter_field(frontmatter, "tools").split(",") if t.strip()]
    tools, dropped = map_tools(raw_tools or list(contract.get("tools") or []))

    out = ["---", f"name: {name}", f"description: {description}", "tools:", '  - "*": false']
    out += [f"  - {t}" for t in tools]
    if dropped:
        out.append("  # dropped, no pi equivalent: " + ", ".join(dropped))
    out.append("---")
    out.append("")
    body = body.lstrip("\n")
    out.append(body.rstrip("\n"))
    out.append("")
    out.append(core_section(core))
    out.append(contract_section(contract))
    if name:
        out.append(ROLE_MARKER.format(name=name) + "\n")
    return "\n".join(out)


def contract_path_for(agent_path: Path) -> Path:
    return agent_path.with_name(agent_path.name[: -len(".md")] + ".contract.json")


def load_contract(agent_path: Path, explicit: str | None) -> dict:
    path = Path(explicit) if explicit else contract_path_for(agent_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render(agent_path: Path, target: str, tools_default: str = DEFAULT_TOOLS_EXPR,
           contract: dict | None = None, core: str | None = None) -> str:
    text = agent_path.read_text(encoding="utf-8")
    core = load_core() if core is None else core
    if target == "claude":
        return render_claude(text, tools_default, core)
    return render_pi(text.replace(TOOLS_DEFAULT_TOKEN, tools_default),
                     contract if contract is not None else load_contract(agent_path, None), core)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", help="path to 01-roles/agents/generic-<role>.md")
    parser.add_argument("--target", choices=("claude", "pi"), required=True)
    parser.add_argument("--tools-default", default=DEFAULT_TOOLS_EXPR)
    parser.add_argument("--contract", default=None, help="contract JSON, defaults to <agent>.contract.json")
    parser.add_argument("--core-source", default=str(CORE_SOURCE),
                        help="file holding the subagent-core section, defaults to the kit's CONTEXT-PACK.md")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    agent_path = Path(args.agent)
    contract = load_contract(agent_path, args.contract)
    try:
        text = render(agent_path, args.target, args.tools_default, contract, load_core(Path(args.core_source)))
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "agent": str(agent_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
