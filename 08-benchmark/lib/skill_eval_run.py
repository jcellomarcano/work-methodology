#!/usr/bin/env python3
"""Skill evals, the runner: one skill's package on Claude Code's own eval tool, scored by the kit.

Usage (through lib/skill_eval.py, which owns the command line; bin/skill-eval.sh is its short form):
    lib/skill_eval.py validate [ROOT] [--kit DIR]
    lib/skill_eval.py run    [SKILL ... | --all] [--skill NAME ...] [--tier smoke|core|deep] [--root DIR] [--kit DIR]
                             [--out DIR] [--runs N] [--model M] [--judge-model M]
                             [--max-cost-usd USD] [--no-cache] [--kit-mcp | --kit-plugin]
                             [--json FILE] [--real]
    lib/skill_eval.py report [--skill NAME ...] [--tier smoke|core|deep] [--root DIR] [--kit DIR]
                             [--out DIR] [--json FILE]

`run` without `--real` prints the plan (per skill: its cases, the two arms, the runs, the cost
ceiling and, when a server makes them two, the native invocations) and spends nothing; `--json FILE` then holds that plan (`mode` "plan"), not a report. With `--real` it prints the ceiling first, then for every skill that
has a case with no stored result: lays the skill's package out as a throwaway plugin holding only
that skill (03-tools/lib/skill_build.py, so what is measured is what ships), writes its cases in
the native layout (lib/skill_eval_native.py), runs `claude plugin eval` once, with and without the
plugin (twice under the kit's MCP server: see below), scores every run, stores one result per case
and prints the report. `report` prints the
same report from the stored results and never starts the tool.

The arm without the skill. With no server in the plugin it is the tool's own ablation: one
invocation with `--ablation with-without`, which removes the whole plugin. That ablation would
also remove an MCP server the plugin carries, and the arm with the skill would be credited for
what the server's tools did. So when a run carries the kit's server (`--kit-mcp` for a skill that
declares its tools, or `--kit-plugin`) the tool is started twice with `--ablation none`: once on
the plugin as it is laid out, and once on a copy of that folder with only `skills/<skill>/`
removed (same name, same `.mcp.json`, same cases, same tools under the same names; under
`--kit-plugin` the other skills stay). The first gives the runs with the skill, the second the
runs without it, and the difference between the arms is the skill alone. The ceiling of the skill
is shared: half for the first invocation, and for the second what is left of the other half once
the first one's spend is known (`share_ceiling`), so the two never add up to more than the ceiling
asked and the overrun stays one run in flight. When the first leaves nothing, the second is not
started and the skill is `not measured`. A failure of either invocation is that skill's failure:
nothing is stored, the line that says it names all that the invocations spent so far, and the
report of that run counts it in the skill's spend (`spend_usd`), names it apart
(`spend_unstored_usd`, a key that is there only then) and prints it (`spend that left no stored
result:`). A ceiling that is not a finite number (`inf`) cannot be shared between two invocations:
under a server the command says so in one line and exits 2 before anything starts; with no server
it is passed on as it always was. The stored result says which way its arm was built (`without_arm`), the report
prints it (`arm without the skill:`), and the tool's own scores kept with it then count the
`tool_used: Skill` grader, which under `--ablation none` is scored and fails in the second.

What the kit does around the native tool, because the tool cannot: tiers (as tags), `setup.files`
(a scaffold script), script validators, forbidden paths, the cascade, the verdict and the cache.

What a skill needs from the kit. A file of the skill that names the kit's tools root is laid out
with this checkout's 03-tools in its place, as the installers render it. A skill whose BUILD.json
declares tools of the kit's MCP server gets that server only with `--kit-mcp`: the plugin is laid
out with this checkout's server, the tool is told to start it (`--allow-real-servers`; it runs as
the user, outside the tool's sandbox) and to allow its declared tools, and the skill's text names
them as the plugin exposes them. Without the flag such a skill runs without its tools: the plan
and the report say so, and its verdict is never `works`.

The kit plugin. `--kit-plugin` evaluates the skill from the kit plugin instead of its own package:
the one plugin of 02-skills/BUILD.json, holding every skill and the kit's MCP server, laid out by
`skill_build.layout_kit_plugin`. The server is the plugin's own (`${CLAUDE_PLUGIN_ROOT}/tools`, not
this checkout's), so the tool is told to start it, as with `--kit-mcp`; the two flags together are a
usage error. The trigger is then read as `<plugin>:<skill>` (or the bare `<skill>`): the name the
skill has in a package of its own is another plugin's skill. The stored result keeps which form was
measured (`package`), the report prints it (`measured as:`), and a result of one form is never
reused for the other. A result measured from the kit plugin also keeps the digest of every file the
plugin held (`kit_plugin_digest`: the skills, the server, the manifest) and is reused only while the
plugin packs to the same digest, so a change of the server or of another packed skill runs it again.

Mocked tools. A case may carry `mocks/<server>/<tool>.md` (lib/skill_eval.py). A run of a skill
uses mocks when a selected case of it has a `mocks/` folder, whatever server flag was given:
`--kit-mcp` and `--kit-plugin` reach only the skills whose cases carry none, and the plan says so
per skill. The plugin is then laid out as under `--kit-mcp` (the server declared,
the skill's text naming the tools as the plugin exposes them), each case's `mocks/` is copied into
its native folder with the tool list file of the mocked tools (what the kit's server lists for
them), the mocked tools join the allowed tools, and the command line says `--mocks record` and
never `--allow-real-servers`: the eval tool answers each mocked tool from its file and
starts no server, so a tool with no mock file is not available to the run. Both arms are the two
invocations described above, on the same mocks, since the tool's documentation does not say
whether its own arm without the plugin keeps them. The stored result says so (`mcp.mocks`,
`mcp.mocked`, `settings.mocks`) and is the same, and reused, with or without a server flag; the
report prints `mocked tools:`. A mocked result is not counted among the runs made without their
tools, so the verdict is computed as for any other; when a declared tool had no mock the report
names it (`tools with no mock:`, `mcp_absent` in the summary), read from what the result stored.

Scoring of one run, in this order; the first one that applies is the run's status:
  errored           the tool reports the run ended abnormally, with or without a trace
  unreadable        its kept directory, its trace or the judge's verdict could not be read
  cheated           a tool call named a `forbidden_paths` entry, or a tool result held a telling
                    line of a staged file under one (skill_eval_native.telling_lines): decided on the
                    trace by the kit, whatever the native graders said; it scores nothing and is
                    counted apart
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
  works         none of the above; `not measured` instead when the skill declares MCP tools and
                a run of it was made without the kit's server and without mocks
A verdict from fewer than runs_per_arm_min scored runs per arm is labelled a signal, and the label
says how many of the runs made were scored: a run that cheated, ended on an error or could not be
read was made and not scored.

Store: `<out>/store/<skill>/<case>/<case_hash>.v<RUNNER_VERSION>.json`. A case whose hash has a
stored result with every run readable, made with the settings asked now (model, judge model, runs
per arm, the kit's MCP server, the kit plugin and, under it, the plugin's own files, the mocks), is reported as
cached and not run again, unless `--no-cache`.
`report` shows what is stored whatever it was run with. `<out>/native/<skill>/<stamp>/` keeps the
tool's result, report and output (under `with/` and `without/` when it was started twice). A run's
trace is removed once it is scored, so its stored result
keeps the names of the tools it called, in order (`tools_called`, a failed call marked), and the
report prints them under a run that did not pass. For the served MCP tools it also keeps an excerpt
of what each call answered (`mcp_answers`): the proof that the server of the plugin answered.

Exit: `run` 0, or 1 when a skill's real run failed for any reason (one `skill-eval: <skill>:
<reason>` line on stderr and a `not measured` verdict; the other skills still run); `report` 0;
2 a usage error or an unreadable case.

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

RUNNER_VERSION = 5  # part of every stored result's name: raise it when the scoring or what a result depends on changes
HERE = pathlib.Path(__file__).resolve().parent
KIT_ROOT = HERE.parent.parent
DEFAULT_MAX_COST_USD = 0.50  # per skill, whatever the number of invocations it takes
VALIDATOR_TIMEOUT_SECONDS = 60
MAX_TOOLS_LISTED = 60  # tool calls of one run kept in its stored result
MAX_ANSWERS_KEPT = 10  # calls to the served MCP tools kept with an excerpt of what each answered
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
UNSCORED = ("cheated", *UNUSABLE)  # a run with one of these was made and scores nothing
REASONS = {
    "no_trigger": "it does not trigger when it should (look at the description)",
    "validator": "its output fails a validator",
    "judge": "the judge rejects it",
}
WITHOUT_TOOLS = ("it ran without its MCP tools (the kit's server was not started), so a better result does not "
                 "show that the skill works: run it again with --kit-mcp")
SETTING_NAMES = {"model": "model", "judge_model": "judge model", "runs": "runs per arm",
                 "kit_mcp": "the kit's MCP server", "kit_plugin": "the kit plugin", "mocks": "the case's mocks"}
# What a result stored before the setting existed was run with; `mocks` is stored only by a run that used them.
SETTING_DEFAULTS = {"kit_plugin": False, "mocks": False}
FORMS = {"kit_plugin": "the kit plugin", "skill_package": "its own package"}
PLUGIN_CHANGED = "another build of the kit plugin (its server or another of its skills changed)"
# How the arm without the skill is built, as a stored result names it and as the report says it.
WITHOUT_ARM = {
    "native_ablation": "the tool's own ablation, which removes the whole plugin",
    "skill_removed": "the same plugin with only skills/{skill}/ removed, in a second invocation of the tool: "
                     "its MCP server and tools stay",
    # never stored: how the report says `skill_removed` of a result whose tools were answered from mocks
    "skill_removed_mocks": "the same plugin with only skills/{skill}/ removed, in a second invocation of the tool: "
                           "the mocked tools stay",
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


def _build_kit(ctx: dict):
    """The checkout under evaluation as skill_build sees it, made once per command."""
    if "build_kit" not in ctx:
        ctx["build_kit"] = _skill_build().Kit(ctx["kit"])
    return ctx["build_kit"]


def declared_needs(ctx: dict, skill: str) -> tuple[list[str], bool]:
    """(the MCP tools the skill's BUILD.json declares, whether a file of it names the kit's tools root).

    A declaration that cannot be read declares nothing here, whatever reading it raised: the run
    itself says why the skill cannot be packed.
    """
    try:
        build = _skill_build()
        declared, _problems = build.load_build(_build_kit(ctx), skill)
    except Exception:  # not only a NativeError: a file nested past the JSON reader raises a RecursionError
        return [], False
    agent = (declared or {}).get("agent_skill")
    if not agent:
        return [], False
    carries = False
    for src in agent["srcs"]:
        try:
            carries = carries or build.TOKEN.encode() in (ctx["kit"] / "02-skills" / skill / src).read_bytes()
        except (OSError, ValueError):
            continue
    return list(agent["mcp_tools"]), carries


def kit_plugin_digest(ctx: dict) -> str | None:
    """The digest of the kit plugin as this checkout packs it now, read once per command.

    None when it cannot be packed: the run itself says why.
    """
    if "kit_plugin_digest" not in ctx:
        try:
            build = _skill_build()
            packed, _problems = build.inspect_kit_plugin(_build_kit(ctx))
            ctx["kit_plugin_digest"] = build.kit_plugin_digest(packed) if packed else None
        except Exception:
            ctx["kit_plugin_digest"] = None
    return ctx["kit_plugin_digest"]


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


def score_run(case: dict, arm: str, native_run: dict, scratch, mcp_prefix: str | None = None,
              plugin: str | None = None) -> dict:
    """One run through the cascade (the module docstring lists the statuses in order).

    `mcp_prefix` is how the names of the served MCP tools start; the calls to them are counted.
    `plugin` is the kit plugin the skill was loaded from: a Skill call then names the skill as
    `<plugin>:<skill>` or `<skill>`, and any other prefix is another plugin's skill.
    """
    error = native_run.get("error")
    run = {"status": "", "detail": "", "triggered": None, "cheat": [], "validators": [], "judge": [], "mcp_calls": 0,
           "tools_called": [], "mcp_answers": [],
           "judge_counted": False, "cost_usd": _money(native_run.get("costUsd")),
           "judge_cost_usd": _money(native_run.get("judgeCostUsd")), "native_score": native_run.get("score"),
           "native_graders": {str(g["name"]): g.get("passed") for g in native_run["graders"]}, "tokens": {}}

    def end(status: str, detail="") -> dict:
        run.update(status=status, detail=_one_line(detail)[:300])
        return run

    try:
        kept = native.kept_dir(native_run.get("tracePath"))
    except NativeError as exc:  # a run that ended abnormally often leaves no trace: it is still that run
        return end("errored", error) if error else end("unreadable", exc)
    workspace = pathlib.Path(scratch) / f"{case['name']}-{arm}-{os.path.basename(kept)}"
    try:
        try:
            trace = native.read_trace(kept)
            if case["validators"]:
                native.copy_workspace(kept, workspace)
        except NativeError as exc:
            return end("errored", error) if error else end("unreadable", exc)
        finally:
            native.remove_kept(kept)  # it was named by this run's result and it has been read
        run["tokens"] = trace["tokens"]
        run["tools_called"] = [use["name"] + (" (error)" if use["error"] else "")
                               for use in trace["tool_uses"][:MAX_TOOLS_LISTED]]
        if mcp_prefix:
            served = [use for use in trace["tool_uses"] if use["name"].startswith(mcp_prefix)]
            run["mcp_calls"] = sum(1 for use in served if not use["error"])
            run["mcp_answers"] = [{"tool": use["name"], "error": use["error"], "answer": use["answer"]}
                                  for use in served[:MAX_ANSWERS_KEPT]]
        if error:
            return end("errored", error)
        run["cheat"] = (native.touched(case["forbidden_paths"], trace["tool_uses"])
                        + native.returned(native.telling_lines(case), trace["tool_uses"]))
        if run["cheat"]:
            return end("cheated", run["cheat"][0])
        if arm == "with" and case["expected_skills"]:
            # A call that came back as an error invoked nothing: the tool accepts any skill name.
            invoked = [use["input"].get("skill") for use in trace["tool_uses"]
                       if use["name"] == "Skill" and not use["error"]]
            invoked = [name for name in invoked if isinstance(name, str)]
            def names(skill: str, name: str) -> bool:
                return name == skill or (name == f"{plugin}:{skill}" if plugin else name.endswith(":" + skill))

            missing = [skill for skill in case["expected_skills"] if not any(names(skill, name) for name in invoked)]
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


def score_case(case: dict, native_result: dict, scratch, mcp_prefix: str | None = None,
               plugin: str | None = None) -> dict:
    """Both arms of one case of a result, scored."""
    aggregates = native_result.get("aggregates") if isinstance(native_result.get("aggregates"), dict) else {}
    return {"arms": {arm: [score_run(case, arm, run, scratch, mcp_prefix, plugin)
                           for run in native_result["arms"].get(arm) or []]
                     for arm in ARMS},
            "native": {key: aggregates.get(key) for key in ("score", "scoreWithout", "delta")}}


def _absent_tools(record: dict) -> list[str]:
    """The declared tools of a mocked result that had no mock file, so no run of it could call them.

    Bare names, sorted; none for a result that was not mocked or does not say which tools had a mock.
    """
    mcp = record.get("mcp") if isinstance(record.get("mcp"), dict) else {}
    declared, mocked = mcp.get("declared"), mcp.get("mocked")
    if not mcp.get("mocks") or not isinstance(declared, list) or not isinstance(mocked, list):
        return []
    return sorted({str(tool).rsplit("__", 1)[-1] for tool in declared} - {str(tool) for tool in mocked})


def summarize(records: list[dict]) -> dict:
    """The counts, scores and spend of a skill's stored results."""
    arms = {arm: dict({status: 0 for status in STATUS_WORDS}, runs=0) for arm in ARMS}
    money = {"spend_usd": 0.0, "judge_usd": 0.0, "judge_uncounted_usd": 0.0, "judge_not_triggered_usd": 0.0}
    runs_per_arm, scored_per_arm, expects = None, None, False
    for record in records:
        expects = expects or bool(record.get("expected_skills"))
        for arm in ARMS:
            runs = record["arms"].get(arm) or []
            runs_per_arm = len(runs) if runs_per_arm is None else min(runs_per_arm, len(runs))
            scored = sum(1 for run in runs if run["status"] not in UNSCORED)
            scored_per_arm = scored if scored_per_arm is None else min(scored_per_arm, scored)
            for run in runs:
                arms[arm]["runs"] += 1
                arms[arm][run["status"]] += 1
                judge = _money(run.get("judge_cost_usd"))
                money["spend_usd"] += _money(run.get("cost_usd"))
                money["judge_usd"] += judge
                money["judge_uncounted_usd"] += 0 if run.get("judge_counted") else judge
                money["judge_not_triggered_usd"] += judge if run["status"] == "not_triggered" else 0
    mocked = sum(1 for record in records if (record.get("mcp") or {}).get("mocks"))  # answered from mock files
    served = [bool((record.get("mcp") or {}).get("served")) for record in records
              if (record.get("mcp") or {}).get("declared") and not (record.get("mcp") or {}).get("mocks")]
    absent = [lacking for lacking in map(_absent_tools, records) if lacking]
    tools = {"without_tools": served.count(False), "mcp_served": served.count(True),
             "mcp_calls": sum(int(run.get("mcp_calls") or 0) for record in records for run in record["arms"].get("with") or []),
             "mcp_calls_without": sum(int(run.get("mcp_calls") or 0) for record in records
                                      for run in record["arms"].get("without") or []),
             **({"mcp_mocked": mocked} if mocked else {}),  # a key that is there only then, and so is the next
             **({"mcp_absent": {"tools": sorted(set().union(*absent)), "cases": len(absent)}} if absent else {})}
    used, base = arms["with"], arms["without"]
    checked = used["runs"] - used["cheated"] - sum(used[status] for status in UNUSABLE)
    triggered = checked - used["not_triggered"]
    scored_base = base["runs"] - base["cheated"] - sum(base[status] for status in UNUSABLE)
    with_score = used["passed"] / triggered if triggered else None
    without_score = base["passed"] / scored_base if scored_base else None
    return {"cases": len(records), "arms": arms, "runs_per_arm": runs_per_arm or 0,
            "scored_per_arm": scored_per_arm or 0, "expects_trigger": expects,
            "checked": checked, "triggered": triggered, "validated": triggered - used["validator_failed"],
            "with_score": with_score, "without_score": without_score,
            "delta": None if None in (with_score, without_score) else with_score - without_score,
            "cheated": used["cheated"] + base["cheated"],
            "not_counted": sum(arms[arm][status] for arm in ARMS for status in UNUSABLE), **money, **tools}


