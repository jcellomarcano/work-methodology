#!/usr/bin/env python3
"""Observational benchmark: what happened in real Claude Code sessions, per session and per group.

Usage:
  bench.py session [--root DIR] [--project PATH|SUBSTR] [--since YYYY-MM-DD]
                   [--window-table FILE] [--out DIR]

--project: an existing path selects exactly that repo's transcript dir; anything else is a
substring filter over transcript dir names; without it every project is read.
--since: keeps sessions whose last record is on or after that day.
--window-table: JSON {"model id prefix": window tokens}, merged over the built-in table.

Writes <out>/session-report.json and <out>/session-report.md. Deterministic (sorted keys,
no run timestamps) and private: no prompt or reply text and no absolute path is written;
projects are named by their transcript dir name. Every number carries a label and a status.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
from collections import Counter

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if __name__ == "__main__":
    # Run directly from a skill folder: the installer copies that folder entry by entry, so leave no
    # __pycache__ next to it. Set here, not in the entry block at the end of the file, because the
    # sibling import below is what would be compiled (same rule as bench_cli.py).
    sys.dont_write_bytecode = True

import transcript_metrics as tm  # noqa: E402

SCHEMA_VERSION = "1.0.0"
TOKEN_TYPES = ("input", "cache_write", "cache_read", "output")
# Context window per model id prefix (longest prefix wins). Neither transcripts nor OTel state
# the window, so these come from the Claude API model table (cached 2026-10-06) and stay Assumed;
# override them with --window-table.
DEFAULT_WINDOWS = {
    "claude-fable-5": 1_000_000, "claude-mythos-5": 1_000_000,
    "claude-opus-5": 1_000_000, "claude-opus-4-8": 1_000_000, "claude-opus-4-7": 1_000_000,
    "claude-opus-4-6": 1_000_000, "claude-sonnet-5": 1_000_000, "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-5": 1_000_000, "claude-haiku-4-5": 200_000,
}
LABELS = {
    "Measured": "counted from the transcript records",
    "Tested": "checked by a deterministic verifier (not used in this mode)",
    "Inferred": "derived by reasoning, e.g. attributing a group difference to a harness",
    "Assumed": "taken from configuration, e.g. the context window table",
    "Unknown": "the input was not recorded; no number is shown",
}
STATUSES = {
    "ok": "computed from recorded input",
    "not-run": "the input this number needs was not recorded",
    "failed": "the transcript could not be read",
    "invalid-arm": "A/B mode only: the arm's setup did not run",
}
CORRELATIONAL_LINE = ("Observational results are correlational: a difference between groups is a signal, "
                      "never a conclusion; attributing it to a harness is Inferred.")
GROUP_ORDER = (("all", "all"), ("by_kit", "kit"), ("by_kit", "no-kit"),
               ("by_subagents", "with-subagents"), ("by_subagents", "without-subagents"))


class UsageError(Exception):
    pass


def _row(value, label="Measured", status="ok", **extra) -> dict:
    out = {"value": value, "label": label, "status": status}
    out.update(extra)
    return out


def _unknown(**extra) -> dict:
    return _row(None, "Unknown", "not-run", **extra)


def _round(x):
    return round(x, 6) if isinstance(x, float) else x


def window_for(model: str | None, table: dict) -> int | None:
    if not model:
        return None
    hits = [k for k in table if model.startswith(k)]
    return table[max(hits, key=lambda k: (len(k), k))] if hits else None


def display_project(dirname: str, home: str | None = None) -> str:
    """A transcript dir name encodes the absolute path, user name included; reports show the
    home prefix as "~" so they can be shared."""
    home = home if home is not None else os.path.expanduser("~")
    prefix = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(home) if os.path.exists(home) else home)
    return "~" + dirname[len(prefix):] if prefix and dirname.startswith(prefix + "-") else dirname


def _main_model(models: dict) -> str | None:
    return max(models, key=lambda m: (models[m], m)) if models else None


def session_row(s: dict, windows: dict) -> dict:
    main_t, sub_t = s["tokens"]["main"], s["tokens"]["subagents"]
    total_main, total_sub = sum(main_t.values()), sum(sub_t.values())
    total = total_main + total_sub
    model = _main_model(s["models"])
    window = window_for(model, windows)
    peak = s["peak_context_tokens"]
    dropped = [c["pre"] - c["post"] for c in s["compactions"]
               if isinstance(c.get("pre"), int) and isinstance(c.get("post"), int)]
    has_sub = s["subagents"]["count"] > 0 or bool(s["agent_tool_calls_by_type"])
    metrics = {
        "activation": {
            "kit_strong": _row(s["kit"]["uses_kit"]),
            "kit_markers": _row(s["kit"]["markers"]),
            "skills": _row(s["skills"]),
            "mcp_servers": _row(s["mcp_servers"]),
        },
        "tokens": {
            "main": _row(dict(main_t)),
            "subagents": _row(dict(sub_t)),
            "total": _row(total),
        },
        "cost_usd": (_row(s["cost_usd"], source="transcript cost-state") if s["cost_usd"] is not None
                     else _unknown(source="not recorded")),
        "context": {
            "peak_tokens": _row(peak, model=model),
            "window_tokens": _row(window, "Assumed", model=model) if window else _unknown(model=model),
            # Divides by an Assumed window, so the ratio is Inferred, never Measured.
            "occupancy": (_row(_round(peak / window), "Inferred", model=model) if window
                          else _unknown(model=model)),
        },
        "compactions": {
            "count": _row(len(s["compactions"])),
            "tokens_dropped": (_row(sum(dropped)) if len(dropped) == len(s["compactions"])
                               else _unknown()),
        },
        "delegation": {
            "subagent_token_share": _row(_round(total_sub / total)) if total else _unknown(),
            "subagents": _row(s["subagents"]["count"]),
            "subagents_by_type": _row(s["subagents"]["by_type"]),
        },
        "model_effort": _row(s["model_effort"]),
        "requests": _row(s["requests"]),
        "steering": {
            "turns": _row(s["human_prompts"]["count"]),
            "queued_messages": _row(s["human_prompts"]["queued_count"]),
            "slash_commands": _row(s["slash_commands"]),
        },
        "wall_clock_s": _row(s["duration_s"]) if s["duration_s"] is not None else _unknown(),
    }
    return {
        "session_id": s["session_id"],
        "project_dir": display_project(s["project_dir"]),
        "first_ts": s["first_ts"],
        "last_ts": s["last_ts"],
        "group": {"kit": "kit" if s["kit"]["uses_kit"] else "no-kit",
                  "subagents": "with-subagents" if has_sub else "without-subagents"},
        "metrics": metrics,
    }


def _median(values) -> dict:
    xs = [v for v in values if v is not None]
    if not xs:
        return _unknown(n=0)
    return _row(_round(float(statistics.median(xs))), n=len(xs))


def _inferred(row: dict) -> dict:
    return dict(row, label="Inferred") if row["value"] is not None else row


def _sessions_using(rows, getter) -> dict:
    c = Counter()
    for r in rows:
        for key in getter(r):
            c[key] += 1
    return _row(dict(sorted(c.items())), n=len(rows))


def group_summary(rows: list) -> dict:
    m = [r["metrics"] for r in rows]
    mix = Counter()
    for x in m:
        for model, efforts in x["model_effort"]["value"].items():
            for effort, k in efforts.items():
                mix[(model, effort)] += k
    requests = sum(mix.values())
    share = {}
    for (model, effort), k in sorted(mix.items()):
        share.setdefault(model, {})[effort] = _round(k / requests)
    sub_types = Counter()
    for x in m:
        sub_types.update(x["delegation"]["subagents_by_type"]["value"])
    tokens_by_type = {}
    for t in TOKEN_TYPES:
        med = _median([x["tokens"]["main"]["value"][t] + x["tokens"]["subagents"]["value"][t] for x in m])
        tokens_by_type[t] = med["value"]
    metrics = {
        "sessions_with_kit_markers": _row(sum(1 for x in m if x["activation"]["kit_strong"]["value"]), n=len(m)),
        "skills_sessions": _sessions_using(m, lambda x: x["activation"]["skills"]["value"]),
        "mcp_servers_sessions": _sessions_using(m, lambda x: x["activation"]["mcp_servers"]["value"]),
        "tokens_total_median": _median([x["tokens"]["total"]["value"] for x in m]),
        "tokens_by_type_median": (_row(tokens_by_type, n=len(m)) if m else _unknown(n=0)),
        "cost_usd_median": dict(_median([x["cost_usd"]["value"] for x in m]),
                                source="transcript cost-state; sessions without one are left out of n"),
        "peak_context_median": _median([x["context"]["peak_tokens"]["value"] for x in m]),
        "occupancy_median": _inferred(_median([x["context"]["occupancy"]["value"] for x in m])),
        "compactions_median": _median([x["compactions"]["count"]["value"] for x in m]),
        "tokens_dropped_median": _median([x["compactions"]["tokens_dropped"]["value"] for x in m]),
        "subagent_token_share_median": _median([x["delegation"]["subagent_token_share"]["value"] for x in m]),
        "subagents_by_type_total": _row(dict(sorted(sub_types.items())), n=len(m)),
        "model_effort_share": _row(share, n=requests) if requests else _unknown(n=0),
        "turns_median": _median([x["steering"]["turns"]["value"] for x in m]),
        "queued_messages_median": _median([x["steering"]["queued_messages"]["value"] for x in m]),
        "wall_clock_s_median": _median([x["wall_clock_s"]["value"] for x in m]),
    }
    return {"n": len(rows), "metrics": metrics}


def load_windows(path: str | None) -> tuple[dict, str]:
    table = dict(DEFAULT_WINDOWS)
    if not path:
        return table, "built-in"
    p = pathlib.Path(path).expanduser()
    try:
        extra = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"--window-table: cannot read a JSON object ({type(exc).__name__})") from exc
    if not isinstance(extra, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0
            for k, v in extra.items()):
        raise UsageError('--window-table: expected {"model id prefix": positive int}')
    table.update(extra)
    return table, f"built-in + {p.name}"


def select_files(root: pathlib.Path, project: str | None) -> tuple[list, dict]:
    if project and os.path.exists(os.path.expanduser(project)):
        tdir = tm.transcript_dir(os.path.expanduser(project), root=root)
        files = sorted(tdir.glob("*.jsonl")) if tdir.is_dir() else []
        return files, {"mode": "path", "project": display_project(tdir.name)}
    if project and os.sep in project:
        raise UsageError("--project: that path does not exist (a substring filter cannot contain a path separator)")
    files = list(tm.main_session_files(root, project))
    return files, {"mode": "substring" if project else "all", "project": project}


def build_report(root: pathlib.Path, project: str | None, since: str | None, windows: dict,
                 window_source: str) -> dict:
    files, selection = select_files(root, project)
    rows, failures = [], []
    for f in files:
        try:
            s = tm.analyze_session(f)
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden; only the type, no path
            failures.append({"file": f.name, "project_dir": display_project(f.parent.name), "error": type(exc).__name__,
                             "status": "failed", "label": "Measured"})
            continue
        if since and (not s["last_ts"] or s["last_ts"][:10] < since):
            continue
        rows.append(session_row(s, windows))
    rows.sort(key=lambda r: (r["project_dir"], r["first_ts"] or "", r["session_id"]))
    groups = {"all": group_summary(rows), "by_kit": {}, "by_subagents": {}}
    for split, name in GROUP_ORDER[1:]:
        key = "kit" if split == "by_kit" else "subagents"
        groups[split][name] = group_summary([r for r in rows if r["group"][key] == name])
    failures.sort(key=lambda x: (x["project_dir"], x["file"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "mode": "observational",
        "filters": {"selection": selection, "since": since},
        "window_table": {"source": window_source, "label": "Assumed", "prefixes": dict(sorted(windows.items()))},
        "legend": {"labels": LABELS, "statuses": STATUSES},
        "notes": [CORRELATIONAL_LINE],
        "sessions": rows,
        "groups": groups,
        "failures": failures,
    }


def _fmt(v) -> str:
    if v is None:
        return "Unknown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, dict):
        parts = []
        for k, x in v.items():
            if isinstance(x, dict):
                parts += [f"{k}/{k2}={_fmt(x2)}" for k2, x2 in x.items()]
            else:
                parts.append(f"{k}={_fmt(x)}")
        return ", ".join(parts) or "none"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "none"
    return str(v)


def render_md(rep: dict) -> str:
    g = rep["groups"]
    n_kit, n_vanilla = g["by_kit"]["kit"]["n"], g["by_kit"]["no-kit"]["n"]
    sel = rep["filters"]["selection"]
    lines = [
        "# Session benchmark (observational)",
        "",
        CORRELATIONAL_LINE,
        "",
        f"Signal vs conclusion: n kit = {n_kit}, n no-kit = {n_vanilla}; every difference below is a signal, "
        "never a conclusion. Only the A/B mode can attribute a difference to a setup.",
        "",
        f"Selection: {sel['mode']}" + (f" `{sel['project']}`" if sel["project"] else "")
        + f"; since: {rep['filters']['since'] or 'any'}; sessions n = {g['all']['n']}; "
        f"unreadable transcripts n = {len(rep['failures'])}. Window table: {rep['window_table']['source']} "
        "(Assumed). Groups: `kit` = at least one strong kit marker (a kit hook that ran, a `metodo` MCP call "
        "or a `generic-*` subagent).",
        "",
        "## Labels and statuses",
        "",
    ]
    lines += [f"- **{k}**: {v}." for k, v in rep["legend"]["labels"].items()]
    lines += [f"- `{k}`: {v}." for k, v in rep["legend"]["statuses"].items()]
    lines += ["", "## Groups"]
    for split, name in GROUP_ORDER:
        grp = g[split] if split == "all" else g[split][name]
        lines += ["", f"### {name} (n = {grp['n']})", "",
                  "| Metric | Value | n | Label | Status |", "|---|---|---|---|---|"]
        for metric, row in grp["metrics"].items():
            lines.append(f"| {metric} | {_fmt(row['value'])} | {row['n']} | {row['label']} | {row['status']} |")
    lines += ["", "## Sessions (n = 1 per row)", "",
              "| Session | Project dir | Group | Tokens | Cost USD | Peak context | Occupancy | Compactions "
              "| Subagent share | Turns | Queued | Wall-clock s |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["sessions"]:
        x = r["metrics"]
        lines.append("| " + " | ".join([
            r["session_id"][:8], f"`{r['project_dir']}`", f"{r['group']['kit']}, {r['group']['subagents']}",
            _fmt(x["tokens"]["total"]["value"]),
            _fmt(x["cost_usd"]["value"]) + f" ({x['cost_usd']['source']})",
            _fmt(x["context"]["peak_tokens"]["value"]), _fmt(x["context"]["occupancy"]["value"]),
            _fmt(x["compactions"]["count"]["value"]), _fmt(x["delegation"]["subagent_token_share"]["value"]),
            _fmt(x["steering"]["turns"]["value"]), _fmt(x["steering"]["queued_messages"]["value"]),
            _fmt(x["wall_clock_s"]["value"]),
        ]) + " |")
    lines += ["", "Labels per column: every count is Measured; window sizes are Assumed; occupancy is Inferred "
              "(it divides by an Assumed window); a missing input is "
              "Unknown (`not-run`). Full rows with labels and statuses are in `session-report.json`.", ""]
    if rep["failures"]:
        lines += ["## Unreadable transcripts", ""]
        lines += [f"- `{f['project_dir']}/{f['file']}`: {f['error']} (`failed`)" for f in rep["failures"]]
        lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bench.py session", description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="transcripts root (default ${CLAUDE_PROJECTS_DIR:-~/.claude/projects})")
    ap.add_argument("--project", default=None, help="a repo path, or a substring of transcript dir names")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD, compared with each session's last record")
    ap.add_argument("--window-table", default=None, help='JSON {"model id prefix": window tokens}')
    ap.add_argument("--out", default="bench-session", help="output dir (default ./bench-session)")
    return ap


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed its usage message
        return int(exc.code or 0)
    try:
        if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
            raise UsageError("--since: expected YYYY-MM-DD")
        if args.since:
            try:
                dt.date.fromisoformat(args.since)
            except ValueError as exc:
                raise UsageError("--since: not a calendar date") from exc
        root = pathlib.Path(args.root or os.environ.get("CLAUDE_PROJECTS_DIR") or "~/.claude/projects").expanduser()
        if not root.is_dir():
            raise UsageError("transcripts root not found (set --root or CLAUDE_PROJECTS_DIR)")
        windows, source = load_windows(args.window_table)
        rep = build_report(root, args.project, args.since, windows, source)
    except UsageError as exc:
        print(f"usage: bench.py session: {exc}", file=sys.stderr)
        return 2
    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "session-report.json").write_text(
        json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "session-report.md").write_text(render_md(rep), encoding="utf-8")
    print(json.dumps({"failures": len(rep["failures"]), "out": str(out), "sessions": len(rep["sessions"])},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
