#!/usr/bin/env python3
"""Skill evals, the native side: what the kit writes for `claude plugin eval` and reads back from it.

The engine is Claude Code's own eval tool (measured on 2.1.330). This module turns a kit case
(lib/skill_eval.py) into the native layout, builds the command line, and reads the two things a
run leaves: the result JSON and one kept directory per run.

What a kit case becomes, in `<plugin>/evals/<case>/`:

  case.yaml     written in JSON syntax, which the tool accepts: `schema_version` "1.1", `name`,
                `tags` (the tier), `runs`, `execution` (the prompt, the limits, `allowed_tools`)
                and the graders inline
  scaffold.sh   only with `setup.files`: copies `files/` (the staged setup) into the run's
                workspace; the tool runs it with `--scaffold`, in both arms
  graders       `expected_skills` -> one `tool_used: Skill` grader each (`trigger-NN`);
                `forbidden_paths` -> one `regex` grader on the trace each (`forbidden-NN`), which
                fails a run that names the path; `expectations` -> one `llm` grader each
                (`expect-NN`). Validators are not graders: the tool has no script grader, so the
                kit runs them itself on the files the run left.

`testdata/` and `validators/` never enter the plugin. `allowed_tools` defaults to the list of the
tool's own template, and `Skill` joins it when the case expects a skill; a tool that needs an
operator grant (GATED_TOOLS, `mcp__*`) is passed to `--allow-tools`. When the runner gives a skill
the kit's MCP server, the server's tools join every case's `allowed_tools` under the names the
plugin exposes them by, and the command line carries `--allow-real-servers`: without it the tool
starts no server of a plugin that has no mock.

Every command line this module builds carries REQUIRED_FLAGS. `--no-publish` is the one that
matters most: without it the tool publishes its HTML report to claude.ai. `--threshold 0` makes
exit 1 mean a failure of the tool and not a low score, which is the kit's to judge.

A kept directory is `<temp>/e-XXXXXX/` with `out/trace.jsonl` (the session, one JSON object per
line) and the workspace under `sealed/home/cwd`, behind a folder at mode 000. One is opened only
when a result of this run names it through `tracePath` and it has that shape under a temporary
folder; it is removed after it was read.

Python 3 stdlib only. The only process this module starts is the binary named by CLAUDE_BIN
(default `claude`), and only through `run_native`, in a process group of its own, so a run that
outlives its timeout is stopped together with every process it started.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import tempfile

import skill_eval

NATIVE_SCHEMA_VERSION = "1.1"
ARMS = ("with", "without")
DEFAULT_RUNS = 3  # the tool's own default, written out so a case never depends on it
DEFAULT_ALLOWED_TOOLS = ("Read", "Glob", "Grep", "Skill")  # the list of `claude plugin eval init --bare`
GATED_TOOLS = ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch")
# A test fails if a built command line lacks any of these.
REQUIRED_FLAGS = ("--no-publish", "--trust-plugin", "--json", "--keep-temp", "--output-dir", "--max-cost-usd")
EXIT_MEANING = {
    1: "a case failed to load, a run could not start or it ended on an API error",
    2: "the cost ceiling was hit or the credential was rejected, so the result is partial",
    130: "it was interrupted",
    143: "it was terminated",
}
SCAFFOLD_SCRIPT = "scaffold.sh"
SCAFFOLD_FILES = "files"
SCAFFOLD_TEXT = """#!/usr/bin/env bash
# Written by the kit's skill-eval runner: stages the case's setup.files into the run's workspace.
# The eval tool runs it with the empty workspace as cwd; the files sit beside this script.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -R "$here/files/." .
"""
# The keys of a tool input that name a path, a pattern or a command line.
PATH_INPUT_KEYS = ("file_path", "path", "notebook_path", "pattern", "glob", "command")
MAX_TRACE_BYTES = 64 * 1024 * 1024
STOP_GRACE_SECONDS = 5  # between asking a run that timed out to end and killing it
MAX_WORKSPACE_BYTES = 256 * 1024 * 1024
MAX_ANSWER_CHARS = 300  # of a tool's result kept with its call
_KEPT_RE = re.compile(r"^e-[A-Za-z0-9_-]{4,16}$")
# What a path is made of inside a tool input; a quote is `\\"` in the trace, so a backslash ends it too.
_PATH_CHAR = r"""[^\s"'\\]"""
_SEGMENT_CHAR = r"""[^/\s"'\\]"""
_NAME_CHAR = "A-Za-z0-9_.-"


class NativeError(Exception):
    """Why the native tool, its result or a kept directory could not be used, in one line."""


def _one_line(value) -> str:
    return " ".join(str(value).split())


def claude_bin() -> str:
    """The binary to start: CLAUDE_BIN or `claude`. A path is made absolute, since the tool runs in the out folder."""
    binary = os.environ.get("CLAUDE_BIN") or "claude"
    return os.path.abspath(binary) if os.sep in binary else binary


# ------------------------------------------------------------------------------ forbidden paths

def glob_pattern(glob: str) -> str:
    """Regex source, valid in Python and in JavaScript, that finds a path under `glob` in a text.

    `*` and `?` stay inside one path segment, `**` crosses segments, and a trailing `/**` also
    matches the folder itself. The path may follow any prefix (the workspace is an absolute path
    in a trace), but not a longer name: `secrets/**` does not match `mysecrets/x`.
    """
    text, body, index = glob.strip("/"), "", 0
    while index < len(text):
        if text.startswith("/**", index) and index + 3 == len(text):
            body, index = body + f"(?:/{_PATH_CHAR}*)?", index + 3
        elif text.startswith("**/", index):
            body, index = body + f"(?:{_PATH_CHAR}*/)?", index + 3
        elif text.startswith("**", index):
            body, index = body + f"{_PATH_CHAR}*", index + 2
        elif text[index] == "*":
            body, index = body + f"{_SEGMENT_CHAR}*", index + 1
        elif text[index] == "?":
            body, index = body + _SEGMENT_CHAR, index + 1
        else:
            body, index = body + re.escape(text[index]), index + 1
    return f"(?:^|[^{_NAME_CHAR}])(?:{body})(?![{_NAME_CHAR}])"


def _names_a_path(key: str) -> bool:
    return key in PATH_INPUT_KEYS or key.lower().endswith(("path", "file", "dir"))


def touched(globs: list[str], tool_uses: list[dict]) -> list[str]:
    """One line per tool call whose input names a path under a forbidden glob, in call order.

    Deterministic, and decided on the trace alone. It sees what a call names (a file, a pattern, a
    command line), not what a broad search returned: `Grep` over the whole workspace is not a hit.
    """
    patterns = [(glob, re.compile(glob_pattern(glob))) for glob in globs]
    hits = []
    for use in tool_uses:
        for key, value in sorted(use["input"].items()):
            if not isinstance(value, str) or not _names_a_path(key):
                continue
            hits += [f"{use['name']} {key}={value[:160]!r} is under {glob!r}"
                     for glob, pattern in patterns if pattern.search(value)]
    return hits


# ------------------------------------------------------------------------------------ the suite

def allowed_tools(case: dict, extra_tools=()) -> list[str]:
    """The tools a run of the case may call; `extra_tools` are the MCP tools the runner serves."""
    tools = list(case["allowed_tools"]) or list(DEFAULT_ALLOWED_TOOLS)
    if case["expected_skills"] and "Skill" not in tools:
        tools.append("Skill")  # a skill cannot trigger in a run that may not call the Skill tool
    return tools + [tool for tool in extra_tools if tool not in tools]


def gated_tools(cases: list[dict], extra_tools=()) -> list[str]:
    """The tools of these cases that the operator has to grant with `--allow-tools`, sorted."""
    return sorted({tool for case in cases for tool in allowed_tools(case, extra_tools)
                   if tool.split("(", 1)[0] in GATED_TOOLS or tool.startswith("mcp__")})


def native_graders(case: dict) -> list[dict]:
    graders = [{"name": f"trigger-{number:02d}", "type": "tool_used", "tool": "Skill", "input_match": re.escape(skill)}
               for number, skill in enumerate(case["expected_skills"], 1)]
    graders += [{"name": f"forbidden-{number:02d}", "type": "regex", "target": "trace", "match": "not_contains",
                 "pattern": f"(?:file_path|notebook_path|path|pattern|glob|command)[^,}}]{{0,300}}?{glob_pattern(glob)}"}
                for number, glob in enumerate(case["forbidden_paths"], 1)]
    graders += [{"name": f"expect-{number:02d}", "type": "llm",
                 "criteria": f"PASS when this is true of the answer, FAIL when it is not: {sentence}"}
                for number, sentence in enumerate(case["expectations"], 1)]
    # A case scored by validators alone has nothing for the tool to grade; it still wants a grader.
    return graders or [{"name": "ran", "type": "regex", "target": "trace", "pattern": "."}]


def runs_of(case: dict, override: int | None = None) -> int:
    return override or case["runs"] or DEFAULT_RUNS


def native_case(case: dict, extra_tools=()) -> dict:
    """The `case.yaml` document of one kit case."""
    execution = {"prompt": case["prompt"], "allowed_tools": allowed_tools(case, extra_tools)}
    execution.update({key: case[key] for key in ("max_turns", "timeout_seconds") if case[key] is not None})
    document = {"schema_version": NATIVE_SCHEMA_VERSION, "name": case["name"],
                "description": f"kit case {case['id']}, tier {case['tier']}", "tags": [case["tier"]],
                "runs": runs_of(case), "execution": execution, "graders": native_graders(case)}
    if case["setup"]["files"]:
        document["context"] = {"scaffold_script": SCAFFOLD_SCRIPT}
    return document


def write_suite(plugin_dir, cases: list[dict], extra_tools=()) -> bool:
    """Write every case under `<plugin_dir>/evals/`; True when any of them has a scaffold script."""
    scaffold = False
    for case in cases:
        folder = pathlib.Path(plugin_dir) / "evals" / case["name"]
        folder.mkdir(parents=True)
        (folder / "case.yaml").write_text(json.dumps(native_case(case, extra_tools), indent=2) + "\n", encoding="utf-8")
        if case["setup"]["files"]:
            skill_eval.stage(case, folder / SCAFFOLD_FILES)  # the same refusals as any staging
            (folder / SCAFFOLD_SCRIPT).write_text(SCAFFOLD_TEXT, encoding="utf-8")
            scaffold = True
    return scaffold


def unmatched_exempt_paths(case: dict) -> list[str]:
    """The `ablation_exempt_paths` globs that match no file the case stages.

    The native ablation removes the plugin and nothing else, so every staged file is in both arms
    already. A glob that matches none of them protects nothing, and the plan says so.
    """
    staged = [target for index, entry in enumerate(case["setup"]["files"])
              for _source, target in skill_eval._plan_entry(case["paths"]["case_dir"], index, entry)[0]]
    return [glob for glob in case["ablation_exempt_paths"]
            if not any(re.search(glob_pattern(glob), path) for path in staged)]


# ------------------------------------------------------------------------------ the command line

def build_argv(claude: str, plugin_dir, out_dir, *, max_cost_usd: float, tier: str | None = None,
               runs: int | None = None, model: str | None = None, judge_model: str | None = None,
               allow_tools=(), scaffold: bool = False, real_servers: bool = False) -> list[str]:
    """The one command line of the runner. Every flag of REQUIRED_FLAGS is always in it.

    `real_servers` lets the tool start the plugin's own MCP server (it has no mock): the server
    runs as the user, outside the sandbox that confines the run's shell tools.
    """
    argv = [claude, "plugin", "eval", str(plugin_dir), "--no-publish", "--trust-plugin", "--keep-temp",
            "--ablation", "with-without", "--threshold", "0", "--max-cost-usd", f"{max_cost_usd:g}",
            "--output-dir", str(out_dir), "--json", str(pathlib.Path(out_dir) / "result.json"),
            "--scaffold" if scaffold else "--no-scaffold"]
    for flag, value in (("--tag", tier), ("--runs", runs), ("--model", model), ("--judge-model", judge_model)):
        if value:
            argv += [flag, str(value)]
    if real_servers:
        argv.append("--allow-real-servers")
    if allow_tools:
        argv += ["--allow-tools", *allow_tools]
    return argv


def _stop_group(proc: subprocess.Popen) -> None:
    """End a run and every process it started: ask first, kill what is still there after the grace."""
    for sign, wait in ((signal.SIGTERM, STOP_GRACE_SECONDS), (signal.SIGKILL, STOP_GRACE_SECONDS)):
        try:
            os.killpg(proc.pid, sign)  # the run leads its own group (start_new_session)
        except OSError:
            pass  # the whole group is gone already
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
        if sign == signal.SIGTERM:  # the tool ended; what it started may have ignored the request
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return


def run_native(argv: list[str], cwd, timeout: float) -> tuple[int, str, str]:
    """Run the tool; (exit code, stdout, stderr). A NativeError when it cannot start or never ends.

    Its output goes to two files, not to pipes: a process the tool started and left behind keeps a
    pipe open, and reading that pipe to its end would hang the runner past any timeout.
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True)
        except OSError as exc:
            raise NativeError(f"cannot start {argv[0]}: {exc.strerror or _one_line(exc)}") from exc
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop_group(proc)
            raise NativeError(f"the native tool did not end within {timeout:g}s and was stopped, "
                              f"with the processes it had started") from exc
        except BaseException:  # an interrupt of the runner must not leave a paid run behind
            _stop_group(proc)
            raise
        out.seek(0)
        err.seek(0)
        return code, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


# ------------------------------------------------------------------------------------ the result

def _shape_problem(raw) -> str | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        return "it is not an object with a 'cases' list"
    for case in raw["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str) or not isinstance(case.get("arms"), dict):
            return "a case has no 'name' or no 'arms'"
        for arm, runs in case["arms"].items():
            if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
                return f"the {arm!r} arm of {case['name']} is not a list of runs"
            for run in runs:
                graders = run.get("graders")
                if not isinstance(graders, list) or not all(isinstance(g, dict) and "name" in g for g in graders):
                    return f"a run of {case['name']} has no list of named graders"
    return None


def read_result(path) -> dict:
    """The result JSON of one invocation; a NativeError when it is missing or not what the tool writes."""
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NativeError(f"the native tool left no result file at {path}") from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise NativeError(f"the result file {path} cannot be read as JSON: {_one_line(exc)}") from exc
    problem = _shape_problem(raw)
    if problem:
        raise NativeError(f"the result file {path} is malformed: {problem}")
    return raw


# ------------------------------------------------------------------------------ kept directories

def _inside(path: str, folder: str) -> bool:
    return path.startswith(folder.rstrip(os.sep) + os.sep)


def kept_dir(trace_path) -> str:
    """The kept directory a result names through `tracePath`; a NativeError when it is not one."""
    if not isinstance(trace_path, str) or not trace_path:
        raise NativeError("the result names no trace for this run")
    path = pathlib.PurePath(trace_path)
    kept = str(path.parent.parent)
    if not path.is_absolute() or (path.parent.name, path.name) != ("out", "trace.jsonl"):
        raise NativeError(f"{trace_path} is not <kept>/out/trace.jsonl, so it was not opened")
    if not _KEPT_RE.match(os.path.basename(kept)) or os.path.islink(kept) or not os.path.isdir(kept):
        raise NativeError(f"{kept} is not a kept directory (a real folder named e-XXXXXX), so it was not opened")
    real = os.path.realpath(kept)
    if not any(_inside(real, os.path.realpath(root)) for root in ("/tmp", tempfile.gettempdir())):
        raise NativeError(f"{kept} is not under a temporary folder, so it was not opened")
    return real


def answer_text(content) -> str:
    """The text of a tool result (a string, or a list of blocks), on one line, at most MAX_ANSWER_CHARS."""
    if isinstance(content, list):
        content = " ".join(block["text"] for block in content
                           if isinstance(block, dict) and isinstance(block.get("text"), str))
    return _one_line(content if isinstance(content, str) else "")[:MAX_ANSWER_CHARS]


def read_trace(kept: str) -> dict:
    """What the kit needs from a trace: the tool calls (each with whether its result was an error and
    an excerpt of that result), the final answer, the tokens and the cwd."""
    path = os.path.join(kept, "out", "trace.jsonl")
    try:
        if os.path.islink(path) or os.path.getsize(path) > MAX_TRACE_BYTES:
            raise NativeError(f"the trace {path} is a link or is larger than {MAX_TRACE_BYTES} bytes")
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise NativeError(f"the trace {path} cannot be read: {getattr(exc, 'strerror', None) or _one_line(exc)}") from exc
    trace = {"tool_uses": [], "final_message": None, "tokens": {}, "cwd": None, "lines": 0}
    failed: set = set()  # ids of the tool calls whose result came back as an error
    answers: dict = {}   # id of a tool call -> an excerpt of its result
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise NativeError(f"line {number} of the trace {path} is not JSON") from exc
        if not isinstance(event, dict):
            continue
        trace["lines"] += 1
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if event.get("type") == "system" and event.get("subtype") == "init":
            trace["cwd"] = event.get("cwd")
        elif event.get("type") == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                    trace["tool_uses"].append({"name": str(block.get("name")), "input": block["input"],
                                               "id": block.get("id"), "error": False})
                elif isinstance(block, dict) and block.get("type") == "text" and trace["final_message"] is None:
                    trace["last_text"] = block.get("text")
        elif event.get("type") == "user":
            answers.update((block.get("tool_use_id"), answer_text(block.get("content"))) for block in content
                           if isinstance(block, dict) and block.get("type") == "tool_result")
            failed.update(block.get("tool_use_id") for block in content
                          if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"))
        elif event.get("type") == "result":
            if isinstance(event.get("result"), str):
                trace["final_message"] = event["result"]
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            trace["tokens"] = {key: usage[key] for key in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens", "output_tokens")
                               if isinstance(usage.get(key), int)}
    if not trace["lines"]:
        raise NativeError(f"the trace {path} is empty")
    for use in trace["tool_uses"]:
        use["answer"] = answers.get(use["id"], "")
        use["error"] = use.pop("id") in failed
    if trace["final_message"] is None:
        trace["final_message"] = trace.get("last_text")
    trace.pop("last_text", None)
    return trace


def copy_workspace(kept: str, dest) -> int:
    """Copy the files a run left (`sealed/home/cwd`) into `dest`; the number of files copied.

    Regular files only: a link is not followed, so nothing outside the workspace is read. The copy
    is what the validators see, so nothing is run inside the kept directory itself.
    """
    sealed = os.path.join(kept, "sealed")
    workspace = os.path.join(sealed, "home", "cwd")
    try:
        os.chmod(kept, 0o700)
        if os.path.isdir(sealed) and not os.path.islink(sealed):
            os.chmod(sealed, 0o700)
        if os.path.islink(workspace) or not os.path.isdir(workspace):
            raise NativeError(f"the kept directory {kept} holds no workspace at sealed/home/cwd")
        copied = total = 0
        for current, dirnames, filenames in os.walk(workspace):
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(current, d))]
            target = os.path.join(str(dest), os.path.relpath(current, workspace))
            os.makedirs(target, exist_ok=True)
            for name in filenames:
                source = os.path.join(current, name)
                if os.path.islink(source) or not os.path.isfile(source):
                    continue
                total += os.path.getsize(source)
                if total > MAX_WORKSPACE_BYTES:
                    raise NativeError(f"the workspace of {kept} is larger than {MAX_WORKSPACE_BYTES} bytes")
                shutil.copy(source, os.path.join(target, name))
                copied += 1
        return copied
    except OSError as exc:
        raise NativeError(f"the workspace of {kept} cannot be read: {exc.strerror or _one_line(exc)}") from exc


def remove_kept(kept: str) -> None:
    """Remove a kept directory this run was given. Its folders come read-only or at mode 000."""
    def unlock(folder: str) -> None:
        try:
            os.chmod(folder, 0o700)
        except OSError:
            pass

    unlock(kept)
    for current, dirnames, _filenames in os.walk(kept):  # top down: a folder is unlocked before it is entered
        for name in dirnames:
            if not os.path.islink(os.path.join(current, name)):
                unlock(os.path.join(current, name))
    shutil.rmtree(kept, ignore_errors=True)