def verdict(summary: dict, selected: int, failure: str | None = None) -> dict:
    """`works`, `review` or `not measured` for one skill, with the reasons in plain words."""
    def answer(name: str, reasons: list[str]) -> dict:
        signal = name != "not measured" and summary["scored_per_arm"] < THRESHOLDS["runs_per_arm_min"]
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
    if summary.get("without_tools"):  # better than nothing, yet not what ships: its tools were missing
        return answer("not measured", [WITHOUT_TOOLS])
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


def settings_differ(record: dict, asked: dict) -> list[str]:
    """What a stored result was run with that is not what is asked now, one phrase per setting."""
    stored = record.get("settings") if isinstance(record.get("settings"), dict) else {}
    was = {key: stored.get(key, SETTING_DEFAULTS.get(key)) for key in SETTING_NAMES}
    return [f"{SETTING_NAMES[key]} {was[key]!r}, now {asked[key]!r}"
            for key in SETTING_NAMES if key in asked and was[key] != asked[key]]


def measured_as(record: dict) -> str:
    """Which form of the skill a stored result measured, as the report says it."""
    package = record.get("package") if isinstance(record.get("package"), dict) else {}
    form = FORMS.get(package.get("form"), FORMS["skill_package"])  # before the kit plugin, every result was a package's
    if not package.get("plugin"):
        return form
    return f"{form} {package['plugin']} {package.get('version')}, invoked as {package.get('invoke')}"


