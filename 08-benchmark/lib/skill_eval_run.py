#!/usr/bin/env python3
"""Skill evals, the runner: one skill's package on Claude Code's own eval tool, scored by the kit.

Usage (through lib/skill_eval.py, which owns the command line):
    lib/skill_eval.py run    [--skill NAME ...] [--tier smoke|core|deep] [--root DIR] [--kit DIR]
                             [--out DIR] [--runs N] [--model M] [--judge-model M]
                             [--max-cost-usd USD] [--no-cache] [--json FILE] [--real]
    lib/skill_eval.py report [--skill NAME ...] [--tier smoke|core|deep] [--root DIR] [--kit DIR]
                             [--out DIR] [--json FILE]

`run` without `--real` prints the plan (per skill: its cases, the two arms, the runs and the cost
ceiling) and spends nothing. With `--real` it prints the ceiling first, then for every skill that
has a case with no stored result: lays the skill's package out as a throwaway plugin holding only
that skill (03-tools/lib/skill_build.py, so what is measured is what ships), writes its cases in
the native layout (lib/skill_eval_native.py), runs `claude plugin eval` once, with and without the
plugin, scores every run, stores one result per case and prints the report. `report` prints the
same report from the stored results and never starts the tool.

What the kit does around the native tool, because the tool cannot: tiers (as tags), `setup.files`
(a scaffold script), script validators, forbidden paths, the cascade, the verdict and the cache.

Scoring of one run, in this order; the first one that applies is the run's status:
  unreadable        its kept directory, its trace or the judge's verdict could not be read
  errored           the tool reports the run ended abnormally
  cheated           a tool call named a `forbidden_paths` entry: decided on the trace by the kit,
                    whatever the native graders said; it scores nothing and is counted apart
  not_triggered     with arm only: a skill of `expected_skills` was not invoked by a Skill call
                    that worked (as `<plugin>:<skill>` or `<skill>`); reported as
                    "not triggered, quality not judged", never as bad quality
  validator_failed  a `validators` script did not exit 0 on the files the run left; it is run as
                    `SCRIPT WORKSPACE TESTDATA` with a copy of the workspace as cwd and a timeout
  judge_rejected    the native `llm` grader of an `expectations` sentence did not pass
  passed            everything that applies passed
A later scorer counts only when the earlier ones passed. The tool runs its judge on every run, so
the judge spend on runs whose judge result did not count is shown apart.

Scores: the with score is the share of triggered runs that passed, the without score the share
of its scored runs that passed, delta their difference. Verdict per skill, on THRESHOLDS:
  not measured  the run failed (the reason is the tool's), nothing is stored, or no run could be scored
  review        it does not trigger when it should (trigger rate under trigger_rate_min);
                its output fails a validator (under validator_pass_min of the triggered runs);
                the judge rejects it (under judge_pass_min of the validated runs);
                it is worse than without it (delta at or under -delta_min);
                it changes nothing (delta under delta_min)
  works         none of the above
A verdict from fewer than runs_per_arm_min runs per arm is labelled a signal.

Store: `<out>/store/<skill>/<case>/<case_hash>.v<RUNNER_VERSION>.json`. A case whose hash has a
stored result with every run readable is reported as cached and not run again, unless
`--no-cache`. `<out>/native/<skill>/<stamp>/` keeps the tool's result, report and output.

Exit: `run` 0, or 1 when a skill's real run failed (one `skill-eval: <skill>: <reason>` line on
stderr and a `not measured` verdict); `report` 0; 2 a usage error or an unreadable case.

Python 3 stdlib only. The only model calls are the ones `claude plugin eval` makes under `--real`.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import time

import skill_eval
import skill_eval_native as native
from skill_eval import CaseError
from skill_eval_native import ARMS, NativeError

RUNNER_VERSION = 1  # part of every stored result's name: raise it when the scoring changes
HERE = pathlib.Path(__file__).resolve().parent
KIT_ROOT = HERE.parent.parent
DEFAULT_MAX_COST_USD = 0.50  # per skill and invocation
VALIDATOR_TIMEOUT_SECONDS = 60
# The one table the verdict is decided on.
THRESHOLDS = {
    "trigger_rate_min": 0.8,    # share of the runs with the skill in which every expected skill was invoked
    "validator_pass_min": 0.8,  # share of the triggered runs whose validators all passed
    "judge_pass_min": 0.8,      # share of the validated runs the judge accepted
    "delta_min": 0.1,           # with minus without: at or above it is better, at or under its negative is worse
    "runs_per_arm_min": 3,      # under it the verdict is a signal
}
STATUS_WORDS = {
    "passed": "passed", "not_triggered": "not triggered, quality not judged", "cheated": "cheated",
    "validator_failed": "failed a validator", "judge_rejected": "rejected by the judge",
    "errored": "ended on an error", "unreadable": "could not be read",
}
UNUSABLE = ("errored", "unreadable")
REASONS = {
    "no_trigger": "it does not trigger when it should (look at the description)",
    "validator": "its output fails a validator",
    "judge": "the judge rejects it",
}
AROUND = ("done by the kit around the native tool: tiers as tags, setup.files through a scaffold script, "
          "script validators on the files each run left, the forbidden-path check on each trace, the cascade, "
          "the verdict and the cache; the tool's own score of each run is kept in the stored result")


def _one_line(value) -> str:
    return " ".join(str(value).split())


def _money(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --------------------------------------------------------------------------- the kit's own tools

def _quiet_import(load):
    """Run an import without leaving bytecode in a folder the runner does not own."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        return load()
    finally:
        sys.dont_write_bytecode = previous


