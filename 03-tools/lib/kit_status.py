#!/usr/bin/env python3
"""Measured status block of the kit's README (kit-init S11).

The README carries a short table between `<!-- kit-status:start -->` and
`<!-- kit-status:end -->` that only this script writes (evidence or silence:
never typed by hand). Each row carries its epistemic tag:

  measured_at       `git rev-parse --short HEAD` and dirty: yes|no (the
                    fingerprinted files against HEAD); no wall-clock time
  code_fingerprint  sha256 over the sorted (path, git blob hash of the
                    working-tree bytes) of every tracked or untracked,
                    not-ignored file under SCOPE, minus README.md, docs/,
                    out/, baselines/, vendor/, __pycache__/ and the owner's
                    personal files. Working-tree content: stable before a
                    commit, unchanged by committing                [Measured]
  structure         agents, skills, skills the installer ships (read as
                    doctor.py reads them), MCP tools (mcp/catalog.py TOOLS),
                    Claude hook commands (hooks/hooks.settings.json), test
                    cases (unittest loader, nothing runs)           [Measured]
  kit suite         `python3 -m unittest discover tests` from 03-tools with
                    METODO_MEMORY=off, METODO_KIT_STATUS_RUNNING=1   [Tested]
  docs caps         offenders and missing of config/docs-caps.json, over
                    this checkout (docs_root = the kit root)        [Measured]
  init              bin/init.sh --no-fetch on a throwaway Gradle/Kotlin
                    fixture (temp HOME, instance and audit), twice: doctor,
                    smoke, readiness, pending human steps; suggestions
                    depend on the machine; idempotency = second report
                    byte-identical                                   [Tested]

Modes:
  --check  cheap: recompute the fingerprint, structure and docs caps and
           compare them with the README block. Exit 0 current, 1 stale or
           missing (prints what differs and the fix command), 2 usage.
  --write  measure everything and rewrite only the lines between the
           markers (inserted under "## Start here" the first time). Refuses
           (exit 1, README untouched) when the suite FAILED unless
           --allow-failing, which records FAILED as it is; refuses when the
           fingerprinted tree changed while measuring. Same tree, same block.

Usage:
    lib/kit_status.py (--check | --write) [--root <kit>] [--allow-failing]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT_TOOLS = Path(__file__).resolve().parent.parent
KIT_ROOT = KIT_TOOLS.parent
sys.path.insert(0, str(KIT_TOOLS))

from lib import docs_lint  # noqa: E402
from lib.doctor import installer_skills, is_personal_path  # noqa: E402

START = "<!-- kit-status:start -->"
END = "<!-- kit-status:end -->"
FIX_COMMAND = "03-tools/bin/kit-status.sh --write"
SCOPE = ("01-roles", "02-skills", "03-tools/bin", "03-tools/lib", "03-tools/hooks", "03-tools/mcp",
         "03-tools/schemas", "03-tools/config", "03-tools/tests")
SKIP_PARTS = frozenset({"out", "baselines", "vendor", "__pycache__", "docs"})
SKIP_NAMES = frozenset({"README.md"})
CHECKED_ROWS = ("code_fingerprint", "structure", "docs caps")
SUITE_TIMEOUT = 3600
INIT_TIMEOUT = 1800
APP_KT = "package a\n\nfun answer(x: Int): Int {\n    val y = x + 1\n    return y\n}\n"


class StatusError(Exception):
    pass


# ----------------------------------------------------------------------------- git and files

def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise StatusError(f"git {' '.join(args[:2])} failed in {root}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def fingerprinted(rel: str) -> bool:
    if is_personal_path(rel):
        return False
    parts = rel.split("/")
    return parts[-1] not in SKIP_NAMES and not SKIP_PARTS.intersection(parts[:-1])


def _blob(path: Path) -> str:
    data = os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fingerprint(root: Path) -> dict:
    """{digest, files, paths}: the working-tree content of the code the README describes."""
    root = Path(root)
    out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SCOPE)
    paths = sorted({p for p in out.split("\0") if p and fingerprinted(p) and (root / p).is_file()})
    digest = hashlib.sha256()
    for rel in paths:
        digest.update(f"{rel}\0{_blob(root / rel)}\n".encode("utf-8"))
    return {"digest": "sha256:" + digest.hexdigest()[:16], "files": len(paths), "paths": paths}


def measured_at(root: Path) -> dict:
    sha = _git(root, "rev-parse", "--short", "HEAD").strip()
    status = _git(root, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all", "--", *SCOPE)
    changed = [entry[3:] for entry in status.split("\0") if len(entry) > 3]
    return {"sha": sha, "dirty": any(fingerprinted(p) for p in changed)}


# ----------------------------------------------------------------------------- structure

def _py(cwd: Path, code: str) -> int | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("METODO_")}
    env["METODO_MEMORY"] = "off"
    try:
        proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(cwd), capture_output=True, text=True,
                              env=env, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    last = proc.stdout.strip().splitlines()[-1:] if proc.returncode == 0 else []
    return int(last[0]) if last and last[0].isdigit() else None


def _hook_commands(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return sum(1 for groups in data["hooks"].values() for group in groups for hook in group["hooks"]
                   if hook.get("type") == "command")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def structure(root: Path) -> dict:
    root = Path(root)
    tools = root / "03-tools"
    installer = tools / "bin" / "install-claude.sh"
    return {
        "agents": len(list((root / "01-roles" / "agents").glob("generic-*.md"))),
        "skills": len(list((root / "02-skills").glob("*/SKILL.md"))),
        "skills_installed": len(installer_skills(installer)) if installer.is_file() else None,
        "mcp_tools": _py(tools, "import sys; sys.path.insert(0, '.'); from mcp import catalog; "
                                "print(len(catalog.TOOLS))"),
        "claude_hooks": _hook_commands(tools / "hooks" / "hooks.settings.json"),
        "test_cases": _py(tools, "import unittest; "
                                 "print(unittest.defaultTestLoader.discover('tests').countTestCases())"),
    }


def docs_caps(root: Path) -> dict:
    root = Path(root)
    try:
        config = json.loads((root / "03-tools" / "config" / "docs-caps.json").read_text(encoding="utf-8"))
        result = docs_lint.check(root, config["caps"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"offenders": None, "missing": None}
    return {"offenders": len(result["offenders"]), "missing": len(result["missing"])}


# ----------------------------------------------------------------------------- suite

_COUNT = {"failures": "failures", "errors": "errors", "skipped": "skipped", "expected failures": "expected_failures",
          "unexpected successes": "unexpected_successes"}


def parse_unittest(text: str, code: int) -> dict:
    result = {"result": "FAILED", "ran": None, "exit": code, **{k: 0 for k in _COUNT.values()}}
    ran = re.findall(r"^Ran (\d+) tests? in ", text, re.M)
    verdict = re.findall(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", text, re.M)
    if not ran or not verdict:
        return result
    result["ran"] = int(ran[-1])
    word, details = verdict[-1]
    for item in filter(None, (d.strip() for d in details.split(","))):
        key, _, value = item.partition("=")
        if key.strip() in _COUNT and value.strip().isdigit():
            result[_COUNT[key.strip()]] = int(value)
    result["result"] = "OK" if word == "OK" and code == 0 else "FAILED"
    return result


def run_suite(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("METODO_")}
    env.update(METODO_MEMORY="off", METODO_KIT_STATUS_RUNNING="1")
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "tests"], cwd=str(Path(root) / "03-tools"),
                              capture_output=True, text=True, env=env, timeout=SUITE_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return parse_unittest("", 124)
    return parse_unittest(proc.stderr + proc.stdout, proc.returncode)


# ----------------------------------------------------------------------------- init on a fixture

def _fixture_env(tmp: Path) -> dict:
    home = tmp / "home"
    home.mkdir(parents=True)
    gitconfig = tmp / "gitconfig"
    gitconfig.write_text("[user]\n\temail = t@example.com\n\tname = t\n[commit]\n\tgpgsign = false\n"
                         "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("METODO_", "GIT_"))}
    env.update(HOME=str(home), METODO_MEMORY="off", GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
    return env


def _fixture_repo(path: Path, env: dict) -> Path:
    """The same small Gradle/Kotlin repo tests/test_init.py builds."""
    files = {"settings.gradle": "include ':app'\n", "app/src/main/kotlin/A.kt": APP_KT,
             "app/src/test/kotlin/ATest.kt": "package a\n\nfun testAnswer() = check(answer(1) == 2)\n",
             "README.md": "# fixture\n"}
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "initial"]):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)
    return path


def run_init(root: Path) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="kit-status-init-"))
    try:
        env = _fixture_env(tmp)
        repo = _fixture_repo(tmp / "work" / "fixture", env)
        home = Path(env["HOME"])
        argv = ["bash", str(Path(root) / "03-tools" / "bin" / "init.sh"), str(repo), "--instance",
                str(home / "fixture-tools"), "--audit", str(home / "fixture-audit"), "--no-fetch"]
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                             env=env).stdout.strip()
        report_path = home / "fixture-tools" / "out" / "init" / f"{sha}.json"
        reports = []
        code = None
        for _ in range(2):
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=INIT_TIMEOUT,
                                      stdin=subprocess.DEVNULL)
                code = proc.returncode if code is None else code
            except subprocess.TimeoutExpired:
                code = 124 if code is None else code
            reports.append(report_path.read_bytes() if report_path.is_file() else None)
        try:
            report = json.loads(reports[0]) if reports[0] else None
        except ValueError:
            report = None
        if not isinstance(report, dict):
            return {"reported": False, "exit": code}
        suggestions = report.get("suggestions") or []
        return {
            "reported": True, "exit": code,
            "doctor": (report.get("doctor") or {}).get("verdict"),
            "kit_installed": bool((report.get("doctor") or {}).get("kit_installed")),
            "smoke": (report.get("smoke") or {}).get("verdict"),
            "loop_ran": bool((report.get("smoke") or {}).get("loop_ran")),
            "ready_for_benchmark": bool(report.get("ready_for_benchmark")),
            "pending": len(report.get("pending_human_steps") or []),
            "missing": sum(1 for s in suggestions if s.get("status") == "missing"),
            "unknown": sum(1 for s in suggestions if s.get("status") == "unknown"),
            "suggestions": len(suggestions),
            "idempotent": reports[1] is not None and reports[0] == reports[1],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- rendering

def _n(value) -> str:
    return "unknown" if value is None else str(value)


def _b(value: bool) -> str:
    return "true" if value else "false"


def cheap_rows(fp: dict, counts: dict, caps: dict) -> dict:
    return {
        "code_fingerprint": f"| code_fingerprint | `{fp['digest']}` over {fp['files']} files (roles, skills, "
                            "tools, tests) | [Measured] |",
        "structure": f"| structure | {_n(counts['agents'])} agents, {_n(counts['skills'])} skills "
                     f"({_n(counts['skills_installed'])} installed), {_n(counts['mcp_tools'])} MCP tools, "
                     f"{_n(counts['claude_hooks'])} Claude hooks, {_n(counts['test_cases'])} test cases | [Measured] |",
        "docs caps": f"| docs caps | {_n(caps['offenders'])} offenders, {_n(caps['missing'])} missing "
                     "(`config/docs-caps.json` over this checkout) | [Measured] |",
    }


def render(at: dict, fp: dict, counts: dict, caps: dict, suite: dict, init: dict) -> str:
    rows = cheap_rows(fp, counts, caps)
    if suite.get("ran") is None:
        suite_text = f"FAILED: no unittest summary (exit {suite.get('exit')})"
    else:
        suite_text = (f"{suite['result']}: ran {suite['ran']}, failures {suite['failures']}, errors {suite['errors']}, "
                      f"skipped {suite['skipped']}, expected failures {suite['expected_failures']}")
        if suite.get("unexpected_successes"):
            suite_text += f", unexpected successes {suite['unexpected_successes']}"
    if init.get("reported"):
        init_text = (f"doctor {init['doctor']}, kit_installed {_b(init['kit_installed'])}, smoke {init['smoke']}, "
                     f"loop_ran {_b(init['loop_ran'])}, ready_for_benchmark {_b(init['ready_for_benchmark'])}; "
                     f"{init['pending']} pending human steps")
        missing_text = (f"{init['missing']} missing, {init['unknown']} unknown of {init['suggestions']} suggested "
                        "helpers (temp HOME)")
        idem_text = "second run's report byte-identical: " + ("yes" if init["idempotent"] else "no")
    else:
        init_text = f"no report (init exit {init.get('exit')})"
        missing_text = idem_text = "not measured: init wrote no report"
    lines = [
        START,
        "| Kit status (`03-tools/bin/kit-status.sh --write`, never by hand) | Value | Tag |",
        "|---|---|---|",
        f"| measured_at | `{at['sha']}`, dirty: {'yes' if at['dirty'] else 'no'} | [Measured] |",
        rows["code_fingerprint"],
        rows["structure"],
        f"| kit suite | {suite_text} | [Tested] |",
        rows["docs caps"],
        f"| init on a Gradle/Kotlin fixture | {init_text} | [Tested] |",
        f"| init suggestions | {missing_text} | [Measured, this machine] |",
        f"| init idempotency | {idem_text} | [Tested] |",
        END,
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- README block

def _marker_lines(lines: list[str], marker: str) -> list[int]:
    return [i for i, line in enumerate(lines) if line.rstrip("\r") == marker]


def extract_block(text: str) -> str | None:
    lines = text.split("\n")
    starts, ends = _marker_lines(lines, START), _marker_lines(lines, END)
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return None
    return "\n".join(lines[starts[0]:ends[0] + 1])


def replace_block(text: str, block: str) -> str:
    lines = text.split("\n")
    starts, ends = _marker_lines(lines, START), _marker_lines(lines, END)
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
            raise StatusError(f"README.md has {len(starts)} start and {len(ends)} end markers out of order: fix them "
                              f"by hand (one `{START}` line, then one `{END}` line)")
        return "\n".join(lines[:starts[0]] + block.split("\n") + lines[ends[0] + 1:])
    heading = [i for i, line in enumerate(lines) if line.strip() == "## Start here"]
    if len(heading) != 1:
        raise StatusError("README.md has no single '## Start here' section to put the status block under")
    nxt = next((i for i in range(heading[0] + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    end = nxt
    while end > heading[0] + 1 and not lines[end - 1].strip():
        end -= 1
    insert = [""] + block.split("\n") + [""]
    return "\n".join(lines[:end] + insert + lines[nxt:])


# ----------------------------------------------------------------------------- modes

def check(root: Path) -> tuple[bool, list[str]]:
    root = Path(root)
    readme = root / "README.md"
    try:
        block = extract_block(readme.read_text(encoding="utf-8"))
        rows = cheap_rows(fingerprint(root), structure(root), docs_caps(root))
    except (OSError, StatusError) as exc:
        return False, [f"kit-status: {exc}", f"fix: {FIX_COMMAND}"]
    if block is None:
        return False, [f"kit-status: README.md has no kit-status block ({START} ... {END})",
                       f"fix: {FIX_COMMAND} (then commit README.md with the change)"]
    have = {line.split("|")[1].strip(): line for line in block.split("\n") if line.startswith("| ")}
    messages = []
    for name in CHECKED_ROWS:
        if have.get(name) != rows[name]:
            messages.append(f"kit-status: README block is stale: {name}")
            messages.append(f"  README:   {have.get(name, '(missing row)')}")
            messages.append(f"  measured: {rows[name]}")
    if messages:
        messages.append(f"fix: {FIX_COMMAND} (re-measures, rewrites the block; commit README.md with the change)")
        return False, messages
    return True, [f"kit-status: README block current ({rows['code_fingerprint'].split('`')[1]})"]


def write(root: Path, suite_runner=run_suite, init_runner=run_init, allow_failing: bool = False,
          log=lambda msg: print(msg, file=sys.stderr, flush=True)) -> int:
    root = Path(root)
    readme = root / "README.md"
    try:
        text = readme.read_text(encoding="utf-8")
        replace_block(text, START + "\n" + END)  # refuse broken markers before measuring
        before = fingerprint(root)
        at = measured_at(root)
    except (OSError, StatusError) as exc:
        log(f"kit-status: {exc}")
        return 2
    log("kit-status: running the kit suite (METODO_MEMORY=off, METODO_KIT_STATUS_RUNNING=1)")
    suite = suite_runner(root)
    if suite.get("result") != "OK" and not allow_failing:
        log(f"kit-status: the kit suite FAILED (ran {suite.get('ran')}, failures {suite.get('failures')}, errors "
            f"{suite.get('errors')}, exit {suite.get('exit')}): README not written. Fix the suite, or record the "
            "failure as it is with --allow-failing")
        return 1
    log("kit-status: running bin/init.sh twice on a throwaway Gradle/Kotlin fixture")
    init = init_runner(root)
    counts = structure(root)
    after = fingerprint(root)
    if after["digest"] != before["digest"]:
        log(f"kit-status: the fingerprinted tree changed while measuring ({before['digest']} -> {after['digest']}): "
            "README not written; rerun on a quiet tree")
        return 1
    caps = docs_caps(root)
    for _ in range(2):  # the README is itself a capped doc: measure caps with the block in place
        new = replace_block(text, render(at, after, counts, caps, suite, init))
        readme.write_text(new, encoding="utf-8")
        measured = docs_caps(root)
        if measured == caps:
            break
        caps = measured
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit-status.sh", description="Measured status block of the kit's README.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="cheap: is the README block current? (no suite run)")
    mode.add_argument("--write", action="store_true", help="measure everything and rewrite the README block")
    parser.add_argument("--root", default=str(KIT_ROOT), help="the kit root (default: this checkout)")
    parser.add_argument("--allow-failing", action="store_true", help="--write: record a FAILED suite as it is")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    root = Path(args.root).resolve()
    if not (root / "README.md").is_file():
        print(f"kit-status: no README.md in {root}", file=sys.stderr)
        return 2
    if args.check:
        current, messages = check(root)
        print("\n".join(messages), file=sys.stdout if current else sys.stderr)
        return 0 if current else 1
    code = write(root, allow_failing=args.allow_failing)
    if code == 0:
        print(extract_block((root / "README.md").read_text(encoding="utf-8")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