def without_arm(record: dict) -> str:
    """How the arm without the skill of a stored result was built: a key of WITHOUT_ARM."""
    built = record.get("without_arm") if isinstance(record.get("without_arm"), dict) else {}
    return built.get("how") if built.get("how") in WITHOUT_ARM else "native_ablation"  # the only way there was before


def _cut(value: float) -> float:
    """`value` cut down to five significant digits: the six a command line prints never round it up."""
    if value <= 0:
        return 0.0
    scale = 10 ** (4 - math.floor(math.log10(value)))
    return math.floor(value * scale) / scale


def share_ceiling(ceiling: float, invocations: int) -> list[float]:
    """The ceiling of one skill for each of its invocations: together they never pass `ceiling`.

    One invocation has it whole, as it was asked. Two have half each, cut down and never rounded up.
    """
    if invocations < 2:
        return [ceiling] * invocations
    first = _cut(ceiling / 2)
    return [first, _cut(ceiling - first)]


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


def select(root, skills: list[str] | None, tier: str | None, kit=None) -> dict[str, list[dict]]:
    """The selected cases by skill, sorted; a CaseError when a named skill, or the root, has none.

    `kit` is the checkout whose MCP catalog the mocks of a case are checked against.
    """
    scope = f" of tier {tier}" if tier else ""
    groups: dict[str, list[dict]] = {}
    if skills:
        for skill in sorted(set(skills)):
            groups[skill] = list(skill_eval.iter_cases(root, skill=skill, tier=tier, kit=kit))
            if not groups[skill]:
                raise CaseError(f"no case{scope} for the skill {skill!r} under {root}")
        return groups
    for case in skill_eval.iter_cases(root, tier=tier, kit=kit):
        groups.setdefault(case["skill"], []).append(case)
    if not groups:
        raise CaseError(f"no case{scope} under {root}")
    return groups