def _skill_build():
    """03-tools/lib/skill_build.py of this checkout, imported by path and never edited from here."""
    if "skill_build" in sys.modules:
        return sys.modules["skill_build"]
    path = KIT_ROOT / "03-tools" / "lib" / "skill_build.py"
    if not path.is_file():
        raise NativeError(f"{path} is not in this checkout, so no skill can be packed")
    spec = importlib.util.spec_from_file_location("skill_build", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["skill_build"] = module
    try:
        _quiet_import(lambda: spec.loader.exec_module(module))
    except Exception as exc:
        sys.modules.pop("skill_build", None)
        raise NativeError(f"{path} cannot be imported: {_one_line(exc)}") from exc
    return module


def _estimator():
    """(count, how a report names it): the kit's token estimator when it can be imported."""
    lib = str(KIT_ROOT / "03-tools" / "lib")
    try:
        sys.path.insert(0, lib)
        try:
            docs_lint = _quiet_import(lambda: importlib.import_module("docs_lint"))
        finally:
            sys.path.remove(lib)
        return docs_lint.token_count, f"{docs_lint.METHOD}, by 03-tools/lib/docs_lint.py"
    except Exception:
        return (lambda text: math.ceil(len(text) / 4)), ("ceil(chars/4), the runner's own copy: "
                                                         "03-tools/lib/docs_lint.py could not be imported")


def skill_tokens(skill_dir) -> tuple[int, str]:
    """The size of a skill in tokens and the estimator used: every text file it ships, not its BUILD.json."""
    count, method = _estimator()
    total = 0
    for current, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in skill_eval.HASH_SKIP)
        for name in sorted(filenames):
            if name in skill_eval.HASH_SKIP or (name == "BUILD.json" and os.path.samefile(current, skill_dir)):
                continue
            try:
                total += count(pathlib.Path(current, name).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    return total, method


# ------------------------------------------------------------------------------------- scoring

def run_validators(case: dict, workspace, timeout: float = VALIDATOR_TIMEOUT_SECONDS) -> list[dict]:
    """Run each validator of the case on `workspace`; one {script, passed, detail} per script.

    A script is called as `SCRIPT WORKSPACE TESTDATA` with the workspace as cwd; TESTDATA is the
    case's answer key folder, or empty when it has none. Exit 0 passes; anything else, a script
    that cannot start and one that outlives the timeout fail.
    """
    testdata = case["paths"]["testdata"] or ""
    env = dict(os.environ, SKILL_EVAL_WORKSPACE=str(workspace), SKILL_EVAL_TESTDATA=testdata,
               SKILL_EVAL_CASE=case["id"], PYTHONDONTWRITEBYTECODE="1")
    results = []
    for relative, script in zip(case["validators"], case["paths"]["validators"]):
        launcher = [sys.executable] if script.endswith(".py") else ["bash"] if script.endswith(".sh") else []
        try:
            proc = subprocess.run([*launcher, script, str(workspace), testdata], cwd=str(workspace), env=env,
                                  capture_output=True, text=True, timeout=timeout)
            said = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
            detail = "" if proc.returncode == 0 else f"exit {proc.returncode}: {_one_line(said[-1]) if said else 'no output'}"
        except subprocess.TimeoutExpired:
            detail = f"timed out after {timeout:g}s"
        except OSError as exc:
            detail = f"cannot start: {exc.strerror or _one_line(exc)}"
        results.append({"script": relative, "passed": not detail, "detail": detail[:300]})
    return results


def score_run(case: dict, arm: str, native_run: dict, scratch) -> dict:
    """One run through the cascade (the module docstring lists the statuses in order)."""
    run = {"status": "", "detail": "", "triggered": None, "cheat": [], "validators": [], "judge": [],
           "judge_counted": False, "cost_usd": _money(native_run.get("costUsd")),
           "judge_cost_usd": _money(native_run.get("judgeCostUsd")), "native_score": native_run.get("score"),
           "native_graders": {str(g["name"]): g.get("passed") for g in native_run["graders"]}, "tokens": {}}

    def end(status: str, detail="") -> dict:
        run.update(status=status, detail=_one_line(detail)[:300])
        return run

    try:
        kept = native.kept_dir(native_run.get("tracePath"))
    except NativeError as exc:
        return end("unreadable", exc)
    workspace = pathlib.Path(scratch) / f"{case['name']}-{arm}-{os.path.basename(kept)}"
    try:
        try:
            trace = native.read_trace(kept)
            if case["validators"]:
                native.copy_workspace(kept, workspace)
        except NativeError as exc:
            return end("unreadable", exc)
        finally:
            native.remove_kept(kept)  # it was named by this run's result and it has been read
        run["tokens"] = trace["tokens"]
        if native_run.get("error"):
            return end("errored", native_run["error"])
        run["cheat"] = native.touched(case["forbidden_paths"], trace["tool_uses"])
        if run["cheat"]:
            return end("cheated", run["cheat"][0])
        if arm == "with" and case["expected_skills"]:
            # A call that came back as an error invoked nothing: the tool accepts any skill name.
            invoked = [use["input"].get("skill") for use in trace["tool_uses"]
                       if use["name"] == "Skill" and not use["error"]]
            invoked = [name for name in invoked if isinstance(name, str)]
            missing = [skill for skill in case["expected_skills"]
                       if not any(name == skill or name.endswith(":" + skill) for name in invoked)]
            run["triggered"] = not missing
            if missing:
                return end("not_triggered", "not invoked: " + ", ".join(missing))
        if case["validators"]:
            run["validators"] = run_validators(case, workspace)
            failed = [result for result in run["validators"] if not result["passed"]]
            if failed:
                return end("validator_failed", f"{failed[0]['script']}: {failed[0]['detail']}")
        if case["expectations"]:
            if native_run.get("skippedPaidGraders"):
                return end("unreadable", "the judge did not run: the cost ceiling skipped it")
            for number in range(1, len(case["expectations"]) + 1):
                name = f"expect-{number:02d}"
                if not isinstance(run["native_graders"].get(name), bool):
                    return end("unreadable", f"the result holds no verdict of the judge for {name}")
                run["judge"].append({"name": name, "passed": run["native_graders"][name]})
            run["judge_counted"] = True
            rejected = [entry["name"] for entry in run["judge"] if not entry["passed"]]
            if rejected:
                return end("judge_rejected", "rejected: " + ", ".join(rejected))
        return end("passed")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def score_case(case: dict, native_result: dict, scratch) -> dict:
    """Both arms of one case of a result, scored."""
    aggregates = native_result.get("aggregates") if isinstance(native_result.get("aggregates"), dict) else {}
    return {"arms": {arm: [score_run(case, arm, run, scratch) for run in native_result["arms"].get(arm) or []]
                     for arm in ARMS},
            "native": {key: aggregates.get(key) for key in ("score", "scoreWithout", "delta")}}


def summarize(records: list[dict]) -> dict:
    """The counts, scores and spend of a skill's stored results."""
    arms = {arm: dict({status: 0 for status in STATUS_WORDS}, runs=0) for arm in ARMS}
    money = {"spend_usd": 0.0, "judge_usd": 0.0, "judge_uncounted_usd": 0.0, "judge_not_triggered_usd": 0.0}
    runs_per_arm, expects = None, False
    for record in records:
        expects = expects or bool(record.get("expected_skills"))
        for arm in ARMS:
            runs = record["arms"].get(arm) or []
            runs_per_arm = len(runs) if runs_per_arm is None else min(runs_per_arm, len(runs))
            for run in runs:
                arms[arm]["runs"] += 1
                arms[arm][run["status"]] += 1
                judge = _money(run.get("judge_cost_usd"))
                money["spend_usd"] += _money(run.get("cost_usd"))
                money["judge_usd"] += judge
                money["judge_uncounted_usd"] += 0 if run.get("judge_counted") else judge
                money["judge_not_triggered_usd"] += judge if run["status"] == "not_triggered" else 0
    used, base = arms["with"], arms["without"]
    checked = used["runs"] - used["cheated"] - sum(used[status] for status in UNUSABLE)
    triggered = checked - used["not_triggered"]
    scored_base = base["runs"] - base["cheated"] - sum(base[status] for status in UNUSABLE)
    with_score = used["passed"] / triggered if triggered else None
    without_score = base["passed"] / scored_base if scored_base else None
    return {"cases": len(records), "arms": arms, "runs_per_arm": runs_per_arm or 0, "expects_trigger": expects,
            "checked": checked, "triggered": triggered, "validated": triggered - used["validator_failed"],
            "with_score": with_score, "without_score": without_score,
            "delta": None if None in (with_score, without_score) else with_score - without_score,
            "cheated": used["cheated"] + base["cheated"],
            "not_counted": sum(arms[arm][status] for arm in ARMS for status in UNUSABLE), **money}


def verdict(summary: dict, selected: int, failure: str | None = None) -> dict:
    """`works`, `review` or `not measured` for one skill, with the reasons in plain words."""
    def answer(name: str, reasons: list[str]) -> dict:
        signal = name != "not measured" and summary["runs_per_arm"] < THRESHOLDS["runs_per_arm_min"]
        return {"verdict": name, "reasons": reasons, "signal": signal}

    used = summary["arms"]["with"]
    if failure:
        return answer("not measured", [failure])
    if not summary["cases"]:
        return answer("not measured", [f"no stored result for its {selected} case(s): run it with `run --real`"])
    if not summary["checked"]:
        if used["runs"] and used["cheated"] == used["runs"]:
            return answer("not measured", ["every run with the skill touched a forbidden path"])
        return answer("not measured", [f"no run with the skill could be scored: {used['cheated']} cheated, "
                                       f"{used['errored']} ended on an error, {used['unreadable']} could not be read"])
    reasons = []
    if summary["expects_trigger"] and summary["triggered"] / summary["checked"] < THRESHOLDS["trigger_rate_min"]:
        reasons.append(REASONS["no_trigger"])
    if summary["triggered"]:
        if summary["validated"] / summary["triggered"] < THRESHOLDS["validator_pass_min"]:
            reasons.append(REASONS["validator"])
        if summary["validated"] and used["passed"] / summary["validated"] < THRESHOLDS["judge_pass_min"]:
            reasons.append(REASONS["judge"])
    if reasons:
        return answer("review", reasons)
    if summary["delta"] is None:
        return answer("not measured", ["no run without the skill could be scored, so there is nothing to compare it with"])
    triggers = "it triggers and " if summary["expects_trigger"] else ""
    if summary["delta"] <= -THRESHOLDS["delta_min"]:
        return answer("review", [f"{triggers}the result is worse than without it"])
    if summary["delta"] < THRESHOLDS["delta_min"]:
        return answer("review", [f"{triggers or 'it '}changes nothing (dead weight: cut or shrink)"])
    return answer("works", [f"{triggers}the result is better than without it"])


# --------------------------------------------------------------------------------------- store

def store_path(out, case: dict, digest: str) -> pathlib.Path:
    return pathlib.Path(out) / "store" / case["skill"] / case["name"] / f"{digest}.v{RUNNER_VERSION}.json"


def load_record(out, case: dict, digest: str) -> dict | None:
    """The stored result of a case under this hash and runner version, or None."""
    try:
        record = json.loads(store_path(out, case, digest).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    arms = record.get("arms") if isinstance(record, dict) else None
    shaped = isinstance(arms, dict) and all(
        isinstance(arms.get(arm), list) and all(isinstance(run, dict) and run.get("status") in STATUS_WORDS
                                                for run in arms[arm]) for arm in ARMS)
    return record if shaped else None


def save_record(out, case: dict, digest: str, record: dict) -> None:
    path = store_path(out, case, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, path)


def reusable(record: dict | None) -> bool:
    """A stored result stands in for a run only when every run of it could be read."""
    return bool(record) and all(record["arms"][arm] for arm in ARMS) and not any(
        run["status"] in UNUSABLE for arm in ARMS for run in record["arms"][arm])


# ---------------------------------------------------------------------------------------- plan

def _context(args) -> dict:
    kit = pathlib.Path(os.path.realpath(args.kit)) if args.kit else KIT_ROOT
    return {"kit": kit,
            "root": pathlib.Path(args.root) if args.root else kit / "08-benchmark" / "evals",
            "out": pathlib.Path(os.path.realpath(args.out)) if args.out else kit / "03-tools" / "out" / "skill-evals"}


def select(root, skills: list[str] | None, tier: str | None) -> dict[str, list[dict]]:
    """The selected cases by skill, sorted; a CaseError when a named skill, or the root, has none."""
    scope = f" of tier {tier}" if tier else ""
    groups: dict[str, list[dict]] = {}
    if skills:
        for skill in sorted(set(skills)):
            groups[skill] = list(skill_eval.iter_cases(root, skill=skill, tier=tier))
            if not groups[skill]:
                raise CaseError(f"no case{scope} for the skill {skill!r} under {root}")
        return groups
    for case in skill_eval.iter_cases(root, tier=tier):
        groups.setdefault(case["skill"], []).append(case)
    if not groups:
        raise CaseError(f"no case{scope} under {root}")
    return groups


def plan_skill(ctx: dict, skill: str, cases: list[dict], use_cache: bool, runs: int | None = None) -> dict:
    """What a run of this skill would do: per case its hash and its stored result, and what is left to run."""
    skill_dir = ctx["kit"] / "02-skills" / skill
    plan = {"skill": skill, "skill_dir": skill_dir, "has_skill": skill_dir.is_dir(), "entries": [], "to_run": []}
    for case in cases:
        digest = skill_eval.case_hash(case, skill_dir) if plan["has_skill"] else None
        stored = load_record(ctx["out"], case, digest) if digest else None
        cached = use_cache and reusable(stored)
        plan["entries"].append({"case": case, "hash": digest, "record": stored, "cached": cached, "fresh": False,
                                "runs": native.runs_of(case, runs)})
        if not cached:
            plan["to_run"].append(case)
    return plan


def plan_lines(plan: dict, ceiling: float) -> list[str]:
    native_runs = sum(len(ARMS) * entry["runs"] for entry in plan["entries"] if not entry["cached"])
    cached = sum(1 for entry in plan["entries"] if entry["cached"])
    lines = [f"{plan['skill']}: {len(plan['entries'])} case(s), {len(plan['to_run'])} to run, {cached} cached; "
             f"arms {', '.join(ARMS)}; {native_runs} native run(s); ceiling USD {ceiling if plan['to_run'] else 0:.2f}"]
    if not plan["has_skill"]:
        lines.append(f"  skill folder not found at {plan['skill_dir']}: a real run reports it as not measured")
    for entry in plan["entries"]:
        case, stored = entry["case"], entry["record"] or {}
        state = (f"cached (stored {stored.get('stored_at')}, {len(stored['arms']['with'])} run(s) per arm; "
                 f"--no-cache runs it again)" if entry["cached"] else f"to run, {entry['runs']} run(s) per arm")
        lines.append(f"  {case['id']} [{case['tier']}]: {state}")
        lines += [f"  {case['id']}: ablation_exempt_paths {glob!r} matches no staged file, so it keeps nothing in both arms"
                  for glob in native.unmatched_exempt_paths(case)]
    return lines


# ------------------------------------------------------------------------------------- real run

def _discard_kept(result: dict) -> None:
    """Remove the kept directories a result names when the result itself is not going to be scored."""
    for case in result["cases"]:
        for runs in case["arms"].values():
            for run in runs:
                try:
                    native.remove_kept(native.kept_dir(run.get("tracePath")))
                except NativeError:
                    pass


def execute(ctx: dict, plan: dict, args) -> None:
    """Run the cases of one skill that have no stored result, score them and store them.

    A NativeError says in one line why the skill could not be measured; nothing of a failed
    invocation is stored as a result.
    """
    skill, cases = plan["skill"], plan["to_run"]
    build = _skill_build()
    work = ctx["out"] / "work" / skill
    native_out = ctx["out"] / "native" / skill / f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        try:
            build.layout_plugin(build.Kit(ctx["kit"]), skill, work / "plugin")
        except build.BuildError as exc:
            raise NativeError(f"the skill cannot be packed: {_one_line(exc)}") from exc
        scaffold = native.write_suite(work / "plugin", cases)
        native_out.mkdir(parents=True)
        argv = native.build_argv(native.claude_bin(), work / "plugin", native_out, max_cost_usd=args.max_cost_usd,
                                 tier=args.tier, runs=args.runs, model=args.model, judge_model=args.judge_model,
                                 allow_tools=native.gated_tools(cases), scaffold=scaffold)
        (native_out / "command.json").write_text(json.dumps(argv) + "\n", encoding="utf-8")
        timeout = 300 + sum(len(ARMS) * native.runs_of(case, args.runs) * (case["timeout_seconds"] or 300) for case in cases)
        code, stdout, stderr = native.run_native(argv, native_out, timeout)
        (native_out / "stdout.txt").write_text(stdout, encoding="utf-8")
        (native_out / "stderr.txt").write_text(stderr, encoding="utf-8")
        result, unread = None, None
        try:
            result = native.read_result(native_out / "result.json")
        except NativeError as exc:
            unread = exc
        if code != 0 or result is None or result.get("partial"):
            if result is not None:
                _discard_kept(result)
            spent = f", USD {_money(result.get('costUsd')):.4f} spent" if result is not None else ""
            said = [line for line in stderr.splitlines() if line.strip()]
            if code != 0:
                meaning = native.EXIT_MEANING.get(code, "a code it does not document")
                reason = f"the native tool exited {code} ({meaning}){spent}: {_one_line(said[-1])[:300] if said else 'no output'}"
            elif result is None:
                reason = str(unread)
            else:
                reason = f"the native tool gave a partial result ({result.get('partialReason') or 'no reason given'}){spent}"
            raise NativeError(f"{reason}; nothing was stored")
        by_name = {case["name"]: case for case in result["cases"]}
        tokens, method = skill_tokens(plan["skill_dir"])
        for entry in plan["entries"]:
            case = entry["case"]
            if entry["cached"] or case["name"] not in by_name:
                continue
            record = score_case(case, by_name.pop(case["name"]), work / "scratch")
            record.update(runner_version=RUNNER_VERSION, case=case["id"], skill=skill, tier=case["tier"],
                          hash=entry["hash"], stored_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                          expected_skills=case["expected_skills"], skill_tokens=tokens, token_method=method,
                          settings={"model": args.model, "judge_model": args.judge_model, "runs": entry["runs"],
                                    "max_cost_usd": args.max_cost_usd, "claude_version": result.get("claudeVersion")})
            save_record(ctx["out"], case, entry["hash"], record)
            entry.update(record=record, fresh=True)
        _discard_kept({"cases": list(by_name.values())})  # runs of cases the kit did not ask for
        missing = [entry["case"]["name"] for entry in plan["entries"] if not entry["cached"] and not entry["fresh"]]
        if missing:
            raise NativeError(f"the result has no case {', '.join(missing)}; they were not stored")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -------------------------------------------------------------------------------------- report

def skill_report(plan: dict, failure: str | None = None) -> dict:
    """Everything the report says about one skill, as data."""
    records = [entry["record"] for entry in plan["entries"] if entry["record"]]
    summary = summarize(records)
    tokens, method = skill_tokens(plan["skill_dir"]) if plan["has_skill"] else (None, "the skill folder is missing")
    cases = []
    for entry in plan["entries"]:
        arms = (entry["record"] or {}).get("arms") or {}
        cases.append({"case": entry["case"]["id"], "tier": entry["case"]["tier"], "hash": entry["hash"],
                      "state": "not run" if not entry["record"] else "run now" if entry["fresh"] else "cached",
                      "arms": {arm: [{"status": run["status"], "detail": run.get("detail", "")} for run in arms.get(arm, [])]
                               for arm in ARMS}})
    return {"skill": plan["skill"], **verdict(summary, len(plan["entries"]), failure), "selected": len(plan["entries"]),
            "cached": sum(1 for case in cases if case["state"] == "cached"), "summary": summary,
            "size_tokens": tokens, "token_method": method, "cases": cases}


def report_lines(report: dict) -> list[str]:
    summary = report["summary"]
    def score(value) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    signal = (f" [signal: {summary['runs_per_arm']} run(s) per arm, a verdict needs {THRESHOLDS['runs_per_arm_min']}]"
              if report["signal"] else "")
    lines = [f"{report['skill']}: {report['verdict']}{signal} - {'; '.join(report['reasons'])}"]
    if summary["cases"]:
        delta = "n/a" if summary["delta"] is None else f"{summary['delta']:+.2f}"
        size = "n/a" if report["size_tokens"] is None else f"{report['size_tokens']} tokens"
        lines += [
            f"  cases: {summary['cases']} measured of {report['selected']} selected ({report['cached']} cached) | "
            f"arms: {', '.join(ARMS)} | runs per arm: {summary['runs_per_arm']}",
            f"  score: with {score(summary['with_score'])}, without {score(summary['without_score'])}, delta {delta} | "
            f"triggered {summary['triggered']} of {summary['checked']} | cheated {summary['cheated']} | "
            f"not counted {summary['not_counted']}",
            f"  size: {size} ({report['token_method']}) | spend: USD {summary['spend_usd']:.4f}, "
            f"judge USD {summary['judge_usd']:.4f} of it",
            f"  judge spend that did not count: USD {summary['judge_uncounted_usd']:.4f}, "
            f"on runs not triggered USD {summary['judge_not_triggered_usd']:.4f} (the native tool runs its judge on every run)",
        ]
    for case in report["cases"]:
        if case["state"] == "not run":
            lines.append(f"  {case['case']} [{case['tier']}]: not run")
            continue
        arms = " | ".join(f"{arm}: {', '.join(STATUS_WORDS[run['status']] for run in case['arms'][arm]) or 'no run'}"
                          for arm in ARMS)
        lines.append(f"  {case['case']} [{case['tier']}]: {arms}{' (cached)' if case['state'] == 'cached' else ''}")
        lines += [f"    {arm} run {number}: {run['detail']}" for arm in ARMS
                  for number, run in enumerate(case["arms"][arm], 1) if run["detail"]]
    return lines


def _print_report(plans: list[dict], failures: dict, json_path) -> None:
    reports = [skill_report(plan, failures.get(plan["skill"])) for plan in plans]
    limits = ", ".join(f"{key} {value:g}" for key, value in THRESHOLDS.items())
    print(f"skill-eval report (runner v{RUNNER_VERSION}; thresholds: {limits})")
    for report in reports:
        print("\n".join(report_lines(report)))
    print(AROUND)
    if json_path:
        data = {"runner_version": RUNNER_VERSION, "thresholds": THRESHOLDS, "skills": reports}
        try:
            pathlib.Path(json_path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            raise CaseError(f"cannot write {json_path}: {exc.strerror or _one_line(exc)}") from exc


# ------------------------------------------------------------------------------------ commands

def cmd_run(args) -> int:
    ctx = _context(args)
    plans = [plan_skill(ctx, skill, cases, use_cache=not args.no_cache, runs=args.runs)
             for skill, cases in select(ctx["root"], args.skill, args.tier).items()]
    paying = [plan for plan in plans if plan["to_run"]]
    total = args.max_cost_usd * len(paying)
    if args.real:  # the ceiling comes before anything that can spend
        print(f"skill-eval: cost ceiling USD {total:.2f} (USD {args.max_cost_usd:.2f} for each of {len(paying)} "
              f"skill(s) to run); the tool checks it before each run, so the run in flight may pass it", flush=True)
    for plan in plans:
        print("\n".join(plan_lines(plan, args.max_cost_usd)), flush=True)
    if not args.real:
        print(f"skill-eval: plan only: nothing was run and nothing was spent; a real run has a ceiling of "
              f"USD {total:.2f} (add --real to run it)")
        return 0
    failures = {}
    for plan in paying:
        try:
            execute(ctx, plan, args)
        except NativeError as exc:
            failures[plan["skill"]] = _one_line(exc)
            print(f"skill-eval: {plan['skill']}: {failures[plan['skill']]}", file=sys.stderr, flush=True)
    _print_report(plans, failures, args.json)
    return 1 if failures else 0


def cmd_report(args) -> int:
    ctx = _context(args)
    plans = [plan_skill(ctx, skill, cases, use_cache=True)
             for skill, cases in select(ctx["root"], args.skill, args.tier).items()]
    _print_report(plans, {}, args.json)
    return 0
