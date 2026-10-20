#!/usr/bin/env python3
"""A/B harness benchmark: run tasks under named arms, judge review findings, report with paired CIs.

Three entry points, dispatched by bench_cli.py (`bench.py ab|judge|report`):
  ab     --config ab.json [--preset kit-vs-vanilla] [--out DIR] [--dry-run]
  judge  --run DIR
  report --run DIR [--out DIR]

`ab` runs every task x arm x repetition in a seeded random order. Each run gets a fresh
`git worktree add --detach` of the repo at the pinned sha in the system temp dir, outside the
repo; an arm's `overlay` copies untracked paths (the kit's `.claude/`, `.mcp.json`) into it, so
an arm without overlay sees no kit file. The worktree is removed in a finally block. The user's
working tree is never written. A run is `ok`, `failed` (no output, API error, timeout, no
findings block) or `invalid-arm` (its transcript does not match the arm's evidence pattern).

`judge` matches seeded defects deterministically, then asks every configured judge to rate
each finding of two arms (kit fingerprints stripped) in both orders, and reports agreement.

`report` writes report.json and report.md: every number carries a label (Measured, Tested,
Inferred, Unknown) and a status; failed and invalid-arm runs are listed, never averaged in.
Deterministic: sorted keys, no run timestamps, fixed bootstrap seed. No prompt or reply text
and no absolute path reaches the report.

Python 3 stdlib only. Works from 08-benchmark/lib and as a top-level copy in a skill folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile

SCHEMA_VERSION = "1.0.0"
HERE = pathlib.Path(__file__).resolve().parent
SIGNAL_LINE = "signal, not a conclusion"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERDICTS = ("valid", "invalid", "Unknown")

# Same allowlist as bin/pr-review-ab.sh: read-only inspection, git history, delegation, kit MCP tools.
DEFAULT_ALLOWED = ("Read,Grep,Glob,Agent,Skill,Bash(git diff:*),Bash(git show:*),Bash(git log:*),"
                   "mcp__metodo__*")
# A kit run shows a kit subagent, a kit MCP call or a kit review skill (English, then pre-port names).
KIT_EVIDENCE = (r'subagent_type":"generic-|"name":"mcp__metodo__|"name":"Skill","input":\{"skill":"'
                r'(receipt-review|adversarial-round|review-comment|cartography|verify-per-commit|'
                r'revision-con-recibo|ronda-adversarial-dos|comentario-de-review|cartografia|verify-por-commit)"')
NATIVE_EVIDENCE = r'"skill":"code-review"'

# The findings contract every review task gets, so every arm answers in the same shape.
REVIEW_CONTRACT = """Do not modify any file and do not post anything. Deliver two things, in this order:

1. A findings list as one JSON array in a fenced ```json block. One object per finding with exactly these fields:
   - "id": "F1", "F2", ...
   - "file": repository-relative path
   - "line": integer line number in the new version, or null
   - "severity": one of "blocker", "major", "minor", "nit"
   - "category": one of "correctness", "security", "concurrency", "performance", "tests", "readability", "standards", "docs"
   - "claim": one sentence stating the defect or improvement
   - "evidence": the exact code fragment or test output that supports the claim (quote, do not paraphrase)
   - "fix": one sentence on the smallest change that resolves it
   - "label": one of "Measured", "Tested", "Inferred", "Assumed": how you know the claim is true
   Report only what you can support with evidence from this repository. An empty array is a valid answer.

2. A verdict line: "VERDICT: approve" or "VERDICT: request-changes", followed by at most three sentences.
"""

TEMPLATES = {
    "neutral": "{task}",
    "kit-invoked": ("This repository ships a review methodology. Use it: invoke the `receipt-review` skill with "
                    "the Skill tool and follow its procedure (tier, cartography if it asks for it, judge and "
                    "adversaries as the tier requires). Do not post comments, do not apply corrections and do not "
                    "modify any repository file. When the procedure ends, do the task below, keeping only findings "
                    "the procedure supported with evidence.\n\n{task}"),
    "native": ("First, use the Skill tool to invoke the `code-review` skill with args \"high\" and follow its "
               "procedure, but do not apply fixes, do not post comments and do not modify any file. Then do the "
               "task below; findings the skill marks as uncertain stay out unless you can support them with "
               "evidence.\n\n{task}"),
}

# Kept byte-identical to protocols/prompts/judge-pairwise.txt (a test fails on drift), so a skill
# folder holding only this file still judges with the same prompt.
JUDGE_PROMPT = """You are judging the findings of two code reviews of the same change. Review A and Review B come from two different setups; you are not told which is which and must not guess. The order in which they appear means nothing.

For every finding in both reviews, decide one of:
- "valid": the defect exists at the cited location and the quoted evidence supports it;
- "invalid": the claim is wrong, or the evidence does not support it;
- "Unknown": you cannot decide from the material below.
Judge each finding on its own. Do not reward length: more findings, longer claims or more detail are not better, and a review with fewer findings and no invalid ones beats a longer review with one invalid finding.

Then say which review you prefer overall: "A", "B" or "tie".

Answer with one JSON object in a fenced ```json block and nothing else:
{"A": {"per_finding": {"F1": "valid"}}, "B": {"per_finding": {"F1": "Unknown"}}, "preferred": "tie"}

Do not use any tool; judge from the text below.

<diff>
<DIFF>
</diff>

<review id="A">
<FINDINGS_A>
</review>