def plan_skill(ctx: dict, skill: str, cases: list[dict], use_cache: bool, runs: int | None = None,
               asked: dict | None = None, kit_mcp: bool = False, kit_plugin: bool = False) -> dict:
    """What a run of this skill would do: per case its hash and its stored result, and what is left to run.

    `asked` holds the model and the judge model of this run; a stored result made with other
    settings, or from a kit plugin that no longer packs to the same files, is not reused. None (the
    report) compares nothing and packs nothing.
    """
    skill_dir = ctx["kit"] / "02-skills" / skill
    plan = {"skill": skill, "skill_dir": skill_dir, "has_skill": skill_dir.is_dir(), "entries": [], "to_run": [],
            "tools_dir": ctx["kit"] / "03-tools"}
    plan["mcp_tools"], plan["tools_root"] = declared_needs(ctx, skill) if plan["has_skill"] else ([], False)
    # a skill whose cases carry mocks always answers the kit's tools from them: a server flag reaches only the others
    mocked = [case for case in cases if case["mocks_dir"]]
    plan["mocks"] = bool(mocked)
    plan["mock_cases"], plan["mock_tools"] = len(mocked), sorted({tool for case in mocked for tool in case["mocks"]})
    plan["flag_not_used"] = ("--kit-plugin" if kit_plugin else "--kit-mcp" if kit_mcp else None) if plan["mocks"] else None
    # the skill from the kit plugin, which starts its own server
    plan["kit_plugin"] = bool(kit_plugin) and not plan["mocks"]
    # this checkout's server is started only for a skill that declares its tools, and never beside the plugin's
    plan["kit_mcp"] = bool(kit_mcp and plan["mcp_tools"] and not kit_plugin) and not plan["mocks"]
    packed = kit_plugin_digest(ctx) if plan["kit_plugin"] and asked is not None else None
    for case in cases:
        digest = skill_eval.case_hash(case, skill_dir) if plan["has_skill"] else None
        stored = load_record(ctx["out"], case, digest) if digest else None
        case_runs = native.runs_of(case, runs)
        differs = (settings_differ(stored, {**asked, "runs": case_runs, "kit_mcp": plan["kit_mcp"],
                                            "kit_plugin": plan["kit_plugin"], "mocks": plan["mocks"]})
                   if stored and asked is not None else [])
        if (stored and asked is not None and plan["kit_plugin"] and not differs
                and (packed is None or stored.get("kit_plugin_digest") != packed)):
            differs = [PLUGIN_CHANGED]  # the server's files and the other packed skills are not in the case hash
        cached = use_cache and reusable(stored) and not differs
        plan["entries"].append({"case": case, "hash": digest, "record": stored, "cached": cached, "fresh": False,
                                "runs": case_runs, "differs": differs})
        if not cached:
            plan["to_run"].append(case)
    # the tool's own ablation removes the whole plugin: a plugin that carries a server, or stands for one
    # through mocks, keeps it in both arms instead
    plan["without_arm"] = "skill_removed" if plan["kit_mcp"] or plan["kit_plugin"] or plan["mocks"] else "native_ablation"
    plan["invocations"] = 0 if not plan["to_run"] else 2 if plan["without_arm"] == "skill_removed" else 1
    return plan


