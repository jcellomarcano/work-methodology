#!/usr/bin/env python3
"""Skill evals: the kit-owned case format, with its validator, loader, staging and content hash.

A case is a folder `<root>/<skill>/<case>/` (the kit's root is `08-benchmark/evals/`):

  case.json     what the case is and how it is scored (the keys below)
  prompt.md     the task given to the agent, not empty
  setup/        optional: fixed files the run starts from
  testdata/     optional: the answer key of the validators; never staged, always a forbidden path
  validators/   optional: scripts that check the files a run left

`case.json` is one JSON object. `schema_version` (the integer 1), `skill` (the name of the folder
the case sits in) and `tier` (`smoke`, `core` or `deep`) are required, and so is at least one
scorer: a non-empty `expected_skills`, `validators` or `expectations`. Any other key is a problem.

  expected_skills        list of skill names that must be invoked
  validators             list of script paths inside the case folder, e.g. "validators/check.py"
  expectations           list of plain sentences an independent judge checks the answer against
  setup                  {"files": [{"from": PATH, "to": PATH}, ...]}: `from` is a file or a folder
                         inside the case folder, `to` is where it lands in the run's working
                         directory ("." puts the content of a folder at its root)
  forbidden_paths        list of relative globs a run may neither read nor write
  ablation_exempt_paths  list of relative globs that stay in both arms of the ablation
  max_turns, timeout_seconds, runs   positive integers; allowed_tools   list of tool names

Example (`evals/demo-skill/smoke-basic/case.json`):

  {"schema_version": 1, "skill": "demo-skill", "tier": "smoke",
   "expected_skills": ["demo-skill"],
   "setup": {"files": [{"from": "setup/notes.txt", "to": "notes.txt"},
                       {"from": "setup/src", "to": "src"}]},
   "forbidden_paths": ["secrets/**"], "ablation_exempt_paths": ["notes.txt"],
   "validators": ["validators/check_output.py"],
   "expectations": ["The answer names the function that was changed."],
   "max_turns": 8, "timeout_seconds": 300, "allowed_tools": ["Read", "Edit", "Skill"], "runs": 1}

Every path of a case is relative and stays inside the case folder, also after its symlinks are
resolved. A `setup.files` entry that reaches `testdata/` is a problem, and so are two entries
that stage a file at the same destination. A link to a file inside the case is staged as a
regular file; a link to a folder is refused.

Functions the runner builds on:
  validate_case(case_dir) -> list[str]   the problems of one case, one line each, [] when valid
  load_case(case_dir) -> dict            the validated case: every key above (absent lists are [],
                                         absent limits None), `name`, `id` ("<skill>/<case>"),
                                         `prompt` (the text) and `paths` (absolute: `case_dir`,
                                         `prompt`, `testdata` or None, `setup_files`, `validators`);
                                         "testdata/**" joins `forbidden_paths` when testdata/ exists
  iter_cases(root, skill=None, tier=None)   the loaded cases, sorted by skill then case folder
  stage(case, dest) -> list[str]         copies `setup.files` into dest, returns what it wrote
  case_hash(case, skill_dir) -> str      sha256 over the relative paths and bytes of the case's
                                         files and the skill's files: no mtime, no absolute path
A CaseError is raised for a case that is not valid or a path that cannot be read.

Usage:
    lib/skill_eval.py validate [ROOT]
    lib/skill_eval.py run [--skill NAME ...] [--tier TIER] [--kit-mcp | --kit-plugin] [--real] ...
    lib/skill_eval.py report [--skill NAME ...] [--tier TIER] ...

`validate` prints `<skill>/<case>: <problem>` lines, sorted, then one summary line.
Exit 0 every case is valid; 1 any problem; 2 a usage error or an unreadable path, as one
`skill-eval:` line on stderr.

`run` and `report` live in lib/skill_eval_run.py, which documents their flags, the scoring and the
verdict. `run` prints a plan and spends nothing unless `--real` is given; `report` never spends.

Python 3 stdlib only. This module makes no network or model call and starts no `claude` process;
the only command that does is `run --real`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

SCHEMA_VERSION = 1
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent / "evals"
TIERS = ("smoke", "core", "deep")
REQUIRED_KEYS = ("schema_version", "skill", "tier")
SCORER_KEYS = ("expected_skills", "validators", "expectations")
STRING_LIST_KEYS = ("expected_skills", "expectations", "allowed_tools")
GLOB_LIST_KEYS = ("forbidden_paths", "ablation_exempt_paths")
LIMIT_KEYS = ("max_turns", "timeout_seconds", "runs")
KNOWN_KEYS = REQUIRED_KEYS + STRING_LIST_KEYS + GLOB_LIST_KEYS + LIMIT_KEYS + ("setup", "validators")
# The answer key: never staged, and forbidden to every run of a case that has one.
TESTDATA_DIR = "testdata"
TESTDATA_GLOB = "testdata/**"
# Left behind by tools, not part of a case or a skill: they would change the hash for no reason.
HASH_SKIP = ("__pycache__", ".DS_Store")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class CaseError(Exception):
    """A case that is not valid, or a path that cannot be read or written safely."""


class UsageError(Exception):
    pass


def _one_line(exc) -> str:
    return " ".join(str(exc).split())


# ---------------------------------------------------------------------------------------- paths

def _is_relative(value) -> bool:
    """A non-empty POSIX path that is not absolute and has no `..` part (lexical check only)."""
    if not isinstance(value, str) or not value.strip() or "\\" in value or "\0" in value:
        return False
    if value.startswith(("/", "~")) or _DRIVE_RE.match(value):
        return False
    return ".." not in value.split("/")


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _join(base: str, relative: str) -> str:
    return os.path.join(base, *pathlib.PurePosixPath(relative).parts)


def _case_error(case_id: str, problems: list[str]) -> CaseError:
    """The one wording of a refused case: its id, then every problem."""
    return CaseError(f"{case_id}: " + "; ".join(problems))


def _reaches_testdata(real: str, case_real: str, testdata: str) -> bool:
    """True when `real` is the answer key, sits in it or holds it, under any spelling of its name.

    The spelling is compared case-folded on every machine: a file system that ignores case opens
    `TESTDATA/` as the answer key, and a case must mean the same thing on the others.
    """
    first = pathlib.PurePath(os.path.relpath(real, case_real)).parts[:1]
    if first and first[0].casefold() == TESTDATA_DIR:
        return True
    return _inside(real, testdata) or (os.path.isdir(testdata) and _inside(testdata, real))


def _answer_key_spellings(case_real: str) -> list[str]:
    """One problem per folder entry that names the answer key under another spelling."""
    try:
        names = sorted(os.listdir(case_real))
    except OSError:
        return []
    return [f"the answer key folder must be spelled {TESTDATA_DIR!r}, found {name!r}"
            for name in names if name != TESTDATA_DIR and name.casefold() == TESTDATA_DIR]


def _plan_entry(case_real: str, index: int, entry: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Every (resolved source file, relative destination) one `setup.files` entry stages, and its problems.

    Validation and staging share this walk, so a link planted after a case was validated is
    still refused when the case is staged.
    """
    label = f"setup.files[{index}]"
    testdata = os.path.realpath(os.path.join(case_real, TESTDATA_DIR))
    pairs: list[tuple[str, str]] = []
    problems: list[str] = []

    def visit(path: str, shown: str, target: pathlib.PurePosixPath, top: bool) -> None:
        real = os.path.realpath(path)
        if not _inside(real, case_real):
            problems.append(f"{label}.from: {shown!r} leaves the case folder through a symlink")
        elif _reaches_testdata(real, case_real, testdata):
            problems.append(f"{label}.from: {shown!r} stages testdata/, the answer key, which is never staged")
        elif not os.path.exists(real):
            problems.append(f"{label}.from: {shown!r} does not exist")
        elif os.path.isdir(real):
            if os.path.islink(path):
                problems.append(f"{label}.from: {shown!r} is a symlink to a folder, which is not staged")
                return
            try:
                names = sorted(os.listdir(real))
            except OSError as exc:  # a folder the user cannot list is their error to read, in one line
                problems.append(f"{label}.from: {shown!r} cannot be read: {exc.strerror or _one_line(exc)}")
                return
            for name in names:
                visit(os.path.join(path, name), f"{shown.rstrip('/')}/{name}", target / name, False)
        elif not os.path.isfile(real):
            problems.append(f"{label}.from: {shown!r} is not a regular file")
        elif top and not target.parts:
            problems.append(f"{label}.to: {entry['to']!r} must name a file because 'from' is a file")
        else:
            pairs.append((real, target.as_posix()))

    visit(_join(case_real, entry["from"]), entry["from"], pathlib.PurePosixPath(entry["to"]), True)
    return pairs, problems


