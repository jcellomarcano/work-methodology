#!/usr/bin/env python3
"""Renders a kit role (01-roles/agents/generic-*.md plus its .contract.json)
into the agent format a runtime understands.

Two targets:

    --target claude   the current Claude Code file, byte for byte, with only
                      __TOOLS_DEFAULT__ replaced. Nothing else is touched, so
                      install-claude.sh can adopt this later without any diff.
    --target pi       pi frontmatter (name, description, tools as a YAML list
                      of lowercase built-ins) plus the original body and a
                      rendered contract section. pi has no per-subagent hooks,
                      so the contract that the Claude harness enforces with
                      hooks travels as prose there.

Usage:
    lib/render_agents.py --target pi <agent.md> [--tools-default EXPR]
    lib/render_agents.py --target claude <agent.md> [--tools-default EXPR]

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


def contract_section(contract: dict) -> str:
    """The part of the contract the Claude harness enforces with hooks and pi
    cannot: budget, forbidden paths, output schema and handoff."""
    cap = contract.get("max_tool_calls")
    forbidden = list(contract.get("forbidden_paths") or [])
    may_write = [g for g in (contract.get("may_write") or []) if "<" not in g]
    targets = list(contract.get("handoff_targets") or [])
    writes_output = any(t.endswith("output_write") for t in (contract.get("tools") or []))
    writes_handoff = any(t.endswith("handoff_write") for t in (contract.get("tools") or []))

    lines = ["## Contract (enforced by prose on this runtime)", ""]
    lines.append("This runtime has no per-subagent hooks, so nothing stops you mechanically. "
                 "Every rule below is yours to keep.")
    lines.append("")
    if cap:
        lines.append(f"- Budget: at most {cap} tool calls. On reaching it, stop and emit your JSON "
                     "with `truncated: true` and `not_covered` filled in.")
    lines.append("- Forbidden paths: " + (", ".join(f"`{p}`" for p in forbidden) if forbidden else "none of its own")
                 + ". The project's shared build files and `**/.claude/**` are always off-limits too.")
    if may_write:
        lines.append("- May write: " + ", ".join(f"`{g}`" for g in may_write) + ", and nothing else.")
    else:
        lines.append("- May write: nothing outside the round directory this role is given.")
    if writes_output:
        lines.append("- Output: write your document with `mcp__metodo__output_write` under the schema your "
                     "protocol names. A FAIL validation writes nothing, so fix the document and write again.")
    if writes_handoff:
        handoff_to = ", ".join(f"`{t}`" for t in targets) if targets else "nobody (you are a terminal role)"
        lines.append(f"- Handoff: close with `mcp__metodo__handoff_write` toward {handoff_to}.")
    lines.append("- Delivery (push, PR, merge, tag) and receipt start/finalize/acknowledge belong to the owner. "
                 "Report them in your output; never run them.")
    return "\n".join(lines) + "\n"


def render_claude(text: str, tools_default: str) -> str:
    return text.replace(TOOLS_DEFAULT_TOKEN, tools_default)


def render_pi(text: str, contract: dict) -> str:
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
    out.append(contract_section(contract))
    return "\n".join(out)


def contract_path_for(agent_path: Path) -> Path:
    return agent_path.with_name(agent_path.name[: -len(".md")] + ".contract.json")


def load_contract(agent_path: Path, explicit: str | None) -> dict:
    path = Path(explicit) if explicit else contract_path_for(agent_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render(agent_path: Path, target: str, tools_default: str = DEFAULT_TOOLS_EXPR,
           contract: dict | None = None) -> str:
    text = agent_path.read_text(encoding="utf-8")
    if target == "claude":
        return render_claude(text, tools_default)
    return render_pi(render_claude(text, tools_default), contract if contract is not None else load_contract(agent_path, None))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", help="path to 01-roles/agents/generic-<role>.md")
    parser.add_argument("--target", choices=("claude", "pi"), required=True)
    parser.add_argument("--tools-default", default=DEFAULT_TOOLS_EXPR)
    parser.add_argument("--contract", default=None, help="contract JSON, defaults to <agent>.contract.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    agent_path = Path(args.agent)
    contract = load_contract(agent_path, args.contract)
    try:
        text = render(agent_path, args.target, args.tools_default, contract)
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