def plan_lines(plan: dict, ceiling: float) -> list[str]:
    native_runs = sum(len(ARMS) * entry["runs"] for entry in plan["entries"] if not entry["cached"])
    cached = sum(1 for entry in plan["entries"] if entry["cached"])
    # the count of invocations is said only when a server makes it two: with none the line is the one printed before
    twice = f" in {plan['invocations']} native invocation(s)" if plan["invocations"] == 2 else ""
    lines = [f"{plan['skill']}: {len(plan['entries'])} case(s), {len(plan['to_run'])} to run, {cached} cached; "
             f"arms {', '.join(ARMS)}; {native_runs} native run(s){twice}; ceiling USD {ceiling if plan['to_run'] else 0:.2f}"]
    if not plan["has_skill"]:
        lines.append(f"  skill folder not found at {plan['skill_dir']}: a real run reports it as not measured")
    declared = len(plan["mcp_tools"])
    if plan["kit_plugin"]:
        lines.append(f"  {plan['skill']}: --kit-plugin evaluates it from the kit plugin (every skill plus the kit's MCP "
                     f"server, started from the plugin's own files; it runs as you, outside the tool's sandbox) and "
                     f"allows the {declared} tool(s) the skill declares")
    elif plan["kit_mcp"]:
        lines.append(f"  {plan['skill']}: --kit-mcp starts this checkout's MCP server for its runs (it runs as you, outside "
                     f"the tool's sandbox) and allows the {declared} tool(s) the skill declares")
    elif plan["mocks"]:
        bare = sorted(tool.rsplit("__", 1)[-1] for tool in plan["mcp_tools"])
        lacking = [tool for tool in bare if tool not in plan["mock_tools"]]
        lines.append(f"  {plan['skill']}: mocks: {len(plan['mock_tools'])} tool(s) of the kit's MCP server "
                     f"({', '.join(plan['mock_tools']) or 'none by a file of its own'}) answer from the mock files of its "
                     f"case(s), in both arms; the real server is not started"
                     + (f"; {len(lacking)} declared tool(s) have no mock and are not available: {', '.join(lacking)}"
                        if lacking else ""))
    elif declared:
        lines.append(f"  {plan['skill']} declares {declared} MCP tool(s) of the kit's server, which this run does not start: "
                     f"the skill runs without its tools, so its verdict cannot be `works` (add --kit-mcp to start the server)")
    if plan["flag_not_used"]:
        lines.append(f"  {plan['skill']}: {plan['flag_not_used']} does not reach it: a skill whose case(s) carry mocks "
                     f"always answers from them")
    if plan["invocations"] == 2:
        first, second = share_ceiling(ceiling, 2)
        stay = "the mocked tools stay" if plan["mocks"] else "the server and its tools stay"
        lines.append(f"  {plan['skill']}: the arm without the skill runs on the same plugin with only skills/{plan['skill']}/ "
                     f"removed, so {stay} in both arms: the tool is started twice with "
                     f"--ablation none, under USD {first:g} and at most USD {second:g} of the ceiling")
    if plan["tools_root"]:
        where = "the plugin's own tools folder" if plan["kit_plugin"] else str(plan["tools_dir"])
        lines.append(f"  {plan['skill']}: its files name the kit's tools root, rendered to {where} for the run")
    for entry in plan["entries"]:
        case, stored = entry["case"], entry["record"] or {}
        state = (f"cached (stored {stored.get('stored_at')}, {len(stored['arms']['with'])} run(s) per arm; "
                 f"--no-cache runs it again)" if entry["cached"] else f"to run, {entry['runs']} run(s) per arm")
        if entry["differs"] and not entry["cached"]:
            state += f" (the stored result used other settings: {'; '.join(entry['differs'])})"
        lines.append(f"  {case['id']} [{case['tier']}]: {state}")
        lines += [f"  {case['id']}: ablation_exempt_paths {glob!r} matches no staged file, so it keeps nothing in both arms"
                  for glob in native.unmatched_exempt_paths(case)]
    return lines


def plan_data(plan: dict, ceiling: float) -> dict:
    """The plan of one skill as data, for `run --json FILE` without `--real`: what `plan_lines` counts."""
    cases = [{"case": entry["case"]["id"], "tier": entry["case"]["tier"], "hash": entry["hash"],
              "state": "cached" if entry["cached"] else "to run", "runs": entry["runs"],
              "stored_at": (entry["record"] or {}).get("stored_at"), "differs": entry["differs"]}
             for entry in plan["entries"]]
    to_run = [case for case in cases if case["state"] == "to run"]
    # said only for a skill that has a case with mocks: the plan of any other is the one written before
    mocks = ({"mocks": {"used": plan["mocks"], "tools": plan["mock_tools"], "cases": plan["mock_cases"]}}
             if plan["mock_cases"] else {})
    return {"skill": plan["skill"], "has_skill": plan["has_skill"], "arms": list(ARMS), "cases": cases, **mocks,
            "to_run": len(to_run), "cached": len(cases) - len(to_run),
            "native_runs": sum(len(ARMS) * case["runs"] for case in to_run),
            "native_invocations": plan["invocations"], "without_arm": plan["without_arm"],
            "ceiling_usd": ceiling if to_run else 0.0, "ceilings_usd": share_ceiling(ceiling, plan["invocations"]),
            "kit_mcp": plan["kit_mcp"], "kit_plugin": plan["kit_plugin"], "mcp_tools": plan["mcp_tools"]}


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