# ---------------------------------------------------------------------------------- validation

def _check_setup(case_real: str, setup, problems: list[str]) -> None:
    if not isinstance(setup, dict) or not isinstance(setup.get("files", []), list):
        problems.append(f"'setup' must be an object with a 'files' list, got {setup!r}")
        return
    problems.extend(f"setup: unknown key {key!r}" for key in sorted(setup) if key != "files")
    landed: dict[str, int] = {}  # destination -> the first entry that stages a file there
    for index, entry in enumerate(setup.get("files", [])):
        label = f"setup.files[{index}]"
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("from", "to")):
            problems.append(f"{label} must be an object with string 'from' and 'to', got {entry!r}")
            continue
        problems.extend(f"{label}: unknown key {key!r}" for key in sorted(entry) if key not in ("from", "to"))
        lexical = []
        if not _is_relative(entry["from"]):
            lexical.append(f"{label}.from: {entry['from']!r} must be a relative path inside the case folder")
        if not _is_relative(entry["to"]):
            lexical.append(f"{label}.to: {entry['to']!r} must be a relative path inside the working directory")
        if lexical:
            problems.extend(lexical)
            continue
        pairs, faults = _plan_entry(case_real, index, entry)
        problems.extend(faults)
        for _source, target in pairs:
            if landed.setdefault(target, index) != index:  # the later file would silently replace the earlier one
                problems.append(f"{label}.to: {target!r} is also the destination of setup.files[{landed[target]}]: "
                                f"two files cannot land on one path")


