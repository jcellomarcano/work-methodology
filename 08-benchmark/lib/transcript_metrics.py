#!/usr/bin/env python3
"""Per-session metrics from Claude Code transcripts (~/.claude/projects/**/*.jsonl).

Deterministic: same input, same bytes out (sorted keys, no run timestamps).
Private: no prompt or reply text leaves this script, only lengths and counts.

Usage:
  transcript_metrics.py --root ~/.claude/projects [--project SUBSTR] --out sessions.json

Facts about the format this relies on (verified 2026-10-13, Claude Code 2.1.x):
- one assistant record per content block; records of one API message share
  message.id and message.usage, so usage is counted once per message.id;
- subagent transcripts live in <session_id>/subagents/agent-<id>.jsonl with a
  sibling agent-<id>.meta.json {agentType, toolUseId, model};
- compaction is a system record with subtype compact_boundary;
- cost-state records (not in every session) carry totalCostUSD.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

SCHEMA_VERSION = "1.0.0"

# Skills the kit installs into a target repo (03-tools/bin/install-claude.sh).
KIT_SKILLS = {
    "cartography", "adversarial-round", "verify-per-commit", "change-card",
    "repo-metrics", "real-environment-minutes", "pr-message", "clean-pass",
    "benchmark-release", "necessary-comment", "human-reply", "human-review",
    "review-comment", "receipt-review", "post-review-comment", "init-kit",
}
# The Spanish names the same skills had before the English port: transcripts
# recorded earlier still carry them, so they keep counting as kit skills.
KIT_SKILLS |= {
    "cartografia", "ronda-adversarial-dos", "verify-por-commit", "ficha-de-cambio",
    "metricas-del-repo", "acta-de-entorno-real", "mensaje-de-pr", "pase-de-limpieza",
    "comentario-necesario", "respuesta-humana", "revision-humana",
    "comentario-de-review", "revision-con-recibo", "publicar-comentario-de-review", "iniciar-kit",
}
ENGRAM_RECALL = {"mem_search", "mem_context", "mem_get_observation", "mem_review", "mem_current_project"}
ENGRAM_SAVE = {"mem_save", "mem_save_prompt", "mem_session_summary", "mem_update",
               "mem_capture_passive", "mem_session_start", "mem_session_end"}


def _ts(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds(a, b):
    return round((b - a).total_seconds(), 3)


def iter_records(path: pathlib.Path):
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _usage_tokens(usage: dict) -> dict:
    return {
        "input": int(usage.get("input_tokens") or 0),
        "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
    }


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _mcp_server(tool_name: str) -> str | None:
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__")
    server = parts[1] if len(parts) > 1 else ""
    if "engram" in server:
        return "engram"
    return server


def _engram_op(tool_name: str) -> str | None:
    if _mcp_server(tool_name) != "engram":
        return None
    op = tool_name.split("__")[-1]
    if op in ENGRAM_RECALL:
        return "recall"
    if op in ENGRAM_SAVE:
        return "save"
    return "other"


class _Tokens:
    def __init__(self):
        self.seen = set()
        self.sum = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        self.requests = 0
        self.peak = 0

    def add(self, msg_id: str, usage: dict):
        if msg_id in self.seen:
            return False
        self.seen.add(msg_id)
        t = _usage_tokens(usage)
        for k in self.sum:
            self.sum[k] += t[k]
        self.requests += 1
        self.peak = max(self.peak, t["input"] + t["cache_write"] + t["cache_read"])
        return True


def _analyze_records(records) -> dict:
    """Shared walker for a main or subagent transcript."""
    tokens = _Tokens()
    models = Counter()
    efforts = Counter()
    tool_calls = Counter()
    seen_tool_ids = set()
    agent_types = Counter()
    agent_prompt_chars = []
    skills = Counter()
    kit_markers = {}       # strong marker -> first timestamp seen (hooks, metodo MCP, generic-* subagents)
    weak_markers = {}      # skill names that the kit installs but user-level skills may share
    engram = Counter()

    def mark(store, key, when):
        iso = _iso(when) if when else None
        if key not in store or (iso and (store[key] is None or iso < store[key])):
            store[key] = iso
    hooks = Counter()
    hook_metodo = 0
    compactions = []
    api_errors = 0
    turn_durations = []
    cost_usd = None
    perm_modes = Counter()
    output_style = None
    versions = Counter()
    branches = Counter()
    cwd = None
    first_ts = last_ts = None
    model_switches = 0
    last_model = None

    # ordered events for reply/latency computation
    events = []  # (kind, ts, payload)

    for r in records:
        rtype = r.get("type")
        ts = _ts(r.get("timestamp"))
        if ts:
            first_ts = ts if first_ts is None or ts < first_ts else first_ts
            last_ts = ts if last_ts is None or ts > last_ts else last_ts
        if r.get("version"):
            versions[r["version"]] += 1
        if r.get("gitBranch"):
            branches[r["gitBranch"]] += 1
        if cwd is None and r.get("cwd"):
            cwd = r["cwd"]

        if rtype == "assistant":
            msg = r.get("message") or {}
            model = msg.get("model") or ""
            msg_id = msg.get("id") or r.get("requestId") or r.get("uuid") or ""
            if model and model != "<synthetic>" and msg_id:
                if tokens.add(msg_id, msg.get("usage") or {}):
                    models[model] += 1
                    if r.get("effort"):
                        efforts[r["effort"]] += 1
                    if last_model and model != last_model:
                        model_switches += 1
                    last_model = model
            if ts:
                events.append(("assistant", ts, msg_id))
            for block in msg.get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    events.append(("text", ts, (msg_id, len(block.get("text") or ""))))
                elif btype == "tool_use":
                    bid = block.get("id") or ""
                    if bid in seen_tool_ids:
                        continue
                    seen_tool_ids.add(bid)
                    name = block.get("name") or ""
                    tool_calls[name] += 1
                    inp = block.get("input") or {}
                    if name == "Agent":
                        st = inp.get("subagent_type") or "unknown"
                        agent_types[st] += 1
                        agent_prompt_chars.append(len(inp.get("prompt") or ""))
                        if st.startswith("generic-"):
                            mark(kit_markers, f"subagent:{st}", ts)
                    elif name == "Skill":
                        sk = inp.get("skill") or ""
                        skills[sk] += 1
                        if sk in KIT_SKILLS:
                            mark(weak_markers, f"skill:{sk}", ts)
                    if name.startswith("mcp__metodo__"):
                        mark(kit_markers, "mcp:metodo", ts)
                    op = _engram_op(name)
                    if op:
                        engram[op] += 1
        elif rtype == "user":
            msg = r.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and not r.get("isMeta"):
                origin = (r.get("origin") or {}).get("kind")
                if origin in (None, "human"):
                    if "<command-name>" in content:
                        events.append(("slash", ts, len(content)))
                        for sk in KIT_SKILLS:
                            if f"<command-name>/{sk}</command-name>" in content:
                                mark(weak_markers, f"skill:{sk}", ts)
                    else:
                        events.append(("human", ts, len(content)))
                        if r.get("permissionMode"):
                            perm_modes[r["permissionMode"]] += 1
        elif rtype == "attachment":
            att = r.get("attachment") or {}
            atype = att.get("type") or ""
            if atype == "output_style":
                output_style = att.get("style")
            elif atype.startswith("hook_"):
                hooks[f"{att.get('hookEvent') or '?'}:{atype}"] += 1
                # A kit hook that really ran prints "[metodo] ..." on its output. The command
                # string alone (": metodo-hook; ...") is present even when the hook exits
                # silently because METODO_TOOLS points nowhere, so it is not evidence.
                output = "".join(_as_text(att.get(k)) for k in ("content", "stdout"))
                if "[metodo]" in output:
                    hook_metodo += 1
                    mark(kit_markers, "hook:metodo", ts)
        elif rtype == "system":
            sub = r.get("subtype")
            if sub == "compact_boundary":
                meta = r.get("compactMetadata") or {}
                compactions.append({"trigger": meta.get("trigger"),
                                    "pre": meta.get("preTokens"), "post": meta.get("postTokens")})
            elif sub == "api_error":
                api_errors += 1
            elif sub == "turn_duration" and r.get("durationMs") is not None:
                turn_durations.append(int(r["durationMs"]))
        elif rtype == "cost-state":
            if r.get("totalCostUSD") is not None:
                cost_usd = round(float(r["totalCostUSD"]), 6)

    # final replies, first-response latency and turn wall-clock
    human_idx = [i for i, e in enumerate(events) if e[0] == "human"]
    human_chars = [events[i][2] for i in human_idx]
    first_response = []
    turn_wall = []
    final_chars = []
    for n, i in enumerate(human_idx):
        end = human_idx[n + 1] if n + 1 < len(human_idx) else len(events)
        h_ts = events[i][1]
        span = events[i + 1:end]
        resp = next((e for e in span if e[0] == "assistant" and e[1] and h_ts), None)
        if resp:
            first_response.append(_seconds(h_ts, resp[1]))
        if n + 1 < len(human_idx) and h_ts and events[human_idx[n + 1]][1]:
            turn_wall.append(_seconds(h_ts, events[human_idx[n + 1]][1]))
        texts = [e for e in span if e[0] == "text"]
        if texts:
            last_id = texts[-1][2][0]
            final_chars.append(sum(c for e in texts for (mid, c) in [e[2]] if mid == last_id))

    return {
        "tokens": tokens,
        "models": dict(sorted(models.items())),
        "effort_levels": dict(sorted(efforts.items())),
        "tool_calls": dict(sorted(tool_calls.items())),
        "agent_types": dict(sorted(agent_types.items())),
        "agent_prompt_chars": agent_prompt_chars,
        "skills": dict(sorted(skills.items())),
        "kit_markers": kit_markers,
        "weak_markers": weak_markers,
        "engram": {"recall_calls": engram["recall"], "save_calls": engram["save"],
                   "other_calls": engram["other"]},
        "hooks": {"by_event": dict(sorted(hooks.items())), "metodo_runs": hook_metodo},
        "compactions": compactions,
        "api_errors": api_errors,
        "turn_durations_ms": turn_durations,
        "cost_usd": cost_usd,
        "permission_modes": dict(sorted(perm_modes.items())),
        "output_style": output_style,
        "versions": sorted(versions),
        "branches": sorted(branches),
        "cwd": cwd,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "model_switches": model_switches,
        "human_prompts": {"count": len(human_chars), "chars_total": sum(human_chars), "chars": human_chars},
        "slash_commands": sum(1 for e in events if e[0] == "slash"),
        "final_replies": {"count": len(final_chars), "chars_total": sum(final_chars), "chars": final_chars},
        "latency_s": {"first_response": first_response, "turn_wall_clock": turn_wall},
    }


def _iso(ts):
    if ts is None:
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def analyze_session(path: pathlib.Path) -> dict:
    main = _analyze_records(iter_records(path))
    session_id = path.stem
    sub_dir = path.parent / session_id / "subagents"
    sub_tokens = _Tokens()
    sub_by_type = Counter()
    sub_by_model = Counter()
    sub_count = 0
    if sub_dir.is_dir():
        for agent_file in sorted(sub_dir.glob("agent-*.jsonl")):
            sub_count += 1
            meta_path = agent_file.with_suffix(".meta.json")
            agent_type = "unknown"
            if meta_path.exists():
                try:
                    agent_type = json.loads(meta_path.read_text(encoding="utf-8")).get("agentType") or "unknown"
                except (json.JSONDecodeError, OSError):
                    pass
            sub_by_type[agent_type] += 1
            sub = _analyze_records(iter_records(agent_file))
            for k in sub_tokens.sum:
                sub_tokens.sum[k] += sub["tokens"].sum[k]
            sub_tokens.requests += sub["tokens"].requests
            sub_tokens.peak = max(sub_tokens.peak, sub["tokens"].peak)
            if sub["models"]:
                sub_by_model[max(sub["models"], key=lambda m: (sub["models"][m], m))] += 1
            if agent_type.startswith("generic-"):
                key = f"subagent:{agent_type}"
                first = _iso(sub["first_ts"])
                if key not in main["kit_markers"] or (first and (main["kit_markers"][key] is None or first < main["kit_markers"][key])):
                    main["kit_markers"][key] = first

    t = main["tokens"]
    total_in = t.sum["input"] + t.sum["cache_write"] + t.sum["cache_read"]
    cwd = main["cwd"] or ""
    project = pathlib.PurePosixPath(cwd).name if cwd else path.parent.name
    first, last = main["first_ts"], main["last_ts"]
    return {
        "session_id": session_id,
        "project": project,
        "project_dir": path.parent.name,
        "first_ts": _iso(first),
        "last_ts": _iso(last),
        "duration_s": _seconds(first, last) if first and last else None,
        "versions": main["versions"],
        "branches": main["branches"],
        "requests": t.requests,
        "tokens": {"main": dict(t.sum), "subagents": dict(sub_tokens.sum)},
        "peak_context_tokens": t.peak,
        "cache_hit_ratio": round(t.sum["cache_read"] / total_in, 6) if total_in else None,
        "models": main["models"],
        "model_switches": main["model_switches"],
        "effort_levels": main["effort_levels"],
        "tool_calls": main["tool_calls"],
        "mcp_servers": dict(sorted(Counter(
            s for name, n in main["tool_calls"].items() for s in [_mcp_server(name)] if s for _ in range(n)
        ).items())),
        "agent_tool_calls_by_type": main["agent_types"],
        "agent_prompt_chars": main["agent_prompt_chars"],
        "subagents": {"count": sub_count, "by_type": dict(sorted(sub_by_type.items())),
                      "by_model": dict(sorted(sub_by_model.items())), "requests": sub_tokens.requests,
                      "peak_context_tokens": sub_tokens.peak},
        "skills": main["skills"],
        "kit": {"uses_kit": bool(main["kit_markers"]),
                "markers": sorted(main["kit_markers"]),
                "marker_ts": dict(sorted(main["kit_markers"].items())),
                "first_marker_ts": min((v for v in main["kit_markers"].values() if v), default=None),
                "weak_markers": sorted(main["weak_markers"])},
        "engram": main["engram"],
        "hooks": main["hooks"],
        "compactions": main["compactions"],
        "api_errors": main["api_errors"],
        "turn_durations_ms": main["turn_durations_ms"],
        "cost_usd": main["cost_usd"],
        "permission_modes": main["permission_modes"],
        "output_style": main["output_style"],
        "human_prompts": main["human_prompts"],
        "slash_commands": main["slash_commands"],
        "final_replies": main["final_replies"],
        "latency_s": main["latency_s"],
    }


def main_session_files(root: pathlib.Path, project_filter: str | None):
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if project_filter and project_filter not in project_dir.name:
            continue
        for f in sorted(project_dir.glob("*.jsonl")):
            yield f


def run(root: pathlib.Path, project_filter: str | None) -> dict:
    sessions = []
    failures = []
    for f in main_session_files(root, project_filter):
        try:
            sessions.append(analyze_session(f))
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            failures.append({"file": f.name, "project_dir": f.parent.name, "error": repr(exc)[:200]})
    sessions.sort(key=lambda s: (s["project"], s["first_ts"] or "", s["session_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "root": root.name,
        "sessions": sessions,
        "failures": failures,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(pathlib.Path.home() / ".claude" / "projects"))
    ap.add_argument("--project", default=None, help="substring filter on the project directory name")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    payload = run(pathlib.Path(args.root).expanduser(), args.project)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": len(payload["sessions"]), "failures": len(payload["failures"]),
                      "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
