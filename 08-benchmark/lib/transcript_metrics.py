#!/usr/bin/env python3
"""Per-session metrics from Claude Code transcripts (~/.claude/projects/**/*.jsonl).

Deterministic: same input, same bytes out (sorted keys, no run timestamps).
Private: no prompt or reply text leaves this script, only lengths and counts.

Usage:
  transcript_metrics.py --root ~/.claude/projects [--project SUBSTR] --out sessions.json
      [--contracts 01-roles/agents] [--routing-log <tools>/out/runs/routing.jsonl]

The context-method metrics (METRICS.md M100-M107) sit under `context_metrics`
in each session; every other field keeps its pre-M100 meaning and value.

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
import re
import sys
from collections import Counter, defaultdict

# 1.1.0: additive, `context_metrics` (M100-M107) per session.
SCHEMA_VERSION = "1.1.0"

# Context-method metrics (METRICS.md M100-M107).
DEFAULT_CONTRACTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "01-roles" / "agents"
REPORT_CAP_TOKENS = 2000            # D9: subagent report cap, ~8,000 chars
SUBAGENT_TOOLS = {"Agent", "Task"}
READ_TOOLS = {"Read"}
# Results of these tools are file content: a METODO-WARN line there is quoted text, not a warn shown.
FILE_CONTENT_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
EDIT_FAMILY = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
RECALL_SEARCH = {"mem_search", "mem_context"}
WARN_RE = re.compile(r"^[ \t]*(METODO-WARN ([a-z0-9][a-z0-9-]*):[^\n]*)", re.MULTILINE)
HASH_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
RECALL_ID_RES = (re.compile(r"#(\d+)(?!\d)"), re.compile(r"\"id\"\s*:\s*\"?(\d+)"),
                 re.compile(r"\bID:\s*(\d+)"))
RECALL_TOPIC_RES = (re.compile(r"\"topic_key\"\s*:\s*\"([^\"\s]{3,200})\""),
                    re.compile(r"\btopic(?:_key)?:\s*([^\s,;)\"]{3,200})"))
RECALL_TITLE_RES = (re.compile(r"\"title\"\s*:\s*\"((?:[^\"\\]|\\.){8,200})\""),
                    re.compile(r"^[ \t]*(?:\*\*)?Title(?:\*\*)?:[ \t]*(.{8,200}?)[ \t]*$", re.MULTILINE),
                    re.compile(r"^[ \t]*(?:\[\d+\][ \t]*)?#\d+[ \t]*(?:\[[^\]\n]*\]|\([^)\n]*\))?[ \t]*"
                               r"(?:[\u2014\u2013:-][ \t]*)?(.{8,200}?)[ \t]*$", re.MULTILINE))

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
        self.first = None   # context of the first request (M104)

    def add(self, msg_id: str, usage: dict):
        if msg_id in self.seen:
            return False
        self.seen.add(msg_id)
        t = _usage_tokens(usage)
        for k in self.sum:
            self.sum[k] += t[k]
        self.requests += 1
        context = t["input"] + t["cache_write"] + t["cache_read"]
        if self.first is None:
            self.first = context
        self.peak = max(self.peak, context)
        return True


def _tok(chars: int) -> int:
    """ceil(chars / 4): the kit's token proxy."""
    return -(-chars // 4)


def _result_text(content) -> str:
    """Model-visible text of a tool_result content (string or blocks; images add nothing)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "".join(parts)
    return _as_text(content)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, dict):
        for k in sorted(value):
            if k != "command":
                yield from _strings(value[k])


def _warn_kinds(text: str) -> list[str]:
    """Kinds of the distinct METODO-WARN lines in one record, sorted."""
    lines = {m.group(1).rstrip(): m.group(2) for m in WARN_RE.finditer(text)}
    return [lines[k] for k in sorted(lines)]


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

    # context-method collections (M100-M107); kept in memory only, never emitted
    seq = 0
    calls = {}          # tool_use id -> {name, input, msg, seq}
    call_list = []      # [(seq, id, name, msg)] in record order
    results = []        # [(seq, tool_use_id, text)], first result per id
    seen_results = set()
    reads = []          # [(path, offset, limit)]
    launches = []       # [(tool_use_id, subagent_type)] for Agent/Task
    material = []       # [(seq, text, name, input)] assistant text and tool inputs
    warns = []          # [(seq, kind, trigger tool_use id or None)]

    for r in records:
        seq += 1
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
                    material.append((seq, block.get("text") or "", None, None))
                elif btype == "tool_use":
                    bid = block.get("id") or ""
                    if bid in seen_tool_ids:
                        continue
                    seen_tool_ids.add(bid)
                    name = block.get("name") or ""
                    tool_calls[name] += 1
                    inp = block.get("input") or {}
                    calls[bid] = {"name": name, "input": inp, "msg": msg_id, "seq": seq}
                    call_list.append((seq, bid, name, msg_id))
                    material.append((seq, json.dumps(inp, ensure_ascii=False, sort_keys=True), name, inp))
                    if isinstance(inp, dict):
                        if name in READ_TOOLS and (inp.get("file_path") or inp.get("path")):
                            reads.append((str(inp.get("file_path") or inp.get("path")),
                                          inp.get("offset"), inp.get("limit")))
                        if name in SUBAGENT_TOOLS:
                            launches.append((bid, inp.get("subagent_type") or "unknown"))
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
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tid = block.get("tool_use_id") or ""
                    if tid and tid in seen_results:
                        continue
                    seen_results.add(tid)
                    text = _result_text(block.get("content"))
                    results.append((seq, tid, text))
                    if (calls.get(tid) or {}).get("name") not in FILE_CONTENT_TOOLS:
                        warns.extend((seq, kind, tid or None) for kind in _warn_kinds(text))
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
                trigger = att.get("toolUseID") or att.get("toolUseId") or None
                warns.extend((seq, kind, trigger) for kind in _warn_kinds("\n".join(_strings(att))))
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
        "_ctx": {"calls": calls, "call_list": call_list, "results": results, "reads": reads,
                 "launches": launches, "material": material, "warns": warns},
    }


def _iso(ts):
    if ts is None:
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


# ------------------------------------------------- context-method metrics (M100-M107)

def load_contract_caps(contracts_dir) -> dict:
    """{role: max_context_tokens} from <dir>/*.contract.json; unreadable files are skipped."""
    caps = {}
    d = pathlib.Path(contracts_dir)
    if not d.is_dir():
        return caps
    for f in sorted(d.glob("*.contract.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        cap = data.get("max_context_tokens")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
            caps[str(data.get("agent") or f.name[:-len(".contract.json")])] = cap
    return dict(sorted(caps.items()))


_DEFAULT_CAPS = None


def _default_caps() -> dict:
    global _DEFAULT_CAPS
    if _DEFAULT_CAPS is None:
        _DEFAULT_CAPS = load_contract_caps(DEFAULT_CONTRACTS_DIR)
    return _DEFAULT_CAPS


def load_routing_log(path) -> dict:
    """{inputs_hash: line} for router log lines with status ok; the last line per hash wins.
    Raises OSError when the file cannot be read."""
    out = {}
    for raw in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (isinstance(line, dict) and line.get("status") == "ok" and isinstance(line.get("inputs_hash"), str)
                and isinstance(line.get("roster"), list)):
            out[line["inputs_hash"]] = line
    return out


def _ratio(num, den):
    return round(num / den, 6) if den else None


def _family(name: str) -> str:
    return "edit" if name in EDIT_FAMILY else name


def _recall_keys(text: str):
    ids = {m.group(1) for rx in RECALL_ID_RES for m in rx.finditer(text)}
    topics = {m.group(1) for rx in RECALL_TOPIC_RES for m in rx.finditer(text)}
    titles = {m.group(1).strip().lower() for rx in RECALL_TITLE_RES for m in rx.finditer(text)}
    return ids, topics, {t for t in titles if len(t) >= 8}


def _recall_used(after, ids, topics, titles) -> bool:
    for _seq, text, name, inp in after:
        if name and _engram_op(name) and isinstance(inp, dict):
            if any(str(inp.get(k)) in ids for k in ("id", "observation_id") if inp.get(k) is not None):
                return True
        if any(re.search("#" + i + r"(?!\d)", text) for i in ids):
            return True
        if any(t in text for t in topics):
            return True
        low = text.lower()
        if any(t in low for t in titles):
            return True
    return False


def _context_metrics(main: dict, subs: list, caps: dict, routing) -> dict:
    c = main["_ctx"]
    calls, results = c["calls"], c["results"]
    result_by_id = {tid: (seq, text) for seq, tid, text in results if tid}

    # M100 per-role peak vs cap
    peaks = defaultdict(list)
    for s in subs:
        peaks[s["role"]].append(s["peak"])
    per_role = {}
    for role in sorted(peaks):
        cap, pmax = caps.get(role), max(peaks[role])
        per_role[role] = {"runs": len(peaks[role]), "cap": cap, "peak_max": pmax,
                          "over_cap_runs": sum(1 for p in peaks[role] if p > cap) if cap else None,
                          "peak_to_cap_max": _ratio(pmax, cap) if cap else None}

    # M101 tool-output share
    by_tool = Counter()
    for _seq, tid, text in results:
        by_tool[(calls.get(tid) or {}).get("name") or "unknown"] += _tok(len(text))
    t = main["tokens"]
    fresh = t.sum["input"] + t.sum["cache_write"]
    tool_tokens = sum(by_tool.values())

    # M102 re-read ratio
    reads = c["reads"]
    paths = {p for p, _o, _l in reads}
    ranges = {(p, json.dumps(o), json.dumps(l)) for p, o, l in reads}
    all_reads = reads + [r for s in subs for r in s["reads"]]
    all_paths = {p for p, _o, _l in all_reads}

    # M103 subagent report size
    sizes, by_role_rep = [], {}
    for bid, role in c["launches"]:
        if bid not in result_by_id:
            continue
        n = _tok(len(result_by_id[bid][1]))
        sizes.append(n)
        r = by_role_rep.setdefault(role, {"reports": 0, "over_cap": 0, "max_tokens_est": 0})
        r["reports"] += 1
        r["over_cap"] += int(n > REPORT_CAP_TOKENS)
        r["max_tokens_est"] = max(r["max_tokens_est"], n)

    # M104 startup load
    startup = {}
    for s in subs:
        values = startup.setdefault(s["role"], [])
        if s["first"] is not None:
            values.append(s["first"])

    # M105 recall-used rate
    recalls = used = empty = result_chars = 0
    for _seq, bid, name, _msg in c["call_list"]:
        if _engram_op(name) != "recall" or name.split("__")[-1] not in RECALL_SEARCH:
            continue
        recalls += 1
        rseq, text = result_by_id.get(bid, (calls[bid]["seq"], ""))
        result_chars += len(text)
        ids, topics, titles = _recall_keys(text)
        if not (ids or topics or titles):
            empty += 1
        elif _recall_used([m for m in c["material"] if m[0] > rseq], ids, topics, titles):
            used += 1

    # M106 delegation ratio vs router
    launched = Counter(role for _bid, role in c["launches"])
    asked_sub, asked_main, matched = Counter(), Counter(), []
    if routing is not None:
        seen = set()
        for _seq, _tid, text in results:
            seen.update(HASH_RE.findall(text))
        matched = sorted(h for h in seen if h in routing)
        for h in matched:
            for e in routing[h]["roster"]:
                if isinstance(e, dict) and e.get("launch") == "run" and e.get("role"):
                    if e.get("delegate") == "subagent":
                        asked_sub[e["role"]] += 1
                    elif e.get("delegate") == "main":
                        asked_main[e["role"]] += 1
    roles = sorted(set(launched) | set(asked_sub) | set(asked_main))
    delegated = sum(min(launched[r], asked_sub[r]) for r in roles)
    requested = sum(asked_sub.values())

    # M107 warn act rate
    call_list = c["call_list"]
    kinds = {}
    no_trigger = no_next = 0
    for wseq, kind, tid in c["warns"]:
        k = kinds.setdefault(kind, {"fires": 0, "judged": 0, "acted": 0})
        k["fires"] += 1
        trig = calls.get(tid) if tid in calls else None
        if trig is None:
            before = [x for x in call_list if x[0] < wseq]
            trig = calls[before[-1][1]] if before else None
        if trig is None:
            no_trigger += 1
            continue
        nxt = next((x for x in call_list if x[0] > wseq and x[3] != trig["msg"]), None)
        if nxt is None:
            no_next += 1
            continue
        k["judged"] += 1
        k["acted"] += int(_family(nxt[2]) != _family(trig["name"]))
    judged = sum(k["judged"] for k in kinds.values())
    acted = sum(k["acted"] for k in kinds.values())

    return {
        "per_role_peak": {"id": "M100", "label": "Measured", "by_role": per_role},
        "tool_output_share": {"id": "M101", "label": "Inferred", "tool_output_tokens_est": tool_tokens,
                              "fresh_input_tokens": fresh, "share": _ratio(tool_tokens, fresh),
                              "by_tool": dict(sorted(by_tool.items()))},
        "reread": {"id": "M102", "label": "Measured", "reads": len(reads), "distinct_paths": len(paths),
                   "rereads": len(reads) - len(paths), "ratio": _ratio(len(reads) - len(paths), len(reads)),
                   "rereads_same_range": len(reads) - len(ranges),
                   "ratio_same_range": _ratio(len(reads) - len(ranges), len(reads)),
                   "all_contexts": {"reads": len(all_reads), "distinct_paths": len(all_paths),
                                    "rereads": len(all_reads) - len(all_paths),
                                    "ratio": _ratio(len(all_reads) - len(all_paths), len(all_reads))}},
        "subagent_reports": {"id": "M103", "label": "Inferred", "cap_tokens": REPORT_CAP_TOKENS,
                             "reports": len(sizes), "over_cap": sum(1 for n in sizes if n > REPORT_CAP_TOKENS),
                             "max_tokens_est": max(sizes, default=None), "tokens_est": sizes,
                             "by_role": dict(sorted(by_role_rep.items()))},
        "startup_load": {"id": "M104", "label": "Measured", "main_tokens": t.first,
                         "subagents_by_role": dict(sorted(startup.items()))},
        "recall_used": {"id": "M105", "label": "Inferred", "recalls": recalls, "used": used, "empty": empty,
                        "rate": _ratio(used, recalls), "result_chars": result_chars},
        "delegation": {"id": "M106", "label": "Inferred", "status": "not-run" if routing is None else "ok",
                       "decisions_matched": len(matched), "requested_subagent": requested,
                       "requested_main": sum(asked_main.values()), "launched": sum(launched.values()),
                       "delegated": delegated, "ratio": _ratio(delegated, requested),
                       "unrequested_launches": None if routing is None else
                       sum(max(0, launched[r] - asked_sub[r]) for r in roles),
                       "by_role": {r: {"requested_subagent": asked_sub[r], "requested_main": asked_main[r],
                                       "launched": launched[r]} for r in roles}},
        "warn_act": {"id": "M107", "label": "Inferred", "fires": len(c["warns"]), "judged": judged,
                     "acted": acted, "rate": _ratio(acted, judged), "no_trigger": no_trigger, "no_next": no_next,
                     "by_kind": dict(sorted(kinds.items()))},
    }


def analyze_session(path: pathlib.Path, contracts: dict | None = None, routing: dict | None = None) -> dict:
    """contracts: {role: max_context_tokens} (default: the kit's 01-roles/agents);
    routing: load_routing_log() output, or None when no routing log was given."""
    main = _analyze_records(iter_records(path))
    session_id = path.stem
    sub_dir = path.parent / session_id / "subagents"
    sub_tokens = _Tokens()
    sub_by_type = Counter()
    sub_by_model = Counter()
    sub_count = 0
    subs = []           # per run, for M100/M102/M104
    launch_roles = dict(main["_ctx"]["launches"])
    if sub_dir.is_dir():
        for agent_file in sorted(sub_dir.glob("agent-*.jsonl")):
            sub_count += 1
            meta_path = agent_file.with_suffix(".meta.json")
            agent_type = "unknown"
            tool_use_id = None
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    agent_type = meta.get("agentType") or "unknown"
                    tool_use_id = meta.get("toolUseId")
                except (json.JSONDecodeError, OSError):
                    pass
            sub_by_type[agent_type] += 1
            sub = _analyze_records(iter_records(agent_file))
            role = agent_type if agent_type != "unknown" else launch_roles.get(tool_use_id) or "unknown"
            subs.append({"role": role, "peak": sub["tokens"].peak, "first": sub["tokens"].first,
                         "reads": sub["_ctx"]["reads"]})
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
        "context_metrics": _context_metrics(main, subs, _default_caps() if contracts is None else contracts, routing),
    }


def main_session_files(root: pathlib.Path, project_filter: str | None):
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if project_filter and project_filter not in project_dir.name:
            continue
        for f in sorted(project_dir.glob("*.jsonl")):
            yield f


def run(root: pathlib.Path, project_filter: str | None, contracts_dir=None, routing_log=None) -> dict:
    caps = load_contract_caps(contracts_dir) if contracts_dir is not None else _default_caps()
    routing = load_routing_log(routing_log) if routing_log is not None else None
    sessions = []
    failures = []
    for f in main_session_files(root, project_filter):
        try:
            sessions.append(analyze_session(f, contracts=caps, routing=routing))
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
    ap.add_argument("--contracts", default=str(DEFAULT_CONTRACTS_DIR),
                    help="directory of role *.contract.json (max_context_tokens, M100)")
    ap.add_argument("--routing-log", default=None,
                    help="router routing.jsonl; enables the delegation ratio (M106)")
    args = ap.parse_args(argv)
    if args.routing_log is not None and not pathlib.Path(args.routing_log).expanduser().is_file():
        ap.error(f"--routing-log: not a readable file: {args.routing_log}")
    payload = run(pathlib.Path(args.root).expanduser(), args.project,
                  contracts_dir=pathlib.Path(args.contracts).expanduser(),
                  routing_log=pathlib.Path(args.routing_log).expanduser() if args.routing_log else None)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": len(payload["sessions"]), "failures": len(payload["failures"]),
                      "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