def _check_validators(case_real: str, validators, problems: list[str]) -> None:
    if not isinstance(validators, list):
        problems.append(f"'validators' must be a list of script paths, got {validators!r}")
        return
    for index, script in enumerate(validators):
        label = f"validators[{index}]: {script!r}"
        if not _is_relative(script):
            problems.append(f"{label} must be a relative path inside the case folder")
            continue
        real = os.path.realpath(_join(case_real, script))
        if not _inside(real, case_real):
            problems.append(f"{label} leaves the case folder through a symlink")
        elif not os.path.exists(real):
            problems.append(f"{label} does not exist")
        elif not os.path.isfile(real):
            problems.append(f"{label} is not a file")


def _check_prompt(case_real: str, problems: list[str]) -> str:
    path = os.path.join(case_real, "prompt.md")
    if not os.path.isfile(path):
        problems.append("prompt.md is missing")
        return ""
    if not _inside(os.path.realpath(path), case_real):
        problems.append("prompt.md leaves the case folder through a symlink")
        return ""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        problems.append(f"prompt.md cannot be read: {_one_line(exc)}")
        return ""
    if not text.strip():
        problems.append("prompt.md is empty")
    return text


def _inspect(case_dir) -> tuple[list[str], dict | None]:
    """The problems of a case and, when there is none, the loaded case."""
    case_real = os.path.realpath(case_dir)
    # A case is named by where it was found, not by where a link leads: `<skill>/<case>` is the
    # path the owner sees and the one `skill` is checked against. Its files are read where they are.
    given = os.path.abspath(case_dir)
    folder, name = os.path.basename(os.path.dirname(given)), os.path.basename(given)
    path = os.path.join(case_real, "case.json")
    if not os.path.isfile(path):
        return ["case.json is missing"], None
    if not _inside(os.path.realpath(path), case_real):
        return ["case.json leaves the case folder through a symlink"], None
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [f"case.json is not valid JSON: {_one_line(exc)}"], None
    if not isinstance(raw, dict):
        return [f"case.json must be a JSON object, got {type(raw).__name__}"], None

    problems = [f"unknown key {key!r}" for key in sorted(raw) if key not in KNOWN_KEYS]
    problems += [f"missing required key {key!r}" for key in REQUIRED_KEYS if key not in raw]
    if "schema_version" in raw and (type(raw["schema_version"]) is not int or raw["schema_version"] != SCHEMA_VERSION):
        problems.append(f"'schema_version' must be {SCHEMA_VERSION}, got {raw['schema_version']!r}")
    if "skill" in raw:
        if not isinstance(raw["skill"], str) or not raw["skill"].strip():
            problems.append(f"'skill' must be a non-empty string, got {raw['skill']!r}")
        elif raw["skill"] != folder:
            problems.append(f"'skill' is {raw['skill']!r} but the case sits in the folder {folder!r}")
    if "tier" in raw and raw["tier"] not in TIERS:
        problems.append(f"'tier' must be one of {', '.join(TIERS)}, got {raw['tier']!r}")
    for key in STRING_LIST_KEYS:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append(f"{key!r} must be a list of non-empty strings, got {value!r}")
    for key in GLOB_LIST_KEYS:
        value = raw.get(key, [])
        if not isinstance(value, list):
            problems.append(f"{key!r} must be a list of relative globs, got {value!r}")
            continue
        problems.extend(f"{key}[{index}]: {glob!r} must be a relative glob"
                        for index, glob in enumerate(value) if not _is_relative(glob))
    for key in LIMIT_KEYS:
        value = raw.get(key)
        if key in raw and (type(value) is not int or value < 1):
            problems.append(f"{key!r} must be a positive integer, got {value!r}")
    _check_setup(case_real, raw.get("setup", {}), problems)
    _check_validators(case_real, raw.get("validators", []), problems)
    if not any(raw.get(key) for key in SCORER_KEYS):
        problems.append(f"no scorer: needs at least one of {', '.join(SCORER_KEYS)}")
    prompt = _check_prompt(case_real, problems)
    problems += _answer_key_spellings(case_real)
    if problems:
        return problems, None

    case = {key: list(raw.get(key, [])) for key in STRING_LIST_KEYS + GLOB_LIST_KEYS + ("validators",)}
    case.update({key: raw.get(key) for key in LIMIT_KEYS})
    case.update({key: raw[key] for key in REQUIRED_KEYS})
    case["setup"] = {"files": [dict(entry) for entry in raw.get("setup", {}).get("files", [])]}
    testdata = os.path.join(case_real, TESTDATA_DIR)
    has_testdata = os.path.isdir(testdata)
    if has_testdata and TESTDATA_GLOB not in case["forbidden_paths"]:
        case["forbidden_paths"].append(TESTDATA_GLOB)
    case.update(name=name, id=f"{folder}/{name}", prompt=prompt)
    case["paths"] = {
        "case_dir": case_real,
        "prompt": os.path.join(case_real, "prompt.md"),
        "testdata": testdata if has_testdata else None,
        "setup_files": [_join(case_real, entry["from"]) for entry in case["setup"]["files"]],
        "validators": [_join(case_real, script) for script in case["validators"]],
    }
    return [], case


