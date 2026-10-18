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

    --no-core         the pre-core format (what the kit installed before the
                      subagent core existed): same render, no core section.

Uninstall candidates (--candidates-dir DIR): for each agent, every text an
install of this kit may have written, one file each under DIR/<agent file
name>/: today's render, today's source in the pre-core format, and, when the
kit is a git checkout, each committed version of the agent (last 50 commits
of the agent, its contract, this renderer or CONTEXT-PACK.md) rendered by the
renderer, contract and core committed with it. Prints {"history": bool}.

Usage:
    lib/render_agents.py --target pi <agent.md> [--tools-default EXPR] [--core-source FILE] [--no-core]
    lib/render_agents.py --target claude <agent.md> [--tools-default EXPR] [--core-source FILE] [--no-core]
    lib/render_agents.py --target T <agent.md>... --candidates-dir DIR [--kit-root DIR] [--tools-default EXPR]

Output goes to stdout, or to --out <file>.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import types
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
KIT_ROOT = Path(__file__).resolve().parent.parent.parent
CORE_SOURCE = KIT_ROOT / "CONTEXT-PACK.md"
RENDERER_REL = "03-tools/lib/render_agents.py"
CORE_REL = "CONTEXT-PACK.md"
HISTORY_LIMIT = 50
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


def core_section(core: str | None) -> str:
    return f"{CORE_HEADING}\n\n{core}\n" if core is not None else ""


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


def render_claude(text: str, tools_default: str, core: str | None) -> str:
    """core=None is the pre-core format: the source with only the token rendered."""
    rendered = text.replace(TOOLS_DEFAULT_TOKEN, tools_default)
    if core is None:
        return rendered
    return rendered.rstrip("\n") + "\n\n" + core_section(core)


def render_pi(text: str, contract: dict, core: str | None) -> str:
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
    if core is not None:
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
           contract: dict | None = None, core: str | None = None, with_core: bool = True) -> str:
    """with_core=False renders the pre-core format (uninstall still recognises it)."""
    text = agent_path.read_text(encoding="utf-8")
    if not with_core:
        core = None
    elif core is None:
        core = load_core()
    if target == "claude":
        return render_claude(text, tools_default, core)
    return render_pi(text.replace(TOOLS_DEFAULT_TOKEN, tools_default),
                     contract if contract is not None else load_contract(agent_path, None), core)