<review id="B">
<FINDINGS_B>
</review>
"""


class ConfigError(Exception):
    pass


def _tool_sha256() -> str:
    return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _r(x):
    return round(x, 6) if isinstance(x, float) else x


# ---------------------------------------------------------------------------------------- config

def preset_arms(name: str) -> list[dict]:
    if name != "kit-vs-vanilla":
        raise ConfigError(f"unknown preset {name!r}; known: kit-vs-vanilla")
    vanilla_env = {"METODO_TOOLS": "/nonexistent"}
    kit_overlay = [".claude", ".mcp.json"]
    return [
        {"name": "vanilla", "prompt_template": TEMPLATES["neutral"], "env": vanilla_env,
         "flags": ["--disable-slash-commands", "--strict-mcp-config"], "overlay": [], "evidence": None},
        {"name": "kit-neutral", "prompt_template": TEMPLATES["neutral"], "env": {}, "flags": [],
         "overlay": kit_overlay, "evidence": KIT_EVIDENCE},
        {"name": "kit-invoked", "prompt_template": TEMPLATES["kit-invoked"], "env": {}, "flags": [],
         "overlay": kit_overlay, "evidence": KIT_EVIDENCE},
        # `--disable-slash-commands` also disables skills, so the native arm keeps the vanilla env and
        # MCP isolation but not that flag; otherwise it could never invoke `code-review`.
        {"name": "native", "prompt_template": TEMPLATES["native"], "env": vanilla_env,
         "flags": ["--strict-mcp-config"], "overlay": [], "evidence": NATIVE_EVIDENCE},
    ]


def _check_rel(path: str, what: str) -> str:
    p = pathlib.PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts:
        raise ConfigError(f"{what} must be a repository-relative path without '..': {path!r}")
    return str(p)


def load_config(path: pathlib.Path, preset: str | None = None) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config: {exc}") from exc
    base = path.resolve().parent
    if not raw.get("model"):
        raise ConfigError("config needs 'model' (the same model runs every arm)")
    repo = (base / raw.get("repo", ".")).resolve()
    cfg = {
        "repo": str(repo), "model": raw["model"], "effort": raw.get("effort", "high"),
        "k": int(raw.get("k", 3)), "seed": raw.get("seed", 0), "timeout_s": float(raw.get("timeout_s", 1800)),
        "max_turns": int(raw.get("max_turns", 80)), "allowed_tools": raw.get("allowed_tools", DEFAULT_ALLOWED),
        "bootstrap_resamples": int(raw.get("bootstrap_resamples", 10000)),
        "judge_timeout_s": float(raw.get("judge_timeout_s", raw.get("timeout_s", 600))),
        "ref": raw.get("sha") or raw.get("head") or "HEAD", "comparisons": raw.get("comparisons"),
    }
    if cfg["k"] < 1:
        raise ConfigError("k must be at least 1")
    preset = preset or raw.get("preset")
    arms = preset_arms(preset) if preset else raw.get("arms") or []
    tasks = raw.get("tasks") or []
    if not arms or not tasks:
        raise ConfigError("config needs at least one task and one arm (or --preset kit-vs-vanilla)")
    cfg["arms"], cfg["tasks"], cfg["judges"] = [], [], []
    for arm in arms:
        name = arm.get("name", "")
        tpl = arm.get("prompt_template", "{task}")
        if not NAME_RE.match(name) or "{task}" not in tpl:
            raise ConfigError(f"arm {name!r}: needs a filename-safe name and a template containing {{task}}")
        cfg["arms"].append({"name": name, "prompt_template": tpl, "env": dict(arm.get("env") or {}),
                            "flags": list(arm.get("flags") or []),
                            "overlay": [_check_rel(p, "overlay") for p in arm.get("overlay") or []],
                            "evidence": arm.get("evidence")})
    for task in tasks:
        tid, kind = task.get("id", ""), task.get("kind", "review")
        if not NAME_RE.match(tid) or kind not in ("review", "change"):
            raise ConfigError(f"task {tid!r}: needs a filename-safe id and kind 'review' or 'change'")
        prompt = task.get("prompt")
        if prompt is None and task.get("prompt_file"):
            prompt = (base / task["prompt_file"]).read_text(encoding="utf-8")
        if not prompt:
            raise ConfigError(f"task {tid!r}: needs 'prompt' or 'prompt_file'")
        cfg["tasks"].append({"id": tid, "kind": kind, "prompt": prompt, "verify": task.get("verify"),
                             "base": task.get("base"), "contract": task.get("contract", True),
                             "seeded": task.get("seeded") or []})
    for judge in raw.get("judges") or []:
        if not NAME_RE.match(judge.get("name", "")) or not judge.get("command"):
            raise ConfigError(f"judge {judge.get('name')!r}: needs a filename-safe name and a command argv")
        cfg["judges"].append({"name": judge["name"], "family": judge.get("family", "unknown"),
                              "command": list(judge["command"])})
    for kind, items, key in (("arm", cfg["arms"], "name"), ("task", cfg["tasks"], "id"),
                             ("judge", cfg["judges"], "name")):
        names = [i[key] for i in items]
        if len(names) != len(set(names)):
            raise ConfigError(f"duplicate {kind} names: {names}")
    return cfg


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def plan_runs(cfg: dict) -> list[dict]:
    items = [(t["id"], a["name"], rep) for t in cfg["tasks"] for a in cfg["arms"] for rep in range(cfg["k"])]
    random.Random(cfg["seed"]).shuffle(items)
    return [{"order": i, "task": t, "arm": a, "rep": r} for i, (t, a, r) in enumerate(items)]


# ------------------------------------------------------------------------------------------ runs

def _transcript_dir(path) -> pathlib.Path:
    """The Claude Code transcript dir of a working directory (transcript_metrics owns the rule)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    try:
        import transcript_metrics
        fn = getattr(transcript_metrics, "transcript_dir", None)
    except ImportError:
        fn = None
    if fn is not None:
        return pathlib.Path(fn(path))
    # Shim until transcript_metrics.transcript_dir exists: the same documented rule.
    root = pathlib.Path(os.environ.get("CLAUDE_PROJECTS_DIR") or "~/.claude/projects").expanduser()
    return root / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def _run_process(cmd, cwd, env, timeout, stdin_text=None) -> dict:
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, start_new_session=True,
                                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        return {"rc": None, "stdout": "", "stderr": repr(exc), "timed_out": False, "launch_error": True}
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:  # kill the whole group, so grandchildren holding the pipes die too
            os.killpg(proc.pid, signal.SIGKILL) if hasattr(os, "killpg") else proc.kill()
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        timed_out = True
    return {"rc": proc.returncode, "stdout": out or "", "stderr": err or "", "timed_out": timed_out,
            "launch_error": False}