def validate_case(case_dir) -> list[str]:
    """The problems of the case in `case_dir`, one line each; empty when the case is valid."""
    return _inspect(case_dir)[0]


def load_case(case_dir) -> dict:
    """The validated case with its absolute paths resolved; a CaseError names every problem."""
    problems, case = _inspect(case_dir)
    if case is None:
        path = pathlib.Path(os.path.abspath(case_dir))
        raise _case_error(f"{path.parent.name}/{path.name}", problems)
    return case


def _case_dirs(root, skill: str | None = None) -> list[pathlib.Path]:
    """Every `<root>/<skill>/<case>/` folder, sorted; hidden and dunder folders are not cases."""
    def folders(parent: pathlib.Path) -> list[pathlib.Path]:
        return sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith((".", "__")))
    root = pathlib.Path(root)
    try:
        return [case for group in folders(root) if skill in (None, group.name) for case in folders(group)]
    except OSError as exc:
        raise CaseError(f"cannot read the evals root {root}: {exc.strerror or _one_line(exc)}") from exc


def iter_cases(root, skill: str | None = None, tier: str | None = None):
    """The loaded cases under `root`, sorted by skill then case folder, optionally one skill or one tier."""
    for case_dir in _case_dirs(root, skill):
        case = load_case(case_dir)
        if tier in (None, case["tier"]):
            yield case


# ------------------------------------------------------------------------------------- staging