def _git(kit_root: Path, *args: str, data: bytes | None = None) -> bytes | None:
    try:
        proc = subprocess.run(["git", "-C", str(kit_root), *args], input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _blobs(kit_root: Path, names: list[str]) -> dict[str, str]:
    """<rev>:<path> -> text for every name that exists, in one cat-file call."""
    out = _git(kit_root, "cat-file", "--batch", data="".join(n + "\n" for n in names).encode())
    found: dict[str, str] = {}
    if out is None:
        return found
    pos = 0
    for name in names:
        eol = out.index(b"\n", pos)
        header = out[pos:eol].split()
        pos = eol + 1
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            found[name] = out[pos:pos + size].decode("utf-8", errors="replace")
            pos += size + 1
        elif len(header) == 3:  # a tree or other object: skip its payload
            pos += int(header[2]) + 1
    return found


_PAST_RENDERERS: dict[str, types.ModuleType] = {}


def _past_renderer(source: str) -> types.ModuleType | None:
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if key not in _PAST_RENDERERS:
        module = types.ModuleType("render_agents_past")
        module.__dict__.update(__file__=str(KIT_ROOT / RENDERER_REL), __name__="render_agents_past")
        try:
            exec(compile(source, f"render_agents.py@{key[:12]}", "exec"), module.__dict__)
        except Exception:  # an old renderer that does not even load renders nothing
            return None
        _PAST_RENDERERS[key] = module
    return _PAST_RENDERERS[key]


def _render_with(source: str, name: str, agent: str, contract: str | None, pack: str | None,
                 target: str, tools_default: str) -> str | None:
    """Runs a committed renderer on committed inputs, exactly as its install did."""
    module = _past_renderer(source)
    if module is None or not hasattr(module, "main"):
        return None
    with tempfile.TemporaryDirectory(prefix="render-past-") as tmp:
        work = Path(tmp)
        agent_path = work / name
        agent_path.write_text(agent, encoding="utf-8")
        if contract is not None:
            contract_path_for(agent_path).write_text(contract, encoding="utf-8")
        argv = [str(agent_path), "--target", target, "--tools-default", tools_default, "--out", str(work / "out.md")]
        if pack is not None:
            (work / CORE_REL).write_text(pack, encoding="utf-8")
            argv += ["--core-source", str(work / CORE_REL)]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = module.main(argv)
        except (Exception, SystemExit):
            return None
        out = work / "out.md"
        return out.read_text(encoding="utf-8") if code in (0, None) and out.is_file() else None


def is_git_checkout(kit_root: Path = KIT_ROOT) -> bool:
    return _git(Path(kit_root), "rev-parse", "--show-prefix") is not None


def _touching(kit_root: Path, pathspecs: list[str]) -> dict[str, list[str]]:
    """file (relative to the kit root) -> the commits that touched it, newest
    first, read with one `git log` over every pathspec."""
    out = _git(kit_root, "log", "--relative", "--format=%x00%H", "--name-only", "--", *pathspecs)
    commits: dict[str, list[str]] = {}
    current = None
    for line in (out or b"").decode("utf-8", errors="replace").splitlines():
        if line.startswith("\0"):
            current = line[1:]
        elif line and current:
            commits.setdefault(line, []).append(current)
    return commits


def _rel(agent_path: Path, kit_root: Path) -> str | None:
    try:
        return Path(agent_path).resolve().relative_to(kit_root).as_posix()
    except ValueError:
        return None


def past_renders(agent_path: Path, target: str, tools_default: str, kit_root: Path = KIT_ROOT,
                 limit: int = HISTORY_LIMIT, touching: dict[str, list[str]] | None = None) -> list[str]:
    """What each committed version of this kit installed for the agent: the
    agent, contract, renderer and core read from the same commit, rendered by
    that commit's renderer. Revisions: the last <limit> commits touching each
    of the four. Empty when the kit is not a git checkout."""
    kit_root = Path(kit_root).resolve()
    rel_agent = _rel(agent_path, kit_root)
    prefix_out = _git(kit_root, "rev-parse", "--show-prefix")
    if rel_agent is None or prefix_out is None:
        return []
    prefix = prefix_out.decode("utf-8").strip()
    rel_contract = contract_path_for(Path(rel_agent)).as_posix()
    paths = (rel_agent, rel_contract, RENDERER_REL, CORE_REL)
    if touching is None:
        touching = _touching(kit_root, list(paths))
    revs: set[str] = set()
    for rel in paths:
        revs.update(touching.get(rel, [])[:limit])
    names = [f"{rev}:{prefix}{rel}" for rev in sorted(revs) for rel in paths]
    blobs = _blobs(kit_root, names)

    seen: set[tuple] = set()
    renders: list[str] = []
    for rev in sorted(revs):
        agent, contract, renderer, pack = (blobs.get(f"{rev}:{prefix}{rel}") for rel in paths)
        if agent is None or renderer is None:
            continue
        pack = pack if "--core-source" in renderer else None
        state = (agent, contract, renderer, pack)
        if state in seen:
            continue
        seen.add(state)
        text = _render_with(renderer, Path(rel_agent).name, agent, contract, pack, target, tools_default)
        if text is not None and text not in renders:
            renders.append(text)
    return renders


def write_candidates(agents: list[Path], target: str, tools_default: str, core: str, out_dir: Path,
                     kit_root: Path = KIT_ROOT) -> bool:
    """Writes every uninstall candidate of each agent under out_dir/<name>/.
    Returns whether the git history was available."""
    history = is_git_checkout(kit_root)
    touching = None
    if history:
        root = Path(kit_root).resolve()
        rels = [r for r in (_rel(a, root) for a in agents) if r is not None]
        specs = sorted({Path(r).parent.as_posix() for r in rels}) + [RENDERER_REL, CORE_REL]
        touching = _touching(root, specs)
    for agent_path in agents:
        contract = load_contract(agent_path, None)
        texts = [render(agent_path, target, tools_default, contract, core),
                 render(agent_path, target, tools_default, contract, with_core=False)]
        if history:
            texts += past_renders(agent_path, target, tools_default, kit_root, touching=touching)
        folder = out_dir / agent_path.name
        folder.mkdir(parents=True, exist_ok=True)
        unique = list(dict.fromkeys(texts))
        for index, text in enumerate(unique):
            (folder / f"{index:03d}.md").write_text(text, encoding="utf-8")
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", nargs="+", help="path to 01-roles/agents/generic-<role>.md")
    parser.add_argument("--target", choices=("claude", "pi"), required=True)
    parser.add_argument("--tools-default", default=DEFAULT_TOOLS_EXPR)
    parser.add_argument("--contract", default=None, help="contract JSON, defaults to <agent>.contract.json")
    parser.add_argument("--core-source", default=str(CORE_SOURCE),
                        help="file holding the subagent-core section, defaults to the kit's CONTEXT-PACK.md")
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-core", action="store_true", help="render the pre-core format (no subagent core)")
    parser.add_argument("--candidates-dir", default=None,
                        help="write every uninstall candidate of each agent under DIR/<agent file name>/")
    parser.add_argument("--kit-root", default=str(KIT_ROOT), help="git checkout whose history is read")
    args = parser.parse_args(argv)

    if args.candidates_dir:
        try:
            history = write_candidates([Path(a) for a in args.agent], args.target, args.tools_default,
                                       load_core(Path(args.core_source)), Path(args.candidates_dir),
                                       Path(args.kit_root))
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps({"history": history}))
        return 0
    if len(args.agent) != 1:
        parser.error("one agent at a time, unless --candidates-dir")
    agent_path = Path(args.agent[0])
    contract = load_contract(agent_path, args.contract)
    try:
        core = None if args.no_core else load_core(Path(args.core_source))
        text = render(agent_path, args.target, args.tools_default, contract, core, with_core=not args.no_core)
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