def _json_block(text: str):
    m = re.search(r"```json\s*(.*?)```", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return None


def extract_findings(text: str):
    block = _json_block(text)
    return block if isinstance(block, list) else None


def extract_verdict(text: str):
    m = re.search(r"VERDICT:\s*(approve|request-changes)", text or "")
    return m.group(1) if m else None


def _inside(child: pathlib.Path, parent: pathlib.Path) -> bool:
    child, parent = pathlib.Path(os.path.realpath(child)), pathlib.Path(os.path.realpath(parent))
    return child == parent or parent in child.parents


def _copy_overlay(repo: pathlib.Path, wt: pathlib.Path, overlay: list[str]):
    copied, missing = [], []
    for rel in overlay:
        src, dst = repo / rel, wt / rel
        if not (src.exists() or src.is_symlink()):
            missing.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        copied.append(rel)
    return copied, missing


def build_prompt(cfg: dict, task: dict, arm: dict) -> str:
    text = task["prompt"].replace("{sha}", cfg["sha"]).replace("{base}", task.get("base_sha") or "")
    if task["kind"] == "review" and task.get("contract", True):
        text = text.rstrip() + "\n\n" + REVIEW_CONTRACT
    return arm["prompt_template"].replace("{task}", text)


def run_one(cfg: dict, task: dict, arm: dict, rep: int, order: int, out: pathlib.Path) -> dict:
    repo = pathlib.Path(cfg["repo"])
    raw_dir = out / "raw" / task["id"] / arm["name"] / str(rep)
    raw_dir.mkdir(parents=True, exist_ok=True)
    rec = {"task": task["id"], "kind": task["kind"], "arm": arm["name"], "rep": rep, "order": order,
           "sha": cfg["sha"], "model": cfg["model"], "effort": cfg["effort"], "status": "failed", "reason": None,
           "session_id": None, "cost_usd": None, "num_turns": None, "duration_ms": None, "is_error": None,
           "usage": None, "findings_count": None, "verdict": None, "verify_exit": None, "verify_passed": None,
           "evidence_hits": None, "transcript_found": None, "overlay_copied": [], "overlay_missing": []}
    base = pathlib.Path(tempfile.mkdtemp(prefix="bench-ab-")).resolve()
    wt = base / "wt"
    added = False
    try:
        if _inside(wt, repo):
            rec["reason"] = "worktree-inside-repo"
            return rec
        try:
            _git(str(repo), "worktree", "add", "--detach", "--quiet", str(wt), cfg["sha"])
            added = True
        except subprocess.CalledProcessError:
            rec["reason"] = "worktree-failed"
            return rec
        rec["overlay_copied"], rec["overlay_missing"] = _copy_overlay(repo, wt, arm["overlay"])
        prompt = build_prompt(cfg, task, arm)
        (raw_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        cmd = [os.environ.get("CLAUDE_BIN") or "claude", "-p", "--model", cfg["model"], "--effort", cfg["effort"],
               "--output-format", "json", "--allowedTools", cfg["allowed_tools"], "--permission-prompts", "none",
               "--max-turns", str(cfg["max_turns"]), *arm["flags"], prompt]
        res = _run_process(cmd, str(wt), dict(os.environ, **arm["env"]), cfg["timeout_s"])
        (raw_dir / "stdout.json").write_text(res["stdout"], encoding="utf-8")
        (raw_dir / "stderr.txt").write_text(res["stderr"], encoding="utf-8")
        if res["timed_out"]:
            rec["reason"] = "timeout"
            return rec
        if res["launch_error"]:
            rec["reason"] = "launch-failed"
            return rec
        try:
            data = json.loads(res["stdout"]) if res["stdout"].strip() else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            rec["reason"] = "no-output" if not res["stdout"].strip() else "unparseable-output"
            return rec
        usage = data.get("usage") or {}
        rec.update({"session_id": data.get("session_id"), "cost_usd": data.get("total_cost_usd"),
                    "num_turns": data.get("num_turns"), "duration_ms": data.get("duration_ms"),
                    "is_error": data.get("is_error"),
                    "usage": {k: usage.get(k) for k in ("input_tokens", "cache_read_input_tokens",
                                                        "cache_creation_input_tokens", "output_tokens")}})
        if data.get("is_error"):
            rec["reason"] = "api-error"
            return rec
        result = data.get("result") or ""
        if task["kind"] == "review":
            findings = extract_findings(result)
            (raw_dir / "findings.json").write_text(_dump(findings), encoding="utf-8")
            rec["verdict"] = extract_verdict(result)
            if findings is None:
                rec["reason"] = "no-findings-block"
                return rec
            rec["findings_count"] = len(findings)
        elif task.get("verify"):
            v = _run_process(["/bin/sh", "-c", task["verify"]], str(wt), dict(os.environ), cfg["timeout_s"])
            (raw_dir / "verify.txt").write_text(v["stdout"] + v["stderr"], encoding="utf-8")
            rec["verify_exit"] = v["rc"]
            rec["verify_passed"] = v["rc"] == 0 and not v["timed_out"]
        rec["status"] = "ok"
        if arm["evidence"]:
            transcript = _transcript_dir(wt) / f"{rec['session_id']}.jsonl"
            rec["transcript_found"] = transcript.is_file()
            if not rec["transcript_found"]:
                rec["status"], rec["reason"] = "invalid-arm", "transcript-missing"
                return rec
            rx = re.compile(arm["evidence"])
            with transcript.open(encoding="utf-8", errors="replace") as fh:
                rec["evidence_hits"] = sum(1 for line in fh if rx.search(line))
            if rec["evidence_hits"] == 0:
                rec["status"], rec["reason"] = "invalid-arm", "evidence-missing"
        return rec
    finally:
        if added:
            try:
                _git(str(repo), "worktree", "remove", "--force", str(wt))
            except subprocess.CalledProcessError:
                shutil.rmtree(wt, ignore_errors=True)
                subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)


def main_ab(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench.py ab", description="Run tasks under named arms, k times each.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--preset", default=None, help="built-in arms: kit-vs-vanilla")
    ap.add_argument("--out", default=None, help="run directory, outside the repo (default ./bench-ab-<sha12>)")
    ap.add_argument("--dry-run", action="store_true", help="print the planned runs and write nothing")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(pathlib.Path(args.config), args.preset)
        cfg["sha"] = _git(cfg["repo"], "rev-parse", "--verify", f"{cfg['ref']}^{{commit}}").strip()
        for task in cfg["tasks"]:
            if task["base"]:
                task["base_sha"] = _git(cfg["repo"], "rev-parse", "--verify", f"{task['base']}^{{commit}}").strip()
    except ConfigError as exc:
        print(f"bench ab: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"bench ab: git could not resolve the repo or a ref: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    out = pathlib.Path(args.out or f"bench-ab-{cfg['sha'][:12]}").resolve()
    if _inside(out, pathlib.Path(cfg["repo"])):
        print("bench ab: --out must be outside the repository (its working tree is never written)", file=sys.stderr)
        return 2
    plan = plan_runs(cfg)
    if args.dry_run:
        print(f"planned runs: {len(plan)} ({len(cfg['tasks'])} tasks x {len(cfg['arms'])} arms x k {cfg['k']})")
        print(f"commit: {cfg['sha'][:12]}  model: {cfg['model']}  effort: {cfg['effort']}")
        print("arms: " + ", ".join(a["name"] for a in cfg["arms"]))
        print(f"order (seed {cfg['seed']}):")
        for p in plan:
            print(f"  #{p['order'] + 1} {p['task']} {p['arm']} {p['rep']}")
        print("estimated cost: unknown until the first run")
        return 0
    if (out / "runs.jsonl").exists():
        print(f"bench ab: {out.name}/runs.jsonl already exists; pick another --out", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for task in cfg["tasks"]:
        if task["kind"] == "review" and task.get("base_sha"):
            diff = _git(cfg["repo"], "diff", f"{task['base_sha']}...{cfg['sha']}")
            (out / "raw" / task["id"]).mkdir(parents=True, exist_ok=True)
            (out / "raw" / task["id"] / "diff.patch").write_text(diff, encoding="utf-8")
    (out / "config.json").write_text(_dump(cfg), encoding="utf-8")
    (out / "plan.json").write_text(_dump(plan), encoding="utf-8")
    tasks = {t["id"]: t for t in cfg["tasks"]}
    arms = {a["name"]: a for a in cfg["arms"]}
    counts: dict[str, int] = {}
    with (out / "runs.jsonl").open("a", encoding="utf-8") as fh:
        for p in plan:
            rec = run_one(cfg, tasks[p["task"]], arms[p["arm"]], p["rep"], p["order"], out)
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            print(f"#{p['order'] + 1}/{len(plan)} {p['task']} {p['arm']} {p['rep']}: {rec['status']}"
                  + (f" ({rec['reason']})" if rec["reason"] else ""), file=sys.stderr)
    print(json.dumps({"runs": len(plan), "by_status": counts, "out": str(out)}, sort_keys=True))
    return 0


# ----------------------------------------------------------------------------------------- judge

def _kit_words() -> list[str]:
    words = {"receipt-review", "adversarial-round", "review-comment", "cartography", "cartographer",
             "verify-per-commit", "change-card", "blind-spot adversary", "challenger", "gentle-ai", "engram",
             "judgment-day", "judgment day", "metodo-hook", "metodo"}
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    try:
        import transcript_metrics
        words |= set(getattr(transcript_metrics, "KIT_SKILLS", set()))
    except ImportError:
        pass
    return sorted(words, key=lambda w: (-len(w), w))


def redact(text) -> str:
    """Strip what would tell a judge which arm wrote a finding (epistemic tags, path:line@sha, kit names)."""
    if not isinstance(text, str):
        return text
    text = re.sub(r"[\[(]\s*(?:Measured|Tested|Inferred|Assumed|Unknown)\s*[\])]", "", text)
    text = re.sub(r"([\w./-]+:\d+(?:-\d+)?)@[0-9a-fA-F]{7,40}\b", r"\1", text)
    text = re.sub(r"mcp__[A-Za-z0-9_]+", "[tool]", text)
    text = re.sub(r"\bgeneric-[A-Za-z][A-Za-z-]*", "[agent]", text)
    text = re.sub(r"\[\s*metodo\s*\]", "[redacted]", text, flags=re.I)
    words = "|".join(re.escape(w) for w in _kit_words())
    text = re.sub(rf"(?<![\w-])(?:{words})(?![\w-])", "[redacted]", text, flags=re.I)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def normalize_findings(findings) -> list[dict]:
    """One schema for every arm, ids renumbered F1..Fn, no `label` field, fingerprints stripped."""
    out = []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        line = f.get("line")
        out.append({"id": f"F{len(out) + 1}", "file": redact(str(f.get("file") or "")),
                    "line": line if isinstance(line, int) else None,
                    **{k: redact(str(f.get(k) or "")) for k in ("severity", "category", "claim", "evidence", "fix")}})
    return out


def match_seeded(findings, seeded) -> dict:
    """Seeded recall by severity: a seeded defect is found when a finding names its file, sits within
    its line window and, when the seeded entry names a category, has that category."""
    recall: dict[str, dict] = {}
    for s in seeded or []:
        sev = s.get("severity", "unknown")
        cell = recall.setdefault(sev, {"found": 0, "total": 0})
        cell["total"] += 1
        window = int(s.get("window", 0))
        for f in findings or []:
            if not isinstance(f, dict) or str(f.get("file", "")).lstrip("./") != str(s.get("file", "")).lstrip("./"):
                continue
            if not isinstance(f.get("line"), int) or abs(f["line"] - int(s.get("line", 0))) > window:
                continue
            if s.get("category") and f.get("category") != s["category"]:
                continue
            cell["found"] += 1
            break
    return recall


def render_judge_prompt(template: str, diff: str, a: list, b: list) -> str:
    values = {"DIFF": diff, "FINDINGS_A": json.dumps(a, indent=1, ensure_ascii=False),
              "FINDINGS_B": json.dumps(b, indent=1, ensure_ascii=False)}
    return re.sub(r"<(DIFF|FINDINGS_A|FINDINGS_B)>", lambda m: values[m.group(1)], template)


def _judge_template(cfg: dict) -> str:
    for cand in (HERE / "judge-pairwise.txt", HERE.parent / "protocols" / "prompts" / "judge-pairwise.txt"):
        if cand.is_file():
            return cand.read_text(encoding="utf-8")
    return JUDGE_PROMPT


def parse_judge_reply(stdout: str):
    text = stdout or ""
    try:  # a `claude -p --output-format json` judge wraps its reply in "result"
        wrapped = json.loads(text)
        if isinstance(wrapped, dict) and isinstance(wrapped.get("result"), str):
            text = wrapped["result"]
        elif isinstance(wrapped, dict) and "A" in wrapped:
            return wrapped
    except json.JSONDecodeError:
        pass
    reply = _json_block(text)
    return reply if isinstance(reply, dict) and "A" in reply and "B" in reply else None


def _verdict(value) -> str:
    v = str(value or "").strip().lower()
    return "valid" if v == "valid" else "invalid" if v == "invalid" else "Unknown"


def judge_pairs(cfg: dict) -> list[tuple[str, str]]:
    if cfg.get("comparisons"):
        return [tuple(p) for p in cfg["comparisons"]]
    names = [a["name"] for a in cfg["arms"]]
    pairs = [(n, "vanilla") for n in names if n != "vanilla"] if "vanilla" in names else []
    if "kit-invoked" in names and "native" in names:
        pairs.append(("kit-invoked", "native"))
    return pairs


def cohen_kappa(x: list, y: list):
    n = len(x)
    if n == 0:
        return None
    po = sum(1 for a, b in zip(x, y) if a == b) / n
    pe = sum((x.count(c) / n) * (y.count(c) / n) for c in VERDICTS)
    if pe >= 1.0:
        return None  # both raters constant: kappa is undefined, reported as Unknown
    return _r((po - pe) / (1 - pe))


def _agreement(x: list, y: list) -> dict:
    n = len(x)
    return {"n": n, "percent": _r(sum(1 for a, b in zip(x, y) if a == b) / n) if n else None,
            "kappa": cohen_kappa(x, y)}


def _load_runs(run_dir: pathlib.Path) -> list[dict]:
    runs = [json.loads(line) for line in (run_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return sorted(runs, key=lambda r: (r["task"], r["arm"], r["rep"]))


def main_judge(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench.py judge", description="Seeded matching, then blind pairwise judges.")
    ap.add_argument("--run", required=True)
    args = ap.parse_args(argv)
    run_dir = pathlib.Path(args.run)
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    runs = {(r["task"], r["arm"], r["rep"]): r for r in _load_runs(run_dir)}
    template = _judge_template(cfg)
    seeded_out, judgments = [], []

    def findings_of(task_id, arm, rep):
        p = run_dir / "raw" / task_id / arm / str(rep) / "findings.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    for task in cfg["tasks"]:
        if task["kind"] != "review":
            continue
        for (tid, arm, rep), r in sorted(runs.items()):
            if tid == task["id"] and r["status"] == "ok" and task.get("seeded"):
                seeded_out.append({"task": tid, "arm": arm, "rep": rep,
                                   "recall": match_seeded(findings_of(tid, arm, rep), task["seeded"])})
        diff_path = run_dir / "raw" / task["id"] / "diff.patch"
        diff = diff_path.read_text(encoding="utf-8") if diff_path.is_file() else \
            "(no diff given; judge from the findings and their quoted evidence)"
        for x, y in judge_pairs(cfg):
            for rep in range(cfg["k"]):
                rx, ry = runs.get((task["id"], x, rep)), runs.get((task["id"], y, rep))
                if not rx or not ry or rx["status"] != "ok" or ry["status"] != "ok":
                    judgments.append({"task": task["id"], "pair": [x, y], "rep": rep, "status": "not-run",
                                      "reason": "an arm run is not ok"})
                    continue
                norm = {x: normalize_findings(findings_of(task["id"], x, rep)),
                        y: normalize_findings(findings_of(task["id"], y, rep))}
                for judge in cfg["judges"]:
                    for order, (a, b) in (("AB", (x, y)), ("BA", (y, x))):
                        prompt = render_judge_prompt(template, diff, norm[a], norm[b])
                        jdir = pathlib.Path(tempfile.mkdtemp(prefix="bench-judge-"))
                        try:
                            res = _run_process(judge["command"], str(jdir), dict(os.environ),
                                               cfg.get("judge_timeout_s", 600), stdin_text=prompt)
                        finally:
                            shutil.rmtree(jdir, ignore_errors=True)
                        raw = run_dir / "raw" / "judge" / task["id"] / f"{x}-vs-{y}" / str(rep)
                        raw.mkdir(parents=True, exist_ok=True)
                        (raw / f"{judge['name']}-{order}.txt").write_text(res["stdout"], encoding="utf-8")
                        reply = None if res["timed_out"] else parse_judge_reply(res["stdout"])
                        rec = {"task": task["id"], "pair": [x, y], "rep": rep, "judge": judge["name"],
                               "family": judge["family"], "order": order, "A": a, "B": b}
                        if reply is None:
                            rec.update({"status": "failed", "reason": "timeout" if res["timed_out"] else "no-reply"})
                        else:
                            per = {}
                            for letter, arm in (("A", a), ("B", b)):
                                given = (reply.get(letter) or {}).get("per_finding") or {}
                                per[arm] = {f["id"]: _verdict(given.get(f["id"])) for f in norm[arm]
                                            if f["id"] in given}
                            pref = str(reply.get("preferred", "")).strip()
                            rec.update({"status": "ok", "reason": None, "per_finding": per,
                                        "preferred": a if pref == "A" else b if pref == "B" else "tie"})
                        judgments.append(rec)
    ok = [j for j in judgments if j["status"] == "ok"]
    between_orders = []
    for judge in cfg["judges"]:
        labels: dict = {}
        prefs: dict = {}
        for j in ok:
            if j["judge"] != judge["name"]:
                continue
            key = (j["task"], tuple(j["pair"]), j["rep"])
            prefs.setdefault(key, {})[j["order"]] = j["preferred"]
            for arm, per in sorted(j["per_finding"].items()):
                for fid, v in per.items():
                    labels.setdefault(key + (arm, fid), {})[j["order"]] = v
        both = [v for v in labels.values() if len(v) == 2]
        agree = _agreement([v["AB"] for v in both], [v["BA"] for v in both])
        pboth = [v for v in prefs.values() if len(v) == 2]
        agree["preference_consistency"] = _r(sum(1 for v in pboth if v["AB"] == v["BA"]) / len(pboth)) \
            if pboth else None
        between_orders.append({"judge": judge["name"], **agree})
    between_judges = []
    names = [j["name"] for j in cfg["judges"]]
    for i, j1 in enumerate(names):
        for j2 in names[i + 1:]:
            labels = {}
            for j in ok:
                if j["judge"] in (j1, j2):
                    for arm, per in j["per_finding"].items():
                        for fid, v in per.items():
                            key = (j["task"], tuple(j["pair"]), j["rep"], j["order"], arm, fid)
                            labels.setdefault(key, {})[j["judge"]] = v
            both = [labels[k] for k in sorted(labels) if len(labels[k]) == 2]
            between_judges.append({"judges": [j1, j2], **_agreement([v[j1] for v in both], [v[j2] for v in both])})
    limitations = []
    if len({j["family"] for j in cfg["judges"]}) < 2:
        limitations.append("single-family judges")
    if len(cfg["judges"]) < 2:
        limitations.append("single judge: no between-judge agreement")
    result = {"schema_version": SCHEMA_VERSION, "tool_sha256": _tool_sha256(), "seeded": seeded_out,
              "judgments": judgments, "families": sorted({j["family"] for j in cfg["judges"]}),
              "agreement": {"between_orders": between_orders, "between_judges": between_judges},
              "limitations": limitations}
    (run_dir / "judge.json").write_text(_dump(result), encoding="utf-8")
    print(json.dumps({"judgments": len(judgments), "ok": len(ok), "limitations": limitations}, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------------------- report

def bootstrap_ci(diffs: list[float], seed, resamples: int = 10000) -> tuple[float, float]:
    """Paired task-level bootstrap 95% percentile CI of the mean difference; same seed, same CI."""
    rng = random.Random(str(seed))
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo = means[math.floor(0.025 * (resamples - 1))]
    hi = means[math.ceil(0.975 * (resamples - 1))]
    return _r(lo), _r(hi)


def num(value, label: str, status: str, n: int) -> dict:
    if value is None:
        label = "Unknown"
    return {"value": _r(value), "label": label, "status": status, "n": n}


def _cell_status(runs: list[dict]) -> str:
    if not runs:
        return "not-run"
    if any(r["status"] == "ok" for r in runs):
        return "ok"
    return "invalid-arm" if any(r["status"] == "invalid-arm" for r in runs) else "failed"


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def build_report(run_dir: pathlib.Path) -> dict:
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    runs = _load_runs(run_dir)
    judge_path = run_dir / "judge.json"
    judged = json.loads(judge_path.read_text(encoding="utf-8")) if judge_path.is_file() else None
    k = cfg["k"]
    tasks = {t["id"]: t for t in cfg["tasks"]}
    arm_names = [a["name"] for a in cfg["arms"]]
    validity_label = "Inferred"
    if judged:
        kappas = [a["kappa"] for a in judged["agreement"]["between_judges"] if a["n"]]
        if kappas and all(kp is not None and kp >= 0.6 for kp in kappas):
            validity_label = "Measured"
    verdicts: dict = {}
    for j in (judged or {}).get("judgments", []):
        if j["status"] == "ok":
            for arm, per in j["per_finding"].items():
                verdicts.setdefault((j["task"], arm), []).extend(per.values())
    seeded: dict = {}
    for s in (judged or {}).get("seeded", []):
        for sev, c in s["recall"].items():
            cell = seeded.setdefault((s["task"], s["arm"]), {}).setdefault(sev, {"found": 0, "total": 0})
            cell["found"] += c["found"]
            cell["total"] += c["total"]
    arms_out: dict = {}
    for arm in arm_names:
        a_runs = [r for r in runs if r["arm"] == arm]
        cells, flips = {}, []
        for tid, task in sorted(tasks.items()):
            cr = [r for r in a_runs if r["task"] == tid]
            ok = [r for r in cr if r["status"] == "ok"]
            st, n_ok = _cell_status(cr), len(ok)
            verified = task["kind"] == "change" and bool(task.get("verify"))
            passed = [bool(r.get("verify_passed")) for r in ok] if verified else []
            cell = {"n_runs": len(cr), "n_ok": n_ok, "status": st}
            if verified and ok:
                cell["pass_at_1"] = num(_mean([1.0 if p else 0.0 for p in passed]), "Tested", "ok", n_ok)
            else:
                cell["pass_at_1"] = num(None, "Unknown", st if not ok else "not-run", n_ok)
            if verified and n_ok == k:
                cell["pass_hat_k"] = num(1 if all(passed) else 0, "Tested", "ok", n_ok)
            else:
                cell["pass_hat_k"] = num(None, "Unknown", "not-run" if not verified or not cr else
                                         _cell_status([r for r in cr if r["status"] != "ok"]), n_ok)
            outcomes = passed if verified else [r.get("verdict") for r in ok if r.get("verdict")]
            if len(outcomes) >= 2:
                cell["flip"] = num(1 if len(set(outcomes)) > 1 else 0, "Measured", "ok", len(outcomes))
                flips.append(cell["flip"]["value"])
            else:
                cell["flip"] = num(None, "Unknown", "not-run", len(outcomes))
            costs = [r["cost_usd"] for r in ok if isinstance(r.get("cost_usd"), (int, float))]
            cell["cost_per_run_usd"] = num(_mean(costs), "Measured", st, len(costs))
            # Spend charges every run the arm actually executed, failed ones included (an invalid-arm
            # run did not execute the arm and is reported apart), so cheap failures cannot hide.
            paid = [r["cost_usd"] for r in cr if r["status"] in ("ok", "failed")
                    and isinstance(r.get("cost_usd"), (int, float))]
            cell["spend_usd"] = num(sum(paid) if paid else None, "Measured" if paid else "Unknown",
                                    "ok" if paid else "not-run", len(paid))
            solved = sum(passed)
            if verified and ok and solved:
                cell["cost_per_solved_usd"] = num(sum(paid) / solved, "Measured", "ok", len(paid))
            else:
                cell["cost_per_solved_usd"] = num(None, "Unknown", "ok" if verified and ok else st if not ok
                                                  else "not-run", n_ok)
            counts = [r["findings_count"] for r in ok if isinstance(r.get("findings_count"), int)]
            cell["mean_findings"] = num(_mean(counts), "Measured", st if counts else "not-run", len(counts))
            vs = verdicts.get((tid, arm), [])
            cell["judge_validity"] = num(vs.count("valid") / len(vs) if vs else None, validity_label,
                                         "ok" if vs else "not-run", len(vs))
            cell["seeded_recall"] = {sev: num(c["found"] / c["total"] if c["total"] else None, "Tested", "ok",
                                              c["total"]) for sev, c in sorted(seeded.get((tid, arm), {}).items())}
            cells[tid] = cell
        valid = [r for r in a_runs if r["status"] in ("ok", "invalid-arm")]
        n_ok_arm = sum(1 for r in valid if r["status"] == "ok")
        arms_out[arm] = {
            "activation": num(n_ok_arm / len(valid) if valid else None, "Measured",
                              "ok" if valid else _cell_status(a_runs), len(valid)),
            "flip_rate": num(_mean(flips), "Measured", "ok" if flips else "not-run", len(flips)),
            "tasks": cells,
        }
    comparisons = []
    resamples = int(cfg.get("bootstrap_resamples", 10000))
    for metric in ("pass_at_1", "cost_per_run_usd", "judge_validity"):
        for baseline in ("vanilla", "native"):
            if baseline not in arms_out:
                continue
            for arm in arm_names:
                if arm == baseline:
                    continue
                diffs, n_runs = [], 0
                for tid in sorted(tasks):
                    a, b = arms_out[arm]["tasks"][tid], arms_out[baseline]["tasks"][tid]
                    if a[metric]["value"] is not None and b[metric]["value"] is not None:
                        diffs.append(a[metric]["value"] - b[metric]["value"])
                        n_runs += a["n_ok"] + b["n_ok"]
                comp = {"metric": metric, "arm": arm, "baseline": baseline, "n_tasks": len(diffs), "n_runs": n_runs}
                if diffs:
                    lo, hi = bootstrap_ci(diffs, f"{cfg.get('seed', 0)}|{metric}|{arm}|{baseline}", resamples)
                    comp.update({"diff": num(_mean(diffs), "Measured", "ok", len(diffs)), "ci95": [lo, hi],
                                 "reading": "not shown" if lo <= 0.0 <= hi else "shown",
                                 "attribution": "Inferred"})
                else:
                    comp.update({"diff": num(None, "Unknown", "not-run", 0), "ci95": None, "reading": "not shown",
                                 "attribution": "Unknown"})
                comparisons.append(comp)
    by_status: dict = {}
    for r in runs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    report = {
        "schema_version": SCHEMA_VERSION, "tool_sha256": _tool_sha256(), "sha": cfg.get("sha"),
        "model": cfg.get("model"), "effort": cfg.get("effort"), "k": k, "seed": cfg.get("seed", 0),
        "bootstrap_resamples": resamples, "cost_source": "claude -p total_cost_usd",
        "n": {"tasks": len(tasks), "runs": len(runs), "by_status": by_status},
        "signal": SIGNAL_LINE if k == 1 or len(tasks) < 5 else None,
        "arms": arms_out, "comparisons": comparisons,
        "excluded_runs": [{"task": r["task"], "arm": r["arm"], "rep": r["rep"], "status": r["status"],
                           "reason": r.get("reason")} for r in runs if r["status"] != "ok"],
        "judges": None if not judged else {"families": judged["families"], "limitations": judged["limitations"],
                                           "agreement": judged["agreement"], "validity_label": validity_label},
    }
    return report


def _fmt(n: dict | None) -> str:
    if not n or n["value"] is None:
        return f"Unknown ({n['status'] if n else 'not-run'})"
    return f"{n['value']} [{n['label']}]"


def render_md(rep: dict) -> str:
    lines = ["# A/B benchmark report", "",
             f"Commit `{(rep['sha'] or '')[:12]}` · model {rep['model']} · effort {rep['effort']} · k {rep['k']} · "
             f"seed {rep['seed']} · bootstrap {rep['bootstrap_resamples']} resamples · cost source: {rep['cost_source']}",
             "", "n: {} tasks, {} runs ({})".format(rep["n"]["tasks"], rep["n"]["runs"], ", ".join(
                 f"{k} {v}" for k, v in sorted(rep["n"]["by_status"].items())))]
    if rep["signal"]:
        lines += ["", f"**{rep['signal']}** (k == 1 or fewer than 5 tasks)"]
    lines += ["", "## Per arm and task", "",
              "| arm | task | ok/runs | pass@1 | pass^k | flip | cost/run USD | spend USD | cost/solved USD | findings | "
              "judge validity | status |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, a in sorted(rep["arms"].items()):
        for tid, c in sorted(a["tasks"].items()):
            lines.append(f"| {arm} | {tid} | {c['n_ok']}/{c['n_runs']} | {_fmt(c['pass_at_1'])} | "
                         f"{_fmt(c['pass_hat_k'])} | {_fmt(c['flip'])} | {_fmt(c['cost_per_run_usd'])} | "
                         f"{_fmt(c['spend_usd'])} | {_fmt(c['cost_per_solved_usd'])} | {_fmt(c['mean_findings'])} | "
                         f"{_fmt(c['judge_validity'])} | {c['status']} |")
    lines += ["", "## Activation and stability", "", "| arm | activation | n runs | flip rate | n tasks |",
              "|---|---|---|---|---|"]
    for arm, a in sorted(rep["arms"].items()):
        lines.append(f"| {arm} | {_fmt(a['activation'])} | {a['activation']['n']} | {_fmt(a['flip_rate'])} | "
                     f"{a['flip_rate']['n']} |")
    lines += ["", "## Comparisons (paired task-level bootstrap 95% CI)", "",
              "| metric | arm | vs | n tasks | n runs | diff | 95% CI | reading |", "|---|---|---|---|---|---|---|---|"]
    for c in rep["comparisons"]:
        ci = f"[{c['ci95'][0]}, {c['ci95'][1]}]" if c["ci95"] else "Unknown"
        lines.append(f"| {c['metric']} | {c['arm']} | {c['baseline']} | {c['n_tasks']} | {c['n_runs']} | "
                     f"{_fmt(c['diff'])} | {ci} | {c['reading']} |")
    seeded_rows = [(arm, tid, sev, v) for arm, a in sorted(rep["arms"].items())
                   for tid, c in sorted(a["tasks"].items()) for sev, v in sorted(c["seeded_recall"].items())]
    if seeded_rows:
        lines += ["", "## Seeded recall by severity", "", "| arm | task | severity | recall | n seeded |",
                  "|---|---|---|---|---|"]
        lines += [f"| {arm} | {tid} | {sev} | {_fmt(v)} | {v['n']} |" for arm, tid, sev, v in seeded_rows]
    if rep["judges"]:
        j = rep["judges"]
        lines += ["", "## Judges", "", f"Families: {', '.join(j['families']) or 'none'} · validity label: "
                  f"{j['validity_label']} · limitations: {', '.join(j['limitations']) or 'none'}", "",
                  "| between | n | percent | kappa | preference consistency |", "|---|---|---|---|---|"]
        for a in j["agreement"]["between_orders"]:
            lines.append(f"| orders of {a['judge']} | {a['n']} | {a['percent']} | {a['kappa']} | "
                         f"{a['preference_consistency']} |")
        for a in j["agreement"]["between_judges"]:
            lines.append(f"| {' and '.join(a['judges'])} | {a['n']} | {a['percent']} | {a['kappa']} | |")
    lines += ["", "## Runs not scored", ""]
    if rep["excluded_runs"]:
        lines += ["| task | arm | rep | status | reason |", "|---|---|---|---|---|"]
        lines += [f"| {r['task']} | {r['arm']} | {r['rep']} | {r['status']} | {r['reason']} |"
                  for r in rep["excluded_runs"]]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main_report(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench.py report", description="Labelled report with paired bootstrap CIs.")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default=None, help="directory for report.json and report.md (default: the run dir)")
    args = ap.parse_args(argv)
    run_dir = pathlib.Path(args.run)
    if not (run_dir / "runs.jsonl").is_file() or not (run_dir / "config.json").is_file():
        print("bench report: the run dir needs runs.jsonl and config.json (from `bench.py ab`)", file=sys.stderr)
        return 2
    rep = build_report(run_dir)
    out = pathlib.Path(args.out) if args.out else run_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(_dump(rep), encoding="utf-8")
    (out / "report.md").write_text(render_md(rep), encoding="utf-8")
    print(json.dumps({"runs": rep["n"]["runs"], "tasks": rep["n"]["tasks"], "signal": rep["signal"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    cmds = {"ab": main_ab, "judge": main_judge, "report": main_report}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("usage: bench_ab.py ab|judge|report ...", file=sys.stderr)
        sys.exit(2)
    sys.exit(cmds[sys.argv[1]](sys.argv[2:]))