def stage(case: dict, dest) -> list[str]:
    """Copy the case's `setup.files` into `dest` and return the relative paths written, sorted.

    Nothing is written unless every file can be: a source that leaves the case folder or reaches
    testdata/, or a destination that a link in `dest` would move outside it, is a CaseError.
    """
    case_real = case["paths"]["case_dir"]
    pairs: list[tuple[str, str, int]] = []
    problems: list[str] = []
    for index, entry in enumerate(case["setup"]["files"]):
        found, faults = _plan_entry(case_real, index, entry)
        pairs += [(source, target, index) for source, target in found]
        problems += faults
    if problems:  # before dest is even created
        raise _case_error(case["id"], problems)
    created = not os.path.lexists(dest)
    os.makedirs(dest, exist_ok=True)
    dest_real = os.path.realpath(dest)
    for _source, target, index in pairs:
        landing = os.path.realpath(_join(dest_real, target))
        if landing == dest_real or not _inside(landing, dest_real):
            problems.append(f"setup.files[{index}].to: {target!r} would be written outside the working directory")
    if problems:
        raise _case_error(case["id"], problems)
    # Every source is copied into a holding folder first, so one that cannot be read stops the
    # staging before any file lands; what did land is taken back if a later move fails, and a
    # file that was replaced is put back from the copy kept of it.
    holding = tempfile.mkdtemp(prefix=".staging-", dir=dest_real)
    placed: list[str] = []
    made: list[str] = []
    replaced: list[tuple[str, str]] = []  # (where the file that was there is kept, where it was)
    try:
        held = []
        for number, (source, target, _index) in enumerate(pairs):
            copy = os.path.join(holding, str(number))
            shutil.copy(source, copy)  # the bytes and the permission bits, not the times
            held.append((copy, target))
        for copy, target in held:
            landing = _join(dest_real, target)
            missing, parent = [], os.path.dirname(landing)
            while not os.path.isdir(parent):
                missing.append(parent)
                parent = os.path.dirname(parent)
            for folder in reversed(missing):
                os.mkdir(folder)
                made.append(folder)
            existed = os.path.lexists(landing)
            if existed and (os.path.islink(landing) or not os.path.isdir(landing)):
                kept = os.path.join(holding, f"replaced-{len(replaced)}")
                os.replace(landing, kept)
                replaced.append((kept, landing))
            os.replace(copy, landing)
            if not existed:
                placed.append(landing)
    except OSError as exc:
        undone = [(os.remove, path) for path in placed]
        undone += [(lambda path, kept=kept: os.replace(kept, path), path) for kept, path in reversed(replaced)]
        undone += [(os.rmdir, path) for path in reversed(made)]
        for undo, path in undone:
            try:
                undo(path)
            except OSError:
                pass
        shutil.rmtree(holding, ignore_errors=True)
        if created:
            shutil.rmtree(dest_real, ignore_errors=True)
        raise _case_error(case["id"], [f"cannot stage setup.files, no file of it was left behind: "
                                       f"{exc.strerror or _one_line(exc)}"]) from exc
    shutil.rmtree(holding, ignore_errors=True)
    return sorted({target for _source, target, _index in pairs})


# ---------------------------------------------------------------------------------------- hash

def _tree_entries(folder: str) -> list[tuple[str, bytes, bytes]]:
    """(relative POSIX path, kind, bytes) of every file under `folder`, sorted; a link is its target text."""
    def refuse(error: OSError) -> None:  # os.walk skips what it cannot list unless told otherwise
        raise error

    entries = []
    for current, dirnames, filenames in os.walk(folder, onerror=refuse):
        dirnames[:] = sorted(d for d in dirnames if d not in HASH_SKIP)
        links = [d for d in dirnames if os.path.islink(os.path.join(current, d))]
        for name in sorted(f for f in filenames if f not in HASH_SKIP) + links:
            path = os.path.join(current, name)
            relative = pathlib.Path(os.path.relpath(path, folder)).as_posix()
            if os.path.islink(path):
                entries.append((relative, b"link", os.readlink(path).encode("utf-8", "surrogateescape")))
            else:
                entries.append((relative, b"file", pathlib.Path(path).read_bytes()))
    return sorted(entries)


def case_hash(case: dict, skill_dir) -> str:
    """sha256 of the case's files and the skill's files: relative paths and bytes, nothing of the machine."""
    skill_real = os.path.realpath(skill_dir)
    if not os.path.isdir(skill_real):
        raise CaseError(f"cannot hash {case['id']}: the skill folder {skill_dir} is not a directory")
    digest = hashlib.sha256()
    try:
        for origin, folder in ((b"case", case["paths"]["case_dir"]), (b"skill", skill_real)):
            for relative, kind, data in _tree_entries(folder):
                for part in (origin, relative.encode("utf-8", "surrogateescape"), kind, data):
                    digest.update(len(part).to_bytes(8, "big"))  # length-prefixed: no two splits collide
                    digest.update(part)
    except OSError as exc:
        raise CaseError(f"cannot hash {case['id']}: {exc.strerror or _one_line(exc)}") from exc
    return digest.hexdigest()


# ------------------------------------------------------------------------------------- command

