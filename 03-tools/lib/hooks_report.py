#!/usr/bin/env python3
"""Turns the hooks ledger (out/hooks/<session>/ledger.jsonl) and the
receipts (out/rdd/*.receipt.json) into the figures agent-protocol.md
paragraph 8 asks for and nobody measured: calls per agent, denials,
warnings, invalid or truncated outputs, gates, receipts by tier and
verdict, first-pass acceptance. And the warn -> block pass criterion.

Usage:
    lib/hooks_report.py [--hooks-dir out/hooks] [--receipts-dir out/rdd] [--min-days 7] [--min-receipts 5] [--max-false-positives 2]
    lib/hooks_report.py --false-positive "<reason>" --session <id> --seq <n> [--hooks-dir ...]
    lib/hooks_report.py --mark-fp <session> <seq> --reason "<why>" [--hooks-dir ...]
    lib/hooks_report.py --verdicts --as-of YYYY-MM-DD [--transcript-metrics sessions.json]
                        [--activation-config F] [--format json|md] [--hooks-dir ...]

Output: out/hooks/report.json (and on stdout). Tokens never reach a hook:
they go in not_measured with how to get them. --mark-fp appends an owner
mark to out/hooks/<session>/false-positives.jsonl (the ledger is never
edited). --verdicts (T9, activation.md section 4, D11 thresholds from
config/activation.json) prints per-element verdicts over the window ending
on --as-of: PROMOTE (to BLOCK), DEMOTE (to OFF), KEEP, EXPIRE (to OFF) or
INSUFFICIENT_DATA. A verdict is a recommendation: it writes nothing and
never changes config; applying one needs a card (methodology.md section 12).
Unmeasured is never perfect (T18, B-007/A-009): precision needs at least one
owner FP mark on the element, override_rate needs outcome lines when the
element asked, act_rate needs M107 judged warns for a WARN element, and an
element whose ledger lines are all mode off is never observed live; any of
these leaves the metric null, named in not_measured, and the verdict KEEP or
INSUFFICIENT_DATA (EXPIRE once past its windows), never PROMOTE.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import activation, baseline  # noqa: E402

FP_FILE = "false-positives.jsonl"
FIRE_DECISIONS = ("warn", "deny", "ask", "block")
BLOCK_DECISIONS = ("deny", "ask", "block")
RECOMMEND = {"PROMOTE": "BLOCK", "DEMOTE": "OFF", "EXPIRE": "OFF"}
_COMMON = None


def hooks_common():
    """hooks/_common.py, for its element table and run-file name (one source)."""
    global _COMMON
    if _COMMON is None:
        spec = importlib.util.spec_from_file_location("metodo_hooks_common_report", TOOLS_ROOT / "hooks" / "_common.py")
        _COMMON = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_COMMON)
    return _COMMON


def _line_element(line: dict) -> str:
    return hooks_common().element_for(line.get("hook"), line.get("kind"), line.get("decision"),
                                      bool(line.get("agent_type") or line.get("agent_id")))

LEDGER_FIELDS = ("seq", "hook", "event", "agent_type", "agent_id", "tool", "kind", "decision", "mode", "reason", "path", "tree", "receipt")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _days_observed(hooks_dir: Path) -> int:
    stamps = []
    for meta in hooks_dir.glob("*/run-meta.json"):
        try:
            stamps.append(datetime.datetime.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["started_at"]))
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    if len(stamps) < 1:
        return 0
    return (max(stamps) - min(stamps)).days


def build_report(hooks_dir: Path, receipts_dir: Path, min_days: int, min_receipts: int, max_false_positives: int) -> dict:
    per_agent: dict[str, Counter] = defaultdict(Counter)
    gates = Counter()
    sessions = 0
    for session_dir in sorted(p for p in hooks_dir.glob("*") if p.is_dir()):
        sessions += 1
        for count_file in session_dir.glob("budget-*.count"):
            agent_type = count_file.stem[len("budget-"):].rsplit("-", 1)[0]
            try:
                calls = int(count_file.read_text(encoding="utf-8").strip() or 0)
            except ValueError:
                calls = 0
            per_agent[agent_type]["calls"] += calls
            per_agent[agent_type]["max_calls"] = max(per_agent[agent_type]["max_calls"], calls)
            per_agent[agent_type]["runs"] += 1
        for line in read_jsonl(session_dir / "ledger.jsonl"):
            agent = line.get("agent_type") or "main"
            kind = line.get("kind", "")
            decision = line.get("decision", "")
            if decision == "deny":
                per_agent[agent]["denials"] += 1
            elif decision in ("warn", "ask"):
                per_agent[agent]["warnings"] += 1
            if kind == "output-invalid":
                per_agent[agent]["invalid_outputs"] += 1
            if kind == "output-truncated":
                per_agent[agent]["truncated_outputs"] += 1
            if kind in ("gate-push", "gate-pr", "gate-merge", "gate-tag"):
                gates[kind] += 1
                if line.get("receipt") == "approved":
                    gates[f"{kind}_with_receipt"] += 1
                elif decision != "deny":
                    gates[f"{kind}_without_receipt"] += 1
                if decision == "ask":
                    gates["asks"] += 1
            if kind == "force-push" and decision == "deny":
                gates["force_denied"] += 1
            if kind == "budget-deny":
                gates["budget_denied"] += 1

    receipts = Counter()
    verdicts = Counter()
    finalized = first_pass = corrections = escalations = verifier_fail = acks = 0
    for path in sorted(receipts_dir.glob("*.receipt.json")):
        r = baseline.load_json(path)
        receipts[r["risk"]["tier"]] += 1
        if r["state"] == "finalized":
            finalized += 1
            verdicts[r["verdict"] or "none"] += 1
            if r["verdict"] == "approved" and r["correction_index"] == 0 and not r.get("inherited_from"):
                first_pass += 1
            if r["correction_index"] == 1:
                corrections += 1
            if r["verdict"] == "escalated":
                escalations += 1
            if any("verifier FAIL" in reason for reason in r.get("verdict_reasons", [])):
                verifier_fail += 1
        if r.get("owner_ack"):
            acks += 1

    false_positives = read_jsonl(hooks_dir / FP_FILE) + [
        m for s in sorted(p for p in hooks_dir.glob("*") if p.is_dir()) for m in read_jsonl(s / FP_FILE)]
    days = _days_observed(hooks_dir)
    flip = {
        "min_days": min_days, "days_observed": days,
        "min_receipts": min_receipts, "receipts_finalized": finalized,
        "max_false_positives": max_false_positives, "false_positives": len(false_positives),
    }
    flip["ready"] = days >= min_days and finalized >= min_receipts and len(false_positives) <= max_false_positives

    return {
        "sessions": sessions,
        "per_agent": {agent: dict(sorted(counter.items())) for agent, counter in sorted(per_agent.items())},
        "gates": dict(sorted(gates.items())),
        "receipts": {
            "by_tier": dict(sorted(receipts.items())),
            "by_verdict": dict(sorted(verdicts.items())),
            "finalized": finalized,
            "first_pass_acceptance": first_pass,
            "corrections_used": corrections,
            "escalations": escalations,
            "verifier_fail_caught": verifier_fail,
            "owner_acks": acks,
        },
        "false_positives": false_positives,
        "flip_warn_to_block": flip,
        "not_measured": [{"metric": "tokens_per_agent",
                          "how_to_get_it": "hooks do not receive tokens; parse transcript_path per session, not built"}],
    }


def record_false_positive(hooks_dir: Path, session: str, seq: int, reason: str) -> Path:
    path = hooks_dir / "false-positives.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"session": session, "seq": seq, "reason": reason}, ensure_ascii=False) + "\n")
    return path


def mark_false_positive(hooks_dir: Path, session: str, seq: int, reason: str) -> Path:
    """Appends the owner's mark for ledger line <session>:<seq>; raises
    ValueError when that line does not exist. The ledger is only read."""
    sdir = hooks_dir / session
    line = next((l for l in read_jsonl(sdir / "ledger.jsonl") if l.get("seq") == seq), None)
    if line is None:
        raise ValueError(f"no ledger line {session}:{seq} under {hooks_dir}")
    if not str(reason).strip():
        raise ValueError("a false-positive mark needs a reason")
    mark = {"session": session, "seq": seq, "hook": line.get("hook"), "kind": line.get("kind"),
            "decision": line.get("decision"), "element": _line_element(line), "reason": reason}
    path = sdir / FP_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(mark, ensure_ascii=False) + "\n")
    return path


# ------------------------------------------------------------ T9 verdicts

def _session_date(sdir: Path) -> datetime.date | None:
    try:
        return datetime.datetime.fromisoformat(
            json.loads((sdir / "run-meta.json").read_text(encoding="utf-8"))["started_at"]).date()
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _act_by_element(path: Path | None, start: datetime.date, end: datetime.date) -> dict:
    """{element: [judged, acted]} from transcript_metrics M107 (warn_act.by_kind),
    sessions whose first_ts falls in the window."""
    out: dict = {}
    if path is None:
        return out
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for s in data.get("sessions") or []:
        try:
            day = datetime.date.fromisoformat(str(s.get("first_ts") or "")[:10])
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        for kind, k in sorted((((s.get("context_metrics") or {}).get("warn_act") or {}).get("by_kind") or {}).items()):
            slot = out.setdefault(hooks_common().element_for(None, kind), [0, 0])
            slot[0] += int(k.get("judged") or 0)
            slot[1] += int(k.get("acted") or 0)
    return out


def verdicts(hooks_dir: Path, as_of: str, thresholds: dict, transcript_metrics: Path | None = None) -> dict:
    """Per-element verdicts over the window ending on `as_of` (activation.md
    section 4). Pure over the files read: no clock, no write."""
    end = datetime.date.fromisoformat(as_of)
    width = int(thresholds["min_days"])
    start = end - datetime.timedelta(days=width - 1)
    t = thresholds
    sessions = []
    for sdir in sorted(p for p in Path(hooks_dir).glob("*") if p.is_dir()):
        day = _session_date(sdir)
        if day is not None and day <= end:
            sessions.append((day, sdir.name, sdir))
    sessions.sort()
    observed_since = sessions[0][0] if sessions else None
    full_window = observed_since is not None and observed_since <= start
    stats: dict = {}

    def slot(element):
        return stats.setdefault(element, {"first_seen": None, "mode": None, "run_mode": None, "runs": 0, "fires": 0,
                                          "blocks": 0, "asks": 0, "overrides": 0, "outcome_lines": 0, "fps": 0,
                                          "main_deny_fps": 0, "lines": 0, "off_lines": 0})

    for day, name, sdir in sessions:
        in_window = day >= start
        lines = read_jsonl(sdir / "ledger.jsonl")
        runs = read_jsonl(sdir / hooks_common().RUNS_FILE)
        marks = {m.get("seq") for m in read_jsonl(sdir / FP_FILE) + read_jsonl(Path(hooks_dir) / FP_FILE)
                 if m.get("session", name) == name}
        for run in runs:
            s = slot(run.get("element") or "unknown")
            s["first_seen"] = s["first_seen"] or day
            if in_window:
                s["runs"] += 1
                s["run_mode"] = run.get("mode") or s["run_mode"]
        open_asks: dict = defaultdict(int)
        for line in lines:
            element = _line_element(line)
            s = slot(element)
            s["first_seen"] = s["first_seen"] or day
            if not in_window:
                continue
            s["lines"] += 1
            s["off_lines"] += str(line.get("mode") or "").lower() == "off"
            decision, kind = line.get("decision"), line.get("kind") or ""
            if kind.endswith("-outcome"):
                s["outcome_lines"] += 1
                key = (kind[:-len("-outcome")], line.get("tree"))
                if decision == "ran" and open_asks[key] > 0:
                    open_asks[key] -= 1
                    s["overrides"] += 1
                continue
            if decision not in FIRE_DECISIONS:
                continue
            s["fires"] += 1
            s["mode"] = line.get("mode") or s["mode"]
            s["blocks"] += decision in BLOCK_DECISIONS
            if decision == "ask":
                s["asks"] += 1
                open_asks[(kind, line.get("tree"))] += 1
            if line.get("seq") in marks:
                s["fps"] += 1
                if decision == "deny" and not (line.get("agent_type") or line.get("agent_id")):
                    s["main_deny_fps"] += 1

    act = _act_by_element(transcript_metrics, start, end)
    elements = {}
    for element in sorted(stats):
        elements[element] = _verdict(element, stats[element], act.get(element), t, end, width, full_window)
    return {"as_of": as_of, "window": {"days": width, "start": start.isoformat(), "end": end.isoformat(),
                                       "observed_since": observed_since.isoformat() if observed_since else None,
                                       "full": full_window},
            "thresholds": {k: t[k] for k in sorted(t)}, "elements": elements,
            "note": "recommendations only: applying a verdict or changing a threshold needs a card "
                    "(methodology.md section 12); this report never writes config"}


def _verdict(element, s, act, t, end, width, full_window) -> dict:
    mode = (s["mode"] or s["run_mode"] or "").upper() or None
    fires, not_measured, reasons = s["fires"], [], []
    # Unmeasured is null, never perfect: no FP mark means nobody sampled the fires.
    precision = round(1 - s["fps"] / fires, 4) if fires and s["fps"] else None
    if precision is None:
        not_measured.append({"metric": "precision", "why": "no fires in the window" if not fires
                             else "no owner FP marks on this element in the window (mark-fp)"})
    if s["asks"] and s["outcome_lines"]:
        override = _rate(s["overrides"], s["asks"])
    else:
        override = None
        not_measured.append({"metric": "override_rate", "why": "no asks in the window" if not s["asks"]
                             else "no <kind>-outcome ledger lines in the window"})
    act_rate = _rate(act[1], act[0]) if act else None
    if act_rate is None:
        not_measured.append({"metric": "act_rate", "why": "no judged warns from --transcript-metrics (M107) in the window"})
    # PROMOTE criteria that must be measured: precision always, override_rate
    # when the element asked, act_rate for a WARN element (a LOG one has none).
    missing = [m for m, absent in (("precision", precision is None),
                                   ("override_rate", bool(s["asks"]) and override is None),
                                   ("act_rate", mode == "WARN" and act_rate is None)) if absent]
    all_off = bool(s["lines"]) and s["off_lines"] == s["lines"]
    if not s["runs"]:
        not_measured.append({"metric": "fire_rate", "why": "no run lines (hook-runs.jsonl) in the window"})
    age = (end - s["first_seen"]).days if s["first_seen"] else 0
    expired = mode in ("LOG", "WARN") and age >= int(t["max_windows"]) * width
    absolute = element in activation.ABSOLUTE
    enough = full_window and fires >= t["min_fires"]
    if absolute:
        verdict = "KEEP"
        reasons.append("absolute set: exempt, owner decision only")
    elif not enough:
        verdict = "EXPIRE" if expired else "INSUFFICIENT_DATA"
        reasons.append(f"fires {fires} < min_fires {t['min_fires']}" if fires < t["min_fires"]
                       else f"observation shorter than one {width}-day window")
        if expired:
            reasons.append(f"{mode} for {age} days >= {t['max_windows']} windows: expired")
    else:
        demote = []
        if precision is not None and precision < t["precision_min"]:
            demote.append(f"precision {precision} < {t['precision_min']}")
        if override is not None and override > t["override_max"]:
            demote.append(f"override_rate {override} > {t['override_max']}")
        if mode == "WARN" and act_rate is not None and act_rate < t["act_rate_min"]:
            demote.append(f"act_rate {act_rate} < {t['act_rate_min']}")
        blockers = []
        if s["fps"] > t["max_false_positives"]:
            blockers.append(f"{s['fps']} confirmed FPs > {t['max_false_positives']}")
        if s["main_deny_fps"] > t["main_deny_max_false_positives"]:
            blockers.append(f"{s['main_deny_fps']} confirmed FPs on a main-session deny")
        if demote:
            verdict, reasons = "DEMOTE", demote
        elif not blockers and mode != "BLOCK" and (missing or all_off):
            verdict = "EXPIRE" if expired else "INSUFFICIENT_DATA"
            reasons += [f"{m} not measured: never counts toward PROMOTE" for m in missing]
            if all_off:
                reasons.append("every ledger line in the window is mode off: never observed live")
            if expired:
                reasons.append(f"{mode} for {age} days >= {t['max_windows']} windows: not promotable")
        elif not blockers and mode != "BLOCK":
            verdict = "PROMOTE"
            reasons.append(f"precision {precision} >= {t['precision_min']}, {s['fps']} confirmed FPs")
        elif expired:
            verdict = "EXPIRE"
            reasons += blockers + [f"{mode} for {age} days >= {t['max_windows']} windows: not promotable"]
        else:
            verdict = "KEEP"
            reasons += blockers or [f"already {mode}; thresholds met"]
    return {"absolute": absolute, "mode": mode, "runs": s["runs"], "fires": fires, "fire_rate": _rate(fires, s["runs"]),
            "block_rate": _rate(s["blocks"], fires), "asks": s["asks"], "overrides": s["overrides"],
            "override_rate": override, "act_rate": act_rate, "judged": act[0] if act else 0,
            "acted": act[1] if act else 0, "false_positives": s["fps"], "main_deny_false_positives": s["main_deny_fps"],
            "precision": precision, "first_seen": s["first_seen"].isoformat() if s["first_seen"] else None,
            "age_days": age, "verdict": verdict, "recommend": RECOMMEND.get(verdict, mode if verdict == "KEEP" else None),
            "reasons": reasons, "not_measured": not_measured}


def verdicts_markdown(report: dict) -> str:
    w = report["window"]
    rows = [f"# Hook verdicts as of {report['as_of']}", "",
            f"Window {w['start']}..{w['end']} ({w['days']} days, full: {str(w['full']).lower()}). {report['note']}.", "",
            "| element | mode | fires | precision | override | act | verdict | recommend |",
            "|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "n/m" if v is None else str(v)  # noqa: E731
    for name, e in report["elements"].items():
        rows.append(f"| {name} | {fmt(e['mode'])} | {e['fires']} | {fmt(e['precision'])} | {fmt(e['override_rate'])} "
                    f"| {fmt(e['act_rate'])} | {e['verdict']} | {fmt(e['recommend'])} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hooks-dir", default=str(TOOLS_ROOT / "out" / "hooks"))
    parser.add_argument("--receipts-dir", default=str(TOOLS_ROOT / "out" / "rdd"))
    parser.add_argument("--min-days", type=int, default=7)
    parser.add_argument("--min-receipts", type=int, default=5)
    parser.add_argument("--max-false-positives", type=int, default=2)
    parser.add_argument("--false-positive", default=None, help="reason; requires --session and --seq")
    parser.add_argument("--session", default=None)
    parser.add_argument("--seq", type=int, default=None)
    parser.add_argument("--mark-fp", nargs=2, metavar=("SESSION", "SEQ"), default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--verdicts", action="store_true")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--transcript-metrics", default=None)
    parser.add_argument("--activation-config", default=os.environ.get("METODO_ACTIVATION_CONFIG"))
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args(argv)

    hooks_dir = Path(args.hooks_dir)
    if args.mark_fp:
        try:
            path = mark_false_positive(hooks_dir, args.mark_fp[0], int(args.mark_fp[1]), args.reason or "")
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"recorded": str(path)}))
        return 0
    if args.verdicts:
        if not args.as_of:
            parser.error("--verdicts requires --as-of YYYY-MM-DD (dates never come from the clock)")
        try:
            datetime.date.fromisoformat(args.as_of)
            thresholds = activation.load_config(args.activation_config)["thresholds"]
            report = verdicts(hooks_dir, args.as_of, thresholds,
                              Path(args.transcript_metrics) if args.transcript_metrics else None)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        print(verdicts_markdown(report) if args.format == "md" else json.dumps(report, sort_keys=True, indent=2), end="" if args.format == "md" else "\n")
        return 0
    if args.false_positive:
        if not (args.session and args.seq is not None):
            parser.error("--false-positive requires --session and --seq")
        path = record_false_positive(hooks_dir, args.session, args.seq, args.false_positive)
        print(json.dumps({"recorded": str(path)}))
        return 0

    report = build_report(hooks_dir, Path(args.receipts_dir), args.min_days, args.min_receipts, args.max_false_positives)
    if hooks_dir.exists():
        baseline.write_json(hooks_dir / "report.json", report)
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
