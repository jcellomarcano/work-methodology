#!/usr/bin/env python3
"""Phase 1 baseline: before/after aggregation over the four extracts in data/.

Inputs (all optional; a missing one is reported as failed, never silently skipped):
  data/sessions.json  (transcript_metrics.py)   data/git.json     (git_metrics.py)
  data/engram.json    (engram_metrics.py)       data/kit.json     (kit_telemetry.py)

Outputs: <out-dir>/phase1-baseline.json and phase1-baseline.md. Every number carries
the label of its METRICS.md row (Measured / Inferred / Unknown) and the whole report
is deterministic: same inputs, same bytes.

Usage: phase1_report.py --data 08-benchmark/data --out-dir 08-benchmark/reports
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys
from collections import Counter

SCHEMA_VERSION = "1.0.0"
INPUTS = ("sessions", "git", "engram", "kit")

# Installer-file mtimes observed on 2026-10-13 (weak evidence, kept as a cross-check only).
INSTALLER_MTIME = {"project-a": "2026-09-23", "project-b": "2026-09-05",
                   "project-c": "2026-09-05", "project-d": "2026-09-30"}
# Engram project names that differ from the transcript project (cwd basename).
ENGRAM_ALIASES = {"project-b-private": "project-b"}

NOT_MEASURED = [
    ("M25", "Seeded-defect recall", "Unknown", "needs Phase 2 seeded tasks"),
    ("M26", "False findings rate", "Unknown", "needs a blind judge over Phase 2 runs"),
    ("M63", "Effort level per request", "Unknown", "present on a minority of transcript records only; reported as a share where present"),
    ("M64", "Router decisions logged", "Unknown", "model-tiers.json is read by no code; nothing is logged"),
    ("M83", "Transferable ways of working", "Assumed", "reviewer judgment, listed in the report prose"),
]


def _stat(values, label="Measured", digits=6):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "median": None, "mean": None, "sum": None, "label": label}
    return {"n": len(vals), "median": round(statistics.median(vals), digits),
            "mean": round(statistics.fmean(vals), digits), "sum": round(sum(vals), digits), "label": label}


def _main_in(s):
    t = s["tokens"]["main"]
    return t["input"] + t["cache_write"] + t["cache_read"]


def _main_total(s):
    return _main_in(s) + s["tokens"]["main"]["output"]


def _sub_total(s):
    return sum(s["tokens"]["subagents"].values())


def _share(s):
    sub, main = _sub_total(s), _main_total(s)
    return sub / (sub + main) if (sub + main) else None


def _median_or_none(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _ratio(num, den):
    return round(num / den, 6) if den else None


def group_metrics(sessions):
    """Aggregate one group of session records into labelled stats (METRICS.md ids)."""
    m = {
        "M01_input_tokens": _stat([_main_in(s) for s in sessions]),
        "M02_output_tokens": _stat([s["tokens"]["main"]["output"] for s in sessions]),
        "M03_cache_hit_ratio": _stat([s["cache_hit_ratio"] for s in sessions]),
        "M04_peak_context": _stat([s["peak_context_tokens"] for s in sessions]),
        "M05_compactions": _stat([len(s["compactions"]) for s in sessions]),
        "M07_subagent_token_share": _stat([_share(s) for s in sessions]),
        "M10_final_reply_chars": _stat([_median_or_none(s["final_replies"]["chars"]) for s in sessions]),
        "M15_human_prompt_chars": _stat([_median_or_none(s["human_prompts"]["chars"]) for s in sessions]),
        "M15_human_prompts": _stat([s["human_prompts"]["count"] for s in sessions]),
        "M11_reply_to_prompt_ratio": _stat([_ratio(s["final_replies"]["chars_total"], s["human_prompts"]["chars_total"]) for s in sessions]),
        "M12_first_response_s": _stat([_median_or_none(s["latency_s"]["first_response"]) for s in sessions]),
        "M13_turn_wall_clock_s": _stat([_median_or_none(s["latency_s"]["turn_wall_clock"]) for s in sessions]),
        "M14_tool_calls_per_turn": _stat([_ratio(sum(s["tool_calls"].values()), s["human_prompts"]["count"]) for s in sessions]),
        "M50_engram_save_calls": _stat([s["engram"]["save_calls"] for s in sessions]),
        "M51_engram_recall_calls": _stat([s["engram"]["recall_calls"] for s in sessions]),
        "M60_subagent_runs": _stat([s["subagents"]["count"] for s in sessions]),
        "M72_hook_metodo_runs": _stat([s["hooks"]["metodo_runs"] for s in sessions]),
        "cost_usd": _stat([s["cost_usd"] for s in sessions]),
        "duration_s": _stat([s["duration_s"] for s in sessions]),
    }
    models, efforts, agents, skills = Counter(), Counter(), Counter(), Counter()
    for s in sessions:
        models.update(s["models"])
        efforts.update(s["effort_levels"])
        agents.update(s["agent_tool_calls_by_type"])
        skills.update(s["skills"])
    m["M08_requests_by_model"] = {"value": dict(sorted(models.items())), "label": "Measured"}
    m["M63_effort_levels_where_present"] = {"value": dict(sorted(efforts.items())), "label": "Measured"}
    m["M60_agent_types"] = {"value": dict(sorted(agents.items())), "label": "Measured"}
    m["M80_skills_invoked"] = {"value": dict(sorted(skills.items())), "label": "Measured"}
    return m


def _marker_ts(s):
    """Timestamp of the earliest strong kit marker in a session; sessions are resumed for
    weeks, so the session start date says nothing about when the kit first ran in it."""
    return (s.get("kit") or {}).get("first_marker_ts")


def adoption(sessions):
    """Per project: timestamp of the earliest strong kit marker across its sessions (Inferred)."""
    out = {}
    for s in sorted(sessions, key=lambda x: (x["project"], x["first_ts"] or "", x["session_id"])):
        p = out.setdefault(s["project"], {"date": None, "ts": None, "first_kit_session": None, "first_marker": None,
                                          "label": "Inferred", "installer_file_mtime": INSTALLER_MTIME.get(s["project"]),
                                          "sessions": 0, "kit_sessions": 0})
        p["sessions"] += 1
        if s["kit"]["uses_kit"]:
            p["kit_sessions"] += 1
            mts = _marker_ts(s)
            if mts and (p["ts"] is None or mts < p["ts"]):
                p["ts"] = mts
                p["date"] = mts[:10]
                p["first_kit_session"] = s["session_id"]
                p["first_marker"] = min(s["kit"]["marker_ts"], key=lambda k: s["kit"]["marker_ts"][k] or "9")
    return dict(sorted(out.items()))


def split_groups(sessions, adopt):
    """before: ended before adoption; after_*: started at or after it; spanning: crosses it."""
    groups = {}
    for proj, a in adopt.items():
        rows = [s for s in sessions if s["project"] == proj]
        buckets = {"before": [], "after_kit": [], "after_no_kit": [], "spanning": [], "no_adoption": [], "undated": []}
        for s in rows:
            if a["ts"] is None:
                buckets["no_adoption"].append(s)
            elif not s["first_ts"] or not s["last_ts"]:
                buckets["undated"].append(s)
            elif s["last_ts"] < a["ts"]:
                buckets["before"].append(s)
            elif s["first_ts"] < a["ts"]:
                buckets["spanning"].append(s)
            elif s["kit"]["uses_kit"]:
                buckets["after_kit"].append(s)
            else:
                buckets["after_no_kit"].append(s)
        groups[proj] = {k: {"n": len(v), "metrics": group_metrics(v)} for k, v in buckets.items()}
    return groups


def monthly(sessions):
    """Per project and month of session start: a trend view that needs no boundary."""
    out = {}
    for s in sessions:
        if not s["first_ts"]:
            continue
        key = s["first_ts"][:7]
        rows = out.setdefault(s["project"], {}).setdefault(key, [])
        rows.append(s)
    result = {}
    for proj, months in sorted(out.items()):
        result[proj] = {}
        for month, rows in sorted(months.items()):
            result[proj][month] = {
                "n": len(rows),
                "kit_sessions": sum(1 for s in rows if s["kit"]["uses_kit"]),
                "M04_peak_context": _stat([s["peak_context_tokens"] for s in rows]),
                "M02_output_tokens": _stat([s["tokens"]["main"]["output"] for s in rows]),
                "M10_final_reply_chars": _stat([_median_or_none(s["final_replies"]["chars"]) for s in rows]),
                "M12_first_response_s": _stat([_median_or_none(s["latency_s"]["first_response"]) for s in rows]),
                "M07_subagent_token_share": _stat([_share(s) for s in rows]),
                "M60_subagent_runs": _stat([s["subagents"]["count"] for s in rows]),
                "M51_engram_recall_calls": _stat([s["engram"]["recall_calls"] for s in rows]),
            }
    return result


def context_cells(sessions):
    """S22: kit vs no-kit, with vs without subagents."""
    cells = {}
    for kit in ("kit", "no_kit"):
        for sub in ("with_subagents", "without_subagents"):
            rows = [s for s in sessions
                    if (s["kit"]["uses_kit"] == (kit == "kit")) and ((s["subagents"]["count"] > 0) == (sub == "with_subagents"))]
            total_in = sum(_main_in(s) for s in rows)
            comps = sum(len(s["compactions"]) for s in rows)
            dropped = [c["pre"] - c["post"] for s in rows for c in s["compactions"]
                       if c.get("pre") is not None and c.get("post") is not None]
            prompts = [c for s in rows for c in s["agent_prompt_chars"]]
            cells[f"{kit}|{sub}"] = {
                "n": len(rows),
                "M04_peak_context": _stat([s["peak_context_tokens"] for s in rows]),
                "M05_compactions": _stat([len(s["compactions"]) for s in rows]),
                "M66_compactions_per_1m_input": {"value": round(comps / (total_in / 1e6), 3) if total_in else None, "label": "Measured"},
                "M66_tokens_dropped_per_compaction": _stat(dropped),
                "M07_subagent_token_share": _stat([_share(s) for s in rows]),
                "M65_agent_prompt_chars": _stat(prompts),
                "M65_subagent_peak_context": _stat([s["subagents"]["peak_context_tokens"] for s in rows if s["subagents"]["count"]]),
                "M02_output_tokens": _stat([s["tokens"]["main"]["output"] for s in rows]),
            }
    return cells


def _git_side(commits, merges):
    non_merge = [c for c in commits if not c["is_merge"]]
    code = [c for c in non_merge if c["touches_code"]]
    return {
        "commits": len(non_merge),
        "insertions": sum(c["insertions"] for c in non_merge),
        "deletions": sum(c["deletions"] for c in non_merge),
        "conventional_rate": _ratio(sum(c["conventional"] for c in non_merge), len(non_merge)),
        "code_commits": len(code),
        "code_commits_with_tests_rate": _ratio(sum(c["touches_tests"] for c in code), len(code)),
        "merges": len(merges),
        "lead_time_days_median": _median_or_none([m["lead_time_days"] for m in merges]),
        "label": "Measured",
    }


def git_split(git, adopt):
    out = {}
    for repo in git.get("repos", []):
        date = (adopt.get(repo["name"]) or {}).get("date")
        if date:
            before = _git_side([c for c in repo["commits"] if c["date"] < date], [m for m in repo["merges"] if m["date"] < date])
            after = _git_side([c for c in repo["commits"] if c["date"] >= date], [m for m in repo["merges"] if m["date"] >= date])
        else:
            before, after = _git_side(repo["commits"], repo["merges"]), _git_side([], [])
        out[repo["name"]] = {"adoption_date": date, "before": before, "after": after,
                             "by_month": repo.get("by_month", {}), "head": repo.get("head")}
    return dict(sorted(out.items()))


def engram_join(engram, sessions):
    by_project = {}
    tx = {s["session_id"]: s for s in sessions}
    for name, p in engram.get("projects", {}).items():
        alias = ENGRAM_ALIASES.get(name, name)
        e_sessions = [x for x in engram.get("sessions", []) if x["project"] == name]
        joined = [x for x in e_sessions if x["session_id"] in tx]
        tx_rows = [s for s in sessions if s["project"] == alias]
        by_project[alias] = {
            "engram_project": name,
            "sessions": p["sessions"],
            "sessions_with_observations": p["sessions_with_observations"],
            "sessions_with_zero_observations": p["sessions"] - p["sessions_with_observations"],
            "observations": p["observations"],
            "by_type": p["by_type"],
            "with_topic_key": p["with_topic_key"],
            "upserted": p["upserted"],
            "first_session": p["first_session"],
            "joined_transcript_sessions": len(joined),
            "transcript_sessions_with_recall": sum(1 for s in tx_rows if s["engram"]["recall_calls"]),
            "transcript_sessions_with_save": sum(1 for s in tx_rows if s["engram"]["save_calls"]),
            "sessions_saving_without_recall": sum(1 for s in tx_rows if s["engram"]["save_calls"] and not s["engram"]["recall_calls"]),
            "recall_calls_total": sum(s["engram"]["recall_calls"] for s in tx_rows),
            "save_calls_total": sum(s["engram"]["save_calls"] for s in tx_rows),
            "label": "Measured (counts) / Inferred (join by session UUID)",
        }
    return dict(sorted(by_project.items()))


def kit_join(kit, sessions):
    tx_ids = {s["session_id"] for s in sessions}
    out = {}
    for inst in kit.get("instances", []):
        rules, budget = Counter(), Counter()
        for s in inst["sessions"]:
            rules.update(s["reply_lint_rule_hits"])
            for agent_type, kinds in s["budget_by_agent_type"].items():
                for kind, n in kinds.items():
                    budget[f"{agent_type}:{kind}"] += n
        r = inst["receipts"]
        out[inst["name"]] = {
            "ledger_sessions": inst["totals"]["sessions"],
            "ledger_lines": inst["totals"]["ledger_lines"],
            "first_started_at": inst["totals"]["first_started_at"],
            "last_started_at": inst["totals"]["last_started_at"],
            "joined_transcript_sessions": sum(1 for s in inst["sessions"] if s["session_id"] in tx_ids),
            "by_kind_decision": inst["totals"]["by_kind_decision"],
            "reply_lint_rule_hits": dict(sorted(rules.items())),
            "budget_events_by_agent": dict(sorted(budget.items())),
            "receipts": {k: r[k] for k in ("count", "voids", "by_state", "by_verdict", "by_risk", "captures_total")},
            "label": "Measured",
        }
    return dict(sorted(out.items()))


def load_inputs(data_dir: pathlib.Path):
    payloads, status = {}, {}
    for name in INPUTS:
        path = data_dir / f"{name}.json"
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
            status[name] = {"status": "ok", "tool_sha256": payloads[name].get("tool_sha256"),
                            "schema_version": payloads[name].get("schema_version")}
        except (OSError, json.JSONDecodeError) as exc:
            payloads[name] = None
            status[name] = {"status": "failed", "error": type(exc).__name__}
    return payloads, status


def build(data_dir: pathlib.Path) -> dict:
    payloads, status = load_inputs(data_dir)
    sessions = (payloads["sessions"] or {}).get("sessions", [])
    adopt = adoption(sessions) if payloads["sessions"] else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "inputs": status,
        "sessions_total": len(sessions),
        "adoption": adopt,
        "groups": split_groups(sessions, adopt) if payloads["sessions"] else {},
        "monthly": monthly(sessions) if payloads["sessions"] else {},
        "context_cells": context_cells(sessions) if payloads["sessions"] else {},
        "git": git_split(payloads["git"], adopt) if payloads["git"] else {},
        "engram": engram_join(payloads["engram"], sessions) if payloads["engram"] else {},
        "kit": kit_join(payloads["kit"], sessions) if payloads["kit"] else {},
        "not_measured": [{"id": i, "metric": m, "label": l, "reason": r} for i, m, l, r in NOT_MEASURED],
    }


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _cell(stat):
    if not isinstance(stat, dict) or "n" not in stat:
        return _fmt(stat.get("value")) if isinstance(stat, dict) else _fmt(stat)
    return "—" if stat["n"] == 0 else f"{_fmt(stat['median'])} (n={stat['n']})"


def render_md(report: dict) -> str:
    L = ["# Phase 1 baseline (retrospective)", "",
         "Retrospective, correlational evidence: task mix, model versions and the user's own practice drift over the period, so every delta below is a hypothesis for Phase 2, not a causal claim. Cells show the median across sessions with n; labels follow `METRICS.md`.", "",
         "## Inputs", "", "| File | Status | Tool sha256 |", "|---|---|---|"]
    for name, st in report["inputs"].items():
        L.append(f"| {name}.json | {st['status']} | {(st.get('tool_sha256') or '—')[:12]} |")
    L += ["", f"Sessions in scope: {report['sessions_total']}.", "", "## Adoption boundary per project", "",
          "| Project | Adoption (earliest strong kit marker) | First marker | Installer file mtime | Sessions | Kit sessions | Label |", "|---|---|---|---|---|---|---|"]
    for p, a in report["adoption"].items():
        L.append(f"| {p} | {a['date'] or 'none'} | {a['first_marker'] or '—'} | {a['installer_file_mtime'] or '—'} | {a['sessions']} | {a['kit_sessions']} | {a['label']} |")
    L += ["", "Strong markers: a kit hook run, a `mcp__metodo__*` call, a `generic-*` subagent. Kit-named skills are weak markers (user-level skills share the names) and never set the boundary. Sessions that were resumed across the boundary are reported as `spanning` and excluded from both sides."]
    for p, g in report["groups"].items():
        if g["before"]["n"] + g["after_kit"]["n"] + g["after_no_kit"]["n"] == 0:
            continue
        L += ["", f"## {p}: before vs after", "", f"Spanning sessions excluded: {g['spanning']['n']}.", "",
              f"| Metric | Before (n={g['before']['n']}) | After, kit (n={g['after_kit']['n']}) | After, no kit (n={g['after_no_kit']['n']}) | Label |", "|---|---|---|---|---|"]
        for key, stat in g["before"]["metrics"].items():
            if "n" not in stat:
                continue
            L.append(f"| {key} | {_cell(stat)} | {_cell(g['after_kit']['metrics'][key])} | {_cell(g['after_no_kit']['metrics'][key])} | {stat['label']} |")
        for key in ("M08_requests_by_model", "M63_effort_levels_where_present", "M60_agent_types", "M80_skills_invoked"):
            L.append(f"| {key} | {json.dumps(g['before']['metrics'][key]['value'])} | {json.dumps(g['after_kit']['metrics'][key]['value'])} | {json.dumps(g['after_no_kit']['metrics'][key]['value'])} | Measured |")
    for p, months in report["monthly"].items():
        if sum(m["n"] for m in months.values()) < 4:
            continue
        L += ["", f"## {p}: by month of session start (trend, no boundary)", "",
              "| Month | Sessions | Kit sessions | Peak context | Output tokens | Final reply chars | First response s | Subagent token share | Subagent runs | Engram recalls |", "|---|---|---|---|---|---|---|---|---|---|"]
        for month, m in months.items():
            L.append(f"| {month} | {m['n']} | {m['kit_sessions']} | {_cell(m['M04_peak_context'])} | {_cell(m['M02_output_tokens'])} | {_cell(m['M10_final_reply_chars'])} | {_cell(m['M12_first_response_s'])} | {_cell(m['M07_subagent_token_share'])} | {_cell(m['M60_subagent_runs'])} | {_cell(m['M51_engram_recall_calls'])} |")
        L += ["", "Label: Measured (medians per month)."]
    if report["context_cells"]:
        L += ["", "## Context under multi-agent work (S22)", "",
              "| Cell | n | Peak context | Compactions / session | Compactions per 1M input | Tokens dropped / compaction | Subagent token share | Agent prompt chars | Output tokens |", "|---|---|---|---|---|---|---|---|---|"]
        for cell, c in report["context_cells"].items():
            L.append(f"| {cell} | {c['n']} | {_cell(c['M04_peak_context'])} | {_cell(c['M05_compactions'])} | {_fmt(c['M66_compactions_per_1m_input']['value'])} | {_cell(c['M66_tokens_dropped_per_compaction'])} | {_cell(c['M07_subagent_token_share'])} | {_cell(c['M65_agent_prompt_chars'])} | {_cell(c['M02_output_tokens'])} |")
        L.append("")
        L.append("Label: Measured (all cells).")
    if report["git"]:
        L += ["", "## Delivery (git)", "",
              "| Repo | Side | Commits | Conventional rate | Code commits with tests | Merges | Lead time days (median) | Label |", "|---|---|---|---|---|---|---|---|"]
        for repo, g in report["git"].items():
            for side in ("before", "after"):
                s = g[side]
                L.append(f"| {repo} | {side} ({g['adoption_date'] or 'no adoption'}) | {s['commits']} | {_fmt(s['conventional_rate'])} | {_fmt(s['code_commits_with_tests_rate'])} | {s['merges']} | {_fmt(s['lead_time_days_median'])} | {s['label']} |")
    if report["engram"]:
        L += ["", "## Memory (Engram)", "",
              "| Project | Sessions | Zero observations | Observations | Joined to transcripts | Transcript sessions with recall | with save | save without recall | Label |", "|---|---|---|---|---|---|---|---|---|"]
        for p, e in report["engram"].items():
            L.append(f"| {p} | {e['sessions']} | {e['sessions_with_zero_observations']} | {e['observations']} | {e['joined_transcript_sessions']} | {e['transcript_sessions_with_recall']} | {e['transcript_sessions_with_save']} | {e['sessions_saving_without_recall']} | {e['label']} |")
    if report["kit"]:
        L += ["", "## Kit telemetry (hooks, gates, receipts)", ""]
        for name, k in report["kit"].items():
            L += [f"### {name}", "", f"Ledger sessions {k['ledger_sessions']} ({k['first_started_at']} → {k['last_started_at']}), lines {k['ledger_lines']}, joined to transcripts {k['joined_transcript_sessions']}. Label: {k['label']}.", "",
                  "| Kind:decision | Count |", "|---|---|"]
            for kd, n in sorted(k["by_kind_decision"].items(), key=lambda x: (-x[1], x[0])):
                L.append(f"| {kd} | {n} |")
            r = k["receipts"]
            L += ["", f"Receipts: {r['count']} (voids {r['voids']}), by verdict {json.dumps(r['by_verdict'])}, by state {json.dumps(r['by_state'])}, captures {r['captures_total']}.",
                  f"Reply-lint rule hits: {json.dumps(k['reply_lint_rule_hits'])}. Budget events: {json.dumps(k['budget_events_by_agent'])}.", ""]
    L += ["", "## Not measured in Phase 1", "", "| Id | Metric | Label | Reason |", "|---|---|---|---|"]
    for row in report["not_measured"]:
        L.append(f"| {row['id']} | {row['metric']} | {row['label']} | {row['reason']} |")
    failed = [n for n, st in report["inputs"].items() if st["status"] != "ok"]
    if failed:
        L += ["", "Failed inputs: " + ", ".join(f"{n}.json: failed" for n in failed) + "."]
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    report = build(pathlib.Path(args.data).expanduser())
    out = pathlib.Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "phase1-baseline.json").write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "phase1-baseline.md").write_text(render_md(report), encoding="utf-8")
    print(json.dumps({"sessions": report["sessions_total"], "inputs": {k: v["status"] for k, v in report["inputs"].items()},
                      "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