def cmd_validate(args) -> int:
    case_dirs = _case_dirs(args.root)
    if not case_dirs:
        raise CaseError(f"no case found under {args.root} (a case is <skill>/<case>/case.json)")
    lines, with_problems = [], 0
    for case_dir in case_dirs:
        problems = validate_case(case_dir)
        with_problems += bool(problems)
        lines += [f"{case_dir.parent.name}/{case_dir.name}: {problem}" for problem in problems]
    for line in sorted(lines):
        print(line)
    print(f"skill-eval: {len(case_dirs)} cases, {len(case_dirs) - with_problems} valid, "
          f"{with_problems} with problems, {len(lines)} problems")
    return 1 if lines else 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would print a usage block and exit; the contract is one line
        raise UsageError(message)


def _runner(name: str):
    """A command of lib/skill_eval_run.py, imported only when it is asked for."""
    def call(args) -> int:
        if str(HERE) not in sys.path:  # `python3 -I` leaves the script's folder out of sys.path
            sys.path.insert(0, str(HERE))
        import skill_eval_run
        return getattr(skill_eval_run, name)(args)
    return call


def _above_zero(kind):
    def parse(text: str):
        try:
            value = kind(text)
        except ValueError:
            value = 0
        if not value > 0:
            raise argparse.ArgumentTypeError(f"must be {'a whole number' if kind is int else 'a number'} above 0, got {text!r}")
        return value
    return parse


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="skill_eval.py", description="Skill evals: check, run and report the kit's eval cases.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    validate = commands.add_parser("validate", help="check every case under ROOT; exit 1 on any problem")
    validate.add_argument("root", nargs="?", default=str(DEFAULT_ROOT), metavar="ROOT",
                          help="folder of <skill>/<case>/ folders (default: the kit's 08-benchmark/evals)")
    validate.set_defaults(run=cmd_validate)
    run = commands.add_parser("run", help="plan the evals of each skill; with --real, run them on `claude plugin eval`")
    report = commands.add_parser("report", help="the verdict per skill from the stored results; starts nothing")
    for command in (run, report):
        command.add_argument("--skill", action="append", metavar="NAME", help="only this skill (repeatable)")
        command.add_argument("--tier", choices=TIERS, help="only the cases of this tier (a native tag)")
        command.add_argument("--root", metavar="DIR", help="folder of <skill>/<case>/ folders (default: <kit>/08-benchmark/evals)")
        command.add_argument("--kit", metavar="DIR", help="the checkout whose 02-skills is evaluated (default: this one)")
        command.add_argument("--out", metavar="DIR", help="results and store (default: <kit>/03-tools/out/skill-evals)")
        command.add_argument("--json", metavar="FILE", help="also write the report as JSON")
    run.add_argument("--real", action="store_true", help="spend: start the native tool (without it only the plan is printed)")
    run.add_argument("--no-cache", action="store_true", help="run a case again even when its hash has a stored result")
    run.add_argument("--kit-mcp", action="store_true",
                     help="for a skill that declares MCP tools: start this checkout's MCP server in its runs "
                          "(it runs as you, outside the tool's sandbox); off by default")
    run.add_argument("--kit-plugin", action="store_true",
                     help="evaluate the skill from the kit plugin (every skill plus the kit's MCP server, started from "
                          "the plugin's own files) instead of its own package; never with --kit-mcp")
    run.add_argument("--runs", type=_above_zero(int), metavar="N", help="runs per arm, instead of each case's own")
    run.add_argument("--model", metavar="M", help="model of the agent under test (default: the session's)")
    run.add_argument("--judge-model", metavar="M", help="model of the judge (default: the tool's)")
    run.add_argument("--max-cost-usd", type=_above_zero(float), default=0.50, metavar="USD",
                     help="cost ceiling of each skill's invocation (default: 0.50)")
    run.set_defaults(run=_runner("cmd_run"))
    report.set_defaults(run=_runner("cmd_report"))
    try:
        args = parser.parse_args(argv)
        return args.run(args)
    except UsageError as exc:
        print(f"skill-eval: {_one_line(exc)} (usage: skill_eval.py validate [ROOT] | run [--kit-mcp | --kit-plugin] [--real] ... | report ...)",
              file=sys.stderr)
        return 2
    except CaseError as exc:
        print(f"skill-eval: {_one_line(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HERE))
    # Run the one importable copy of this module: the runner imports it by name, and an error it
    # raises has to be the CaseError that main() catches.
    import skill_eval as _module
    raise SystemExit(_module.main())