def _failure(reason: str, spent: float) -> NativeError:
    """Why an invocation left nothing to score, with what the invocations of the skill had spent by then (`spent_usd`)."""
    error = NativeError(reason)
    error.spent_usd = spent
    return error


def _invoke(plugin_dir, native_out, cases: list[dict], args, *, ceiling: float, served, scaffold: bool,
            real_servers: bool, ablation: str = native.ABLATIONS[0], mocks: bool = False) -> dict:
    """Start the native tool once on `plugin_dir`, keep what it said under `native_out`, return its result.

    A NativeError says in one line why the invocation left nothing to score; the kept directories
    its result named are removed before it is raised.
    """
    native_out.mkdir(parents=True)
    argv = native.build_argv(native.claude_bin(), plugin_dir, native_out, max_cost_usd=ceiling,
                             tier=args.tier, runs=args.runs, model=args.model, judge_model=args.judge_model,
                             allow_tools=native.gated_tools(cases, served), scaffold=scaffold,
                             real_servers=real_servers, ablation=ablation, mocks=mocks)
    (native_out / "command.json").write_text(json.dumps(argv) + "\n", encoding="utf-8")
    arms = 1 if ablation == "none" else len(ARMS)
    timeout = 300 + sum(arms * native.runs_of(case, args.runs) * (case["timeout_seconds"] or 300) for case in cases)
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
        raise _failure(f"{reason}; nothing was stored", _money(result.get("costUsd")) if result is not None else 0.0)
    return result


def _merge_arms(used: dict, bare: dict) -> dict:
    """One result with both arms out of two invocations made with `--ablation none`.

    Each reports its one arm as `with`: the first one's runs stay the arm with the skill, the second
    one's become the arm without it. A case that only one of them holds is left out, its kept
    directories removed, and the caller reports it as missing.
    """
    def score(case: dict):
        value = case["aggregates"].get("score") if isinstance(case.get("aggregates"), dict) else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    others = {case["name"]: case for case in bare["cases"]}
    cases, alone = [], []
    for case in used["cases"]:
        other = others.pop(case["name"], None)
        if other is None:
            alone.append(case)
            continue
        with_score, without_score = score(case), score(other)
        cases.append({**case, "arms": {"with": case["arms"].get("with") or [], "without": other["arms"].get("with") or []},
                      "aggregates": {"score": with_score, "scoreWithout": without_score,
                                     "delta": None if None in (with_score, without_score) else with_score - without_score}})
    _discard_kept({"cases": alone + list(others.values())})
    return {**used, "cases": cases}


def _both_arms(work, native_out, skill: str, cases: list[dict], args, **how) -> tuple[dict, list[float]]:
    """The two arms as two invocations with `--ablation none`; (one result with both arms, the two ceilings).

    The second runs on a copy of the laid-out plugin with only `skills/<skill>/` removed, so the
    server, its tools and their names are the same in both arms (the module docstring says why).
    """
    bare = work / "plugin-without"
    shutil.copytree(work / "plugin", bare, symlinks=True)
    if not (bare / "skills" / skill).is_dir():
        raise NativeError(f"the plugin laid out for {skill} holds no skills/{skill}/, so no arm without it can be built")
    shutil.rmtree(bare / "skills" / skill)
    ceilings = share_ceiling(args.max_cost_usd, 2)
    try:
        used = _invoke(work / "plugin", native_out / "with", cases, args, ceiling=ceilings[0], ablation="none", **how)
    except NativeError as exc:
        raise _failure(f"the arm with the skill: {exc}", getattr(exc, "spent_usd", 0.0)) from exc
    spent = _money(used.get("costUsd"))
    ceilings[1] = _cut(min(ceilings[1], args.max_cost_usd - spent))  # an overrun of the first comes out of the second
    if ceilings[1] <= 0:
        _discard_kept(used)
        raise _failure(f"the arm without the skill: it was not started, since the arm with the skill spent "
                       f"USD {spent:.4f} of the ceiling of USD {args.max_cost_usd:.2f} and nothing is left for the arm "
                       f"without it; nothing was stored", spent)
    try:
        without = _invoke(bare, native_out / "without", cases, args, ceiling=ceilings[1], ablation="none", **how)
    except NativeError as exc:
        _discard_kept(used)
        total = spent + getattr(exc, "spent_usd", 0.0)  # the line of the second alone would leave the first one's out
        raise _failure(f"the arm without the skill: {exc}; USD {total:.4f} spent by the two invocations, "
                       f"USD {spent:.4f} of it by the arm with the skill", total) from exc
    return _merge_arms(used, without), ceilings


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
        if plan["kit_plugin"]:
            try:
                laid = build.layout_kit_plugin(_build_kit(ctx), work / "plugin")
            except build.BuildError as exc:
                raise NativeError(f"the kit plugin cannot be packed: {_one_line(exc)}") from exc
            if skill not in laid["skills"]:
                raise NativeError(f"the kit plugin does not hold the skill {skill} (it packs the skills that have a BUILD.json)")
            served, mcp_prefix, plugin = laid["skills"][skill]["mcp_tools"], laid["tool_prefix"], laid["name"]
            package = {"form": "kit_plugin", "plugin": plugin, "version": laid["version"],
                       "invoke": laid["skills"][skill]["invoke"]}
            measured = {"kit_plugin_digest": laid["digest"]}
        else:
            try:
                # a mock stands for a server the plugin declares: the layout is the one of --kit-mcp, the server not started
                laid = build.layout_plugin(_build_kit(ctx), skill, work / "plugin",
                                           local_mcp=plan["kit_mcp"] or plan["mocks"], render_tools=True)
            except build.BuildError as exc:
                raise NativeError(f"the skill cannot be packed: {_one_line(exc)}") from exc
            served = laid["mcp_tools"]  # empty unless --kit-mcp was asked for a skill that declares tools
            if plan["mocks"]:  # only a tool with a mock file is there to call
                served = sorted({build.plugin_tool_name(laid["name"], build.MCP_PREFIX + tool)
                                 for case in cases for tool in case["mocks"]})
            mcp_prefix = (build.plugin_tool_name(laid["name"], build.MCP_PREFIX)
                          if plan["kit_mcp"] or plan["mocks"] else None)
            plugin = None
            package = {"form": "skill_package", "plugin": laid["name"], "version": laid["version"], "invoke": laid["invoke"]}
            measured = {}
        starts_server = plan["kit_mcp"] or plan["kit_plugin"]  # the plugin under test carries a server with no mock
        tool_list, unlisted = skill_eval.kit_tool_list(ctx["kit"]) if plan["mocks"] else (None, None)
        if unlisted:
            raise NativeError(f"the tool list of the kit's MCP server cannot be read, so a mocked tool would have no "
                              f"schema: {unlisted}")
        how = {"served": served, "real_servers": starts_server,
               "scaffold": native.write_suite(work / "plugin", cases, extra_tools=served, mocks=plan["mocks"],
                                              tool_list=tool_list)}
        if plan["mocks"]:  # a key of its own, so the call of a run without mocks is the one made before
            how["mocks"] = True
        if plan["without_arm"] == "skill_removed":
            result, ceilings = _both_arms(work, native_out, skill, cases, args, **how)
        else:
            ceilings = share_ceiling(args.max_cost_usd, 1)
            result = _invoke(work / "plugin", native_out, cases, args, ceiling=ceilings[0], **how)
        by_name = {case["name"]: case for case in result["cases"]}
        tokens, method = skill_tokens(plan["skill_dir"])
        for entry in plan["entries"]:
            case = entry["case"]
            if entry["cached"] or case["name"] not in by_name:
                continue
            record = score_case(case, by_name.pop(case["name"]), work / "scratch", mcp_prefix, plugin)
            # stored only by a run that used mocks: the result of any other run is the one stored before
            mock_mcp = {"mocks": bool(case["mocks_dir"]), "mocked": case["mocks"]} if plan["mocks"] else {}
            mock_setting = {"mocks": True} if plan["mocks"] else {}
            record.update(runner_version=RUNNER_VERSION, case=case["id"], skill=skill, tier=case["tier"],
                          hash=entry["hash"], stored_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                          expected_skills=case["expected_skills"], skill_tokens=tokens, token_method=method,
                          mcp={"declared": plan["mcp_tools"], "served": bool(served) and not plan["mocks"], **mock_mcp},
                          package=package, **measured,
                          without_arm={"how": plan["without_arm"], "invocations": len(ceilings), "ceilings_usd": ceilings},
                          settings={"model": args.model, "judge_model": args.judge_model, "runs": entry["runs"],
                                    "kit_mcp": plan["kit_mcp"], "kit_plugin": plan["kit_plugin"], **mock_setting,
                                    "max_cost_usd": args.max_cost_usd,
                                    "claude_version": result.get("claudeVersion")})
            save_record(ctx["out"], case, entry["hash"], record)
            entry.update(record=record, fresh=True)
        _discard_kept({"cases": list(by_name.values())})  # runs of cases the kit did not ask for
        missing = [entry["case"]["name"] for entry in plan["entries"] if not entry["cached"] and not entry["fresh"]]
        if missing:
            raise NativeError(f"the result has no case {', '.join(missing)}; they were not stored")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -------------------------------------------------------------------------------------- report

def skill_report(plan: dict, failure: str | None = None, unstored_usd: float = 0.0) -> dict:
    """Everything the report says about one skill, as data.

    `unstored_usd` is what the invocations of this run spent and left no stored result for: it is
    counted in the spend and named apart, under a key that is there only when it is above zero.
    """
    records = [entry["record"] for entry in plan["entries"] if entry["record"]]
    summary = summarize(records)
    if unstored_usd > 0:
        summary.update(spend_usd=summary["spend_usd"] + unstored_usd, spend_unstored_usd=unstored_usd)
    tokens, method = skill_tokens(plan["skill_dir"]) if plan["has_skill"] else (None, "the skill folder is missing")
    cases = []
    for entry in plan["entries"]:
        arms = (entry["record"] or {}).get("arms") or {}
        cases.append({"case": entry["case"]["id"], "tier": entry["case"]["tier"], "hash": entry["hash"],
                      "state": "not run" if not entry["record"] else "run now" if entry["fresh"] else "cached",
                      "arms": {arm: [{"status": run["status"], "detail": run.get("detail", ""),
                                      "tools_called": run.get("tools_called") or []} for run in arms.get(arm, [])]
                               for arm in ARMS}})
    calls = f"; {summary['mcp_calls_without']} call(s) to its tools in the runs without the skill"
    def how_built(record: dict) -> str:
        how = without_arm(record)
        return "skill_removed_mocks" if how == "skill_removed" and (record.get("mcp") or {}).get("mocks") else how

    built = [WITHOUT_ARM[how].format(skill=plan["skill"]) + (calls if how.startswith("skill_removed") else "")
             for how in sorted({how_built(record) for record in records})]
    return {"skill": plan["skill"], **verdict(summary, len(plan["entries"]), failure), "selected": len(plan["entries"]),
            "cached": sum(1 for case in cases if case["state"] == "cached"), "summary": summary,
            "measured_as": sorted({measured_as(record) for record in records}), "without_arm": built,
            "size_tokens": tokens, "token_method": method, "cases": cases}


def report_lines(report: dict) -> list[str]:
    summary = report["summary"]
    def score(value) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    made, scored = summary["runs_per_arm"], summary["scored_per_arm"]
    counted = f"{made} run(s) per arm" if scored == made else f"{scored} of {made} run(s) per arm could be scored"
    signal = f" [signal: {counted}, a verdict needs {THRESHOLDS['runs_per_arm_min']}]" if report["signal"] else ""
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
        lines += [f"  measured as: {form}" for form in report["measured_as"]]
        lines += [f"  arm without the skill: {how}" for how in report["without_arm"]]
    if summary.get("spend_unstored_usd"):
        lines.append(f"  spend that left no stored result: USD {summary['spend_unstored_usd']:.4f}, by the native "
                     f"invocations of this run that failed{' (counted in the spend above)' if summary['cases'] else ''}")
    if summary["cases"]:
        if summary["without_tools"]:
            lines.append(f"  without its tools: the skill declares MCP tools and the kit's server was not started in "
                         f"{summary['without_tools']} of {summary['cases']} case(s), so the verdict cannot be `works`")
        if summary.get("mcp_mocked"):
            lines.append(f"  mocked tools: answered from the mock files of {summary['mcp_mocked']} case(s), the real "
                         f"server not started; {summary['mcp_calls']} call(s) to them in the runs with the skill")
        if summary.get("mcp_absent"):  # a mocked run is not counted as one without its tools: the report names them
            lacking = summary["mcp_absent"]
            lines.append(f"  tools with no mock: {len(lacking['tools'])} declared tool(s) had no mock and were not "
                         f"available in {lacking['cases']} of {summary['mcp_mocked']} mocked case(s): "
                         f"{', '.join(lacking['tools'])}; the verdict above does not take this into account")
        if summary["mcp_served"]:
            lines.append(f"  kit MCP server: started for {summary['mcp_served']} case(s); {summary['mcp_calls']} call(s) to "
                         f"its tools in the runs with the skill")
    for case in report["cases"]:
        if case["state"] == "not run":
            lines.append(f"  {case['case']} [{case['tier']}]: not run")
            continue
        arms = " | ".join(f"{arm}: {', '.join(STATUS_WORDS[run['status']] for run in case['arms'][arm]) or 'no run'}"
                          for arm in ARMS)
        lines.append(f"  {case['case']} [{case['tier']}]: {arms}{' (cached)' if case['state'] == 'cached' else ''}")
        for arm in ARMS:
            for number, run in enumerate(case["arms"][arm], 1):
                if run["status"] == "passed":
                    continue
                lines += [f"    {arm} run {number}: {run['detail']}"] if run["detail"] else []
                lines += [f"    {arm} run {number} called: {', '.join(run['tools_called'])}"] if run["tools_called"] else []
    return lines


def _write_json(json_path, data: dict) -> None:
    try:
        pathlib.Path(json_path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CaseError(f"cannot write {json_path}: {exc.strerror or _one_line(exc)}") from exc


def _print_report(plans: list[dict], failures: dict, json_path, unstored: dict | None = None) -> None:
    reports = [skill_report(plan, failures.get(plan["skill"]), (unstored or {}).get(plan["skill"], 0.0)) for plan in plans]
    limits = ", ".join(f"{key} {value:g}" for key, value in THRESHOLDS.items())
    print(f"skill-eval report (runner v{RUNNER_VERSION}; thresholds: {limits})")
    for report in reports:
        print("\n".join(report_lines(report)))
    print(AROUND)
    if json_path:
        _write_json(json_path, {"runner_version": RUNNER_VERSION, "thresholds": THRESHOLDS, "skills": reports})


# ------------------------------------------------------------------------------------ commands

def cmd_run(args) -> int:
    ctx = _context(args)
    if args.kit_plugin and args.kit_mcp:
        raise CaseError("pass --kit-plugin or --kit-mcp, not both: the kit plugin starts its own server")
    asked = {"model": args.model, "judge_model": args.judge_model}
    plans = [plan_skill(ctx, skill, cases, use_cache=not args.no_cache, runs=args.runs, asked=asked, kit_mcp=args.kit_mcp,
                        kit_plugin=args.kit_plugin)
             for skill, cases in select(ctx["root"], args.skill, args.tier, ctx["kit"]).items()]
    paying = [plan for plan in plans if plan["to_run"]]
    twice = [plan for plan in plans if plan["invocations"] == 2]
    if not math.isfinite(args.max_cost_usd) and twice:
        carries = "mocked tools" if all(plan["mocks"] for plan in twice) else "the kit's MCP server"
        raise CaseError(f"--max-cost-usd {args.max_cost_usd:g} cannot be shared between the two invocations a run with "
                        f"{carries} makes: give a finite number")
    total = args.max_cost_usd * len(paying)
    if args.real:  # the ceiling comes before anything that can spend
        print(f"skill-eval: cost ceiling USD {total:.2f} (USD {args.max_cost_usd:.2f} for each of {len(paying)} "
              f"skill(s) to run); the tool checks it before each run, so the run in flight may pass it", flush=True)
    for plan in plans:
        print("\n".join(plan_lines(plan, args.max_cost_usd)), flush=True)
    if not args.real:
        if args.json:  # the plan as data: without it the flag would be dropped in silence
            _write_json(args.json, {"runner_version": RUNNER_VERSION, "mode": "plan", "max_cost_usd": args.max_cost_usd,
                                    "ceiling_usd": total, "skills": [plan_data(plan, args.max_cost_usd) for plan in plans]})
        print(f"skill-eval: plan only: nothing was run and nothing was spent; a real run has a ceiling of "
              f"USD {total:.2f} (add --real to run it)")
        return 0
    failures, unstored = {}, {}
    for plan in paying:
        try:
            execute(ctx, plan, args)
        except Exception as exc:  # whatever stops one skill is that skill's failure; the others still run
            failures[plan["skill"]] = (_one_line(exc) if isinstance(exc, NativeError) else
                                       f"unexpected error: {type(exc).__name__}: {_one_line(exc)}")
            if plan["invocations"] == 2:  # with one invocation its line names the spend and the report stays as it was
                unstored[plan["skill"]] = getattr(exc, "spent_usd", 0.0)
            print(f"skill-eval: {plan['skill']}: {failures[plan['skill']]}", file=sys.stderr, flush=True)
    _print_report(plans, failures, args.json, unstored)
    return 1 if failures else 0


def cmd_report(args) -> int:
    ctx = _context(args)
    plans = [plan_skill(ctx, skill, cases, use_cache=True)
             for skill, cases in select(ctx["root"], args.skill, args.tier, ctx["kit"]).items()]
    _print_report(plans, {}, args.json)
    return 0
