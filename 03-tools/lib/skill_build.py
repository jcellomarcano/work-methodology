#!/usr/bin/env python3
"""Skill BUILD: one declaration per skill, its five verifiable targets, a cache and the package.

`02-skills/<skill>/BUILD.json` is one JSON object: `schema_version` (the integer 1) and up to
five targets, each an object. A target that is not declared is not run; any other key is a problem.

  agent_skill          {"srcs": [...], "deps": [...]}    the skill as a package
      srcs     the files of the skill, at the top level of its folder; SKILL.md is always one of
               them. A file in a subfolder is a problem until the installers can copy one
      deps     optional; what the skill needs from the kit: an `mcp__metodo__<tool>` name per MCP
               tool, or the path of a kit file or folder it calls at run time
  validate_skill_test  {}    the front matter of SKILL.md is well formed
  py_type_test         {}    strict type check of the `.py` files among `agent_skill.srcs`
  py_test              {"cwd": DIR, "modules": [...], "inputs": [...]}    the unit tests
      cwd      the kit folder `python3 -m unittest` runs in
      modules  the dotted unittest modules to run
      inputs   kit files or folders the tests read, so a change in them runs again; the test
               modules themselves always count, and with no `inputs` a PASS is never cached
  eval_suite           {}    every case under 08-benchmark/evals/<skill>/ is valid

Example (`02-skills/demo-skill/BUILD.json`):

  {"schema_version": 1,
   "agent_skill": {"srcs": ["SKILL.md", "report.py"],
                   "deps": ["mcp__metodo__job_status", "03-tools/lib/docs_lint.py"]},
   "validate_skill_test": {},
   "py_type_test": {},
   "py_test": {"cwd": "08-benchmark", "modules": ["tests.test_skill_sync"],
               "inputs": ["08-benchmark/lib", "08-benchmark/tests"]},
   "eval_suite": {}}

Every path is relative and stays inside the skill folder (`srcs`) or the kit (the rest), also
after its symlinks are resolved. `srcs` never names BUILD.json or a cache folder.

What each target checks, and when it is a SKIP (a SKIP is never a pass):
  agent_skill          every src exists; `deps` and the `mcp__metodo__*` tools of the SKILL.md
                       `allowed-tools` line name the same tools; each is in mcp/catalog.py; each
                       kit path exists; the front matter gives name, version and description
  validate_skill_test  `name` equals the folder, `description` is not empty, and no plain scalar
                       holds ': ' or ' #' (the two forms a strict YAML parser rejects)
  py_type_test         SKIP "no Python in this skill"; SKIP naming the checker when none is installed
                       or when the named one has no strict argv in CHECKERS
  py_test              SKIP "no unittest module declared"
  eval_suite           SKIP "no eval case yet"; a case is checked by 08-benchmark/lib/skill_eval.py

The package of `agent_skill` is `<out>/<skill>/<skill>-<version>.zip`:
  .claude-plugin/plugin.json   name, version and description, taken from the front matter
  MANIFEST.json                the files, what the package requires (`requires.mcp_server`,
                               `mcp_tools`, `kit_paths`, `tools_root_token`) and `standalone`
  skills/<skill>/<src>         each src, byte for byte
Entries are sorted, stored uncompressed, dated 1980-01-01 and given mode 0644, so identical
inputs give identical bytes on any machine. Nothing outside `srcs` is packed.

A src carrying the `__TOOLS_DEFAULT__` token (the kit's tools root, rendered by the installers) is
packed verbatim, token intact: the zip does not depend on a machine. The manifest lists the file
under `requires.tools_root_token`, the package does not stand alone, and `deps` must name a path
under 03-tools or the target fails. `layout_plugin(..., render_tools=True)` renders the token to
this checkout's tools root, as the installers do.

A PASS is stored in 03-tools/out/skill-build/cache/<skill>.<target>.json under a hash of the
target's inputs (the files of the skill folder, plus the catalog, the checker with its flags and
its `--version`, the test modules with the declared `inputs`, or the cases) and RUNNER_VERSION; a
stored target is reported `cached` and not run. The cache trusts `inputs`: a file the tests read
and the declaration does not list can change without a new run.
A FAIL or a SKIP is never stored. `--no-cache` neither reads nor writes the cache.

Functions the eval runner builds on:
  Kit(root=None)                           the paths of a checkout (default: this one)
  load_build(kit, skill)                   (declaration or None, problems, one line each)
  run_skill(kit, skill, use_cache=True)    one result per target: skill, target, status, reason, cached
  build_package(kit, skill, out_dir)       writes the zip and returns its path
  package_path(out_dir, skill, version)    where that zip goes
  plugin_tool_name(plugin, tool)           `mcp__metodo__<tool>` as a plugin exposes it
  layout_plugin(kit, skill, dest, local_mcp=False, repo=None, render_tools=False)
      lays the same package out as a plugin folder in `dest` (absent or empty) and returns
      plugin_dir, name, skill, invoke ("<plugin>:<skill>"), version, files, manifest, local_mcp,
      rendered_tools and mcp_tools. `render_tools` renders the tools-root token in the skill's
      files. `local_mcp` does that too, adds `.mcp.json` for this checkout's `metodo` server
      (METODO_REPO set when `repo` is given; that file is never part of the zip) and rewrites
      every `mcp__metodo__` name in the skill's files to the name Claude Code gives a plugin's
      tool, `mcp__plugin_<plugin>_metodo__<tool>`; `mcp_tools` lists the declared ones that way.
A BuildError is raised by the last two for a skill that cannot be packed.

Usage:
    lib/skill_build.py test  [SKILL ...] [--all] [--no-cache] [--json FILE]
    lib/skill_build.py build [SKILL ...] [--all] [--out DIR]

One line per target on stdout, `<STATUS> <skill>:<target> <reason>`; a skill with no BUILD.json
is one `SKIP <skill>:BUILD` line and a declaration with problems one `FAIL <skill>:BUILD` line
per problem. The counts go to stderr. Exit 0 no FAIL; 1 any FAIL; 2 a usage error or a path
that cannot be written, as one `skill-build:` line on stderr.

Python 3 stdlib only; runs under `python3 -I`. No network, no model call, no agent process.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile

RUNNER_VERSION = 2  # part of every hash: raise it when a target checks something new
SCHEMA_VERSION = 1
HERE = pathlib.Path(__file__).resolve().parent
BUILD_FILE = "BUILD.json"
SKILL_FILE = "SKILL.md"
TARGETS = ("agent_skill", "validate_skill_test", "py_type_test", "py_test", "eval_suite")
TARGET_KEYS = {"agent_skill": ("srcs", "deps"), "validate_skill_test": (), "py_type_test": (),
               "py_test": ("cwd", "modules", "inputs"), "eval_suite": ()}
MCP_SERVER = "metodo"
MCP_PREFIX = f"mcp__{MCP_SERVER}__"
TOOLS_DIR = "03-tools"
TOKEN = "__TOOLS_DEFAULT__"
# Left behind by tools, never part of a skill: not packed, not hashed, not a valid src.
CACHE_PARTS = ("__pycache__", ".DS_Store", ".mypy_cache", ".pytype", ".pytest_cache")
PLAIN_BREAKERS = (": ", " #")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o100644
# The checker a test (or the owner) names; otherwise the first of CHECKERS found on PATH.
CHECKER_ENV = "SKILL_BUILD_TYPE_CHECKER"
# UNVERIFIED: none of the three was installed when this was written (2026-11-23), so no argv
# below has been run. Check each line against the checker's own --help before trusting a PASS;
# until CHECKERS_VERIFIED is set, every PASS of py_type_test says so in its reason.
# Each line asks for the checker's strict mode. pyright has no strict flag: it reads the mode from
# a project file, which the executor writes from STRICT_PROJECT_SETTINGS in place of STRICT_PROJECT.
STRICT_PROJECT = "{strict-project}"
STRICT_PROJECT_SETTINGS = {"typeCheckingMode": "strict"}
CHECKERS = {
    "pytype": ["--strict-none-binding", "--strict-parameter-checks", "--strict-primitive-comparisons",
               "--strict-undefined-checks"],
    "mypy": ["--strict"],
    "pyright": ["--warnings", "--project", STRICT_PROJECT],
}
CHECKERS_VERIFIED = False
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOOL_RE = re.compile(rf"^{MCP_PREFIX}[a-z0-9_]+$")
_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$")
_ITEM_RE = re.compile(r"^[ \t]+-[ \t]+(.*)$")
_BLOCK_RE = re.compile(r"^[|>][+-]?[0-9]?[+-]?$")  # the indicator of a YAML block scalar
_RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)
_CATALOG_CODE = ("import json, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\n"
                 "from mcp import catalog\nprint(json.dumps(sorted(catalog.BY_NAME)))\n")
USAGE = "usage: skill-build.sh test|build [SKILL ...] [--all] [--no-cache] [--json FILE] [--out DIR]"


class BuildError(Exception):
    """A skill that cannot be packed, or a folder that cannot be used."""


class UsageError(Exception):
    pass


def _one_line(value) -> str:
    return " ".join(str(value).split())


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


def _join(base, relative: str) -> str:
    return os.path.join(str(base), *pathlib.PurePosixPath(relative).parts)


class Kit:
    """The paths of one checkout of the kit, and its MCP catalog, read once."""

    def __init__(self, root=None):
        self.root = pathlib.Path(os.path.realpath(root if root is not None else HERE.parent.parent))
        self.skills = self.root / "02-skills"
        self.tools = self.root / TOOLS_DIR
        self.evals = self.root / "08-benchmark" / "evals"
        self.out = self.tools / "out" / "skill-build"
        self.cache = self.out / "cache"
        self._catalog: tuple[frozenset[str] | None, str | None] | None = None

    def catalog(self) -> tuple[frozenset[str] | None, str | None]:
        """(the tool names of mcp/catalog.py, None), or (None, why it cannot be read)."""
        if self._catalog is None:
            self._catalog = self._read_catalog()
        return self._catalog

    def _read_catalog(self) -> tuple[frozenset[str] | None, str | None]:
        if not (self.tools / "mcp" / "catalog.py").is_file():
            return None, f"{TOOLS_DIR}/mcp/catalog.py is not in this checkout"
        # A process of its own: the catalog imports the server's modules under the name `mcp`.
        try:
            proc = subprocess.run([sys.executable, "-I", "-c", _CATALOG_CODE, str(self.tools)],
                                  capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                return None, _one_line((proc.stderr.strip().splitlines() or ["no output"])[-1])
            return frozenset(json.loads(proc.stdout)), None
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return None, _one_line(exc)


# ---------------------------------------------------------------------------------- declaration

def _path_problem(label: str, value, base: pathlib.Path, home: str) -> str | None:
    """Why `value` is not a path inside `base` (called `home` in the message), or None."""
    if not _is_relative(value):
        return f"{label}: {value!r} leaves {home}: it must be a relative path inside it"
    if not _inside(os.path.realpath(_join(base, value)), os.path.realpath(base)):
        return f"{label}: {value!r} leaves {home} through a symlink"
    return None


def _listed(label: str, value, problems: list[str]) -> list | None:
    if not isinstance(value, list):
        problems.append(f"{label} must be a list, got {value!r}")
        return None
    return value


def _check_agent_skill(kit: Kit, skill: str, decl: dict, problems: list[str]) -> None:
    srcs = decl.get("srcs")
    if not isinstance(srcs, list) or not srcs:
        problems.append(f"agent_skill.srcs must be a non-empty list of files of the skill, got {srcs!r}")
    else:
        before = len(problems)
        seen: set = set()
        for src in srcs:
            problem = _path_problem("agent_skill.srcs", src, kit.skills / skill, "the skill folder")
            parts = src.split("/") if isinstance(src, str) else []
            if problem:
                problems.append(problem)
            elif src == BUILD_FILE or any(part in CACHE_PARTS for part in parts):
                problems.append(f"agent_skill.srcs: {src!r} is the BUILD file or a cache entry, which is never packed")
            elif len(parts) > 1:
                problems.append(f"agent_skill.srcs: {src!r} is in a subfolder, and the installers copy only the "
                                f"top-level files of a skill, so it could not be installed: keep it at the top level")
            elif src in seen:
                problems.append(f"agent_skill.srcs: {src!r} is listed more than once")
            seen.add(src if isinstance(src, str) else repr(src))
        if len(problems) == before and SKILL_FILE not in srcs:
            problems.append(f"agent_skill.srcs must name {SKILL_FILE}")
    for index, dep in enumerate(_listed("agent_skill.deps", decl.get("deps", []), problems) or []):
        if isinstance(dep, str) and dep.startswith("mcp__"):
            if not _TOOL_RE.match(dep):
                problems.append(f"agent_skill.deps[{index}]: {dep!r} is not an {MCP_PREFIX}<tool> name")
            continue
        problem = _path_problem("agent_skill.deps", dep, kit.root, "the kit")
        if problem:
            problems.append(problem if isinstance(dep, str) else
                            f"agent_skill.deps[{index}]: {dep!r} must be a tool name or a kit path")


def _check_py_test(kit: Kit, decl: dict, problems: list[str]) -> None:
    modules = _listed("py_test.modules", decl.get("modules", []), problems) or []
    for index, module in enumerate(modules):
        if not isinstance(module, str) or not _MODULE_RE.match(module):
            problems.append(f"py_test.modules[{index}]: {module!r} is not a dotted module name")
    if "cwd" in decl:
        problem = _path_problem("py_test.cwd", decl["cwd"], kit.root, "the kit")
        problems.extend([problem] if problem else [])
    elif modules:
        problems.append("py_test.cwd is required with modules: the kit folder the tests run in")
    for path in _listed("py_test.inputs", decl.get("inputs", []), problems) or []:
        problem = _path_problem("py_test.inputs", path, kit.root, "the kit")
        problems.extend([problem] if problem else [])


def load_build(kit: Kit, skill: str) -> tuple[dict | None, list[str]]:
    """The declaration of `skill` and its problems, one line each; the declaration is None with any."""
    try:
        text = (kit.skills / skill / BUILD_FILE).read_bytes().decode("utf-8")
    except OSError as exc:
        return None, [f"{BUILD_FILE} cannot be read: {exc.strerror or _one_line(exc)}"]
    except UnicodeDecodeError:
        return None, [f"{BUILD_FILE} is not UTF-8 text"]
    try:
        raw = json.loads(text)
    except ValueError as exc:
        return None, [f"{BUILD_FILE} is not valid JSON: {_one_line(exc)}"]
    if not isinstance(raw, dict):
        return None, [f"{BUILD_FILE} must be a JSON object, got {type(raw).__name__}"]
    problems = [f"unknown key {key!r}" for key in sorted(raw) if key not in ("schema_version",) + TARGETS]
    version = raw.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        problems.append(f"'schema_version' must be {SCHEMA_VERSION}, got {version!r}")
    for target in TARGETS:
        if target in raw and not isinstance(raw[target], dict):
            problems.append(f"{target!r} must be an object, got {raw[target]!r}")
        elif target in raw:
            problems += [f"{target}: unknown key {key!r}" for key in sorted(raw[target]) if key not in TARGET_KEYS[target]]
    if isinstance(raw.get("agent_skill"), dict):
        _check_agent_skill(kit, skill, raw["agent_skill"], problems)
    if isinstance(raw.get("py_test"), dict):
        _check_py_test(kit, raw["py_test"], problems)
    if problems:
        return None, problems
    build = {target: dict(raw[target]) for target in TARGETS if target in raw}
    if "agent_skill" in build:
        deps = list(build["agent_skill"].get("deps", []))
        build["agent_skill"].update(deps=deps, mcp_tools=sorted(d for d in deps if d.startswith("mcp__")),
                                    kit_paths=sorted(d for d in deps if not d.startswith("mcp__")))
    return build, []


# --------------------------------------------------------------------------------- front matter

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_front_matter(path) -> tuple[dict | None, list[str]]:
    """(top-level fields, plain-scalar problems) of a SKILL.md; (None, []) when it has no front matter.

    A field is a string, or a list for a flow (`[a, b]`) or block (`- a`) sequence. A block
    scalar (`|` or `>`) is its indented lines, dedented, kept as lines or folded into one; with no
    line under it the field is empty. The kit ships no YAML parser: this reads the subset the
    skills use and checks the one rule a strict parser rejects in it, a plain scalar holding
    ': ' or ' #'.
    """
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return None, []
    if lines[0] != "---" or "---" not in lines[1:]:
        return None, []
    fields: dict = {}
    problems: list[str] = []
    current = None
    block: tuple[bool, list[str]] | None = None  # (folded, lines) while a block scalar is being read

    def block_text(folded: bool, raw: list[str]) -> str:
        text = textwrap.dedent("\n".join(raw)).strip("\n")
        return " ".join(part.strip() for part in text.split("\n") if part.strip()) if folded else text

    for number, line in enumerate(lines[1:lines.index("---", 1)], start=2):
        if block is not None:
            if not line.strip() or line[0] in " \t":
                block[1].append(line.rstrip())
                continue
            fields[current], block = block_text(*block), None
        key, item = _KEY_RE.match(line), _ITEM_RE.match(line)
        if key:
            current, value = key.group(1), (key.group(2) or "").strip()
            label = current
            if _BLOCK_RE.match(value):  # the indicator is not the value: the lines under it are
                fields[current], block = "", (value[0] == ">", [])
                continue
            if value.startswith("[") and value.endswith("]"):
                fields[current] = [_unquote(part.strip()) for part in value[1:-1].split(",") if part.strip()]
            else:
                fields[current] = _unquote(value) if value else []
        elif item and current is not None and isinstance(fields[current], list):
            value, label = item.group(1).strip(), f"{current} item"
            fields[current].append(_unquote(value))
        else:
            continue
        if value and value[0] not in "\"'[{|>":
            problems += [f"line {number}: `{label}` holds {breaker!r} unquoted"
                         for breaker in PLAIN_BREAKERS if breaker in value]
    if block is not None:
        fields[current] = block_text(*block)
    return fields, problems


def _text_field(fields: dict, key: str) -> str:
    value = fields.get(key)
    return value.strip() if isinstance(value, str) else ""


# -------------------------------------------------------------------------------------- package

def _json_bytes(data) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _inspect_package(kit: Kit, skill: str, decl: dict) -> tuple[dict | None, list[str]]:
    """(what the package of `skill` holds, []) for a loaded `agent_skill`, or (None, the problems
    that keep it from being packed). `_require_package` is the one to call for a skill by name."""
    folder = kit.skills / skill
    problems: list[str] = []
    files: list[tuple[str, bytes]] = []
    for src in sorted(decl["srcs"]):
        path = _join(folder, src)
        if not os.path.isfile(path):
            problems.append(f"srcs: {src} does not exist")
        elif not _inside(os.path.realpath(path), os.path.realpath(folder)):
            problems.append(f"srcs: {src} leaves the skill folder through a symlink")
        else:
            files.append((src, pathlib.Path(path).read_bytes()))
    fields, _plain = read_front_matter(folder / SKILL_FILE)
    tools, paths = set(decl["mcp_tools"]), list(decl["kit_paths"])
    if fields is None:
        problems.append(f"{SKILL_FILE} has no front matter")
        fields = {}
    else:
        problems += [f"{SKILL_FILE} front matter has no {key}" for key in ("name", "version", "description")
                     if not _text_field(fields, key)]
        if _text_field(fields, "name") not in ("", skill):
            problems.append(f"front matter name {fields['name']!r} is not the folder {skill!r}")
        if _text_field(fields, "version") and not _VERSION_RE.match(_text_field(fields, "version")):
            problems.append(f"front matter version {fields['version']!r} cannot name a file")
        allowed = fields.get("allowed-tools", [])
        used = {tool for tool in ([allowed] if isinstance(allowed, str) else allowed) if tool.startswith(MCP_PREFIX)}
        problems += [f"allowed-tools names {tool} but deps does not" for tool in sorted(used - tools)]
        problems += [f"deps names {tool} but allowed-tools does not" for tool in sorted(tools - used)]
    if tools:
        names, error = kit.catalog()
        if names is None:
            problems.append(f"the MCP catalog cannot be read: {error}")
        else:
            problems += [f"{tool} is not in the MCP catalog" for tool in sorted(tools)
                         if tool[len(MCP_PREFIX):] not in names]
    problems += [f"deps: {path} does not exist" for path in paths if not os.path.exists(_join(kit.root, path))]
    carriers = [src for src, data in files if TOKEN.encode() in data]
    if carriers and not any(path == TOOLS_DIR or path.startswith(TOOLS_DIR + "/") for path in paths):
        problems.append(f"{', '.join(carriers)} carries {TOKEN} but deps names no path under {TOOLS_DIR}")
    if problems:
        return None, problems
    name, version, description = (_text_field(fields, key) for key in ("name", "version", "description"))
    manifest = {
        "schema_version": SCHEMA_VERSION, "name": name, "version": version, "description": description,
        "skill": f"skills/{skill}", "files": [src for src, _data in files],
        "requires": {"mcp_server": MCP_SERVER if tools else None, "mcp_tools": sorted(tools),
                     "kit_paths": sorted(paths), "tools_root_token": carriers},
        "standalone": not (tools or paths or carriers),
    }
    entries = [(".claude-plugin/plugin.json", _json_bytes({"name": name, "version": version, "description": description})),
               ("MANIFEST.json", _json_bytes(manifest))]
    entries += [(f"skills/{skill}/{src}", data) for src, data in files]
    return {"name": name, "version": version, "manifest": manifest, "entries": sorted(entries)}, []


def _require_package(kit: Kit, skill: str) -> dict:
    """What the package of `skill` holds, from its BUILD file; a BuildError says in one line why
    the skill cannot be packed."""
    if not (kit.skills / skill / BUILD_FILE).is_file():
        raise BuildError(f"{skill}: no {BUILD_FILE}")
    build, problems = load_build(kit, skill)
    if build is None:
        raise BuildError(f"{skill}: " + "; ".join(problems))
    if "agent_skill" not in build:
        raise BuildError(f"{skill}: agent_skill is not declared")
    plan, problems = _inspect_package(kit, skill, build["agent_skill"])
    if plan is None:
        raise BuildError(f"{skill}: " + "; ".join(problems))
    return plan


def _write_zip(path: pathlib.Path, entries: list[tuple[str, bytes]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as package:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED  # no compressor version in the bytes
            info.create_system = 3
            info.external_attr = ZIP_MODE << 16
            package.writestr(info, data)
    os.replace(partial, path)


def package_path(out_dir, skill: str, version: str) -> pathlib.Path:
    """Where the package of a skill goes: `<out_dir>/<skill>/<skill>-<version>.zip`."""
    return pathlib.Path(out_dir) / skill / f"{skill}-{version}.zip"


def _write_package(plan: dict, skill: str, out_dir) -> pathlib.Path:
    path = package_path(out_dir, skill, plan["version"])
    _write_zip(path, plan["entries"])
    return path


def build_package(kit: Kit, skill: str, out_dir) -> pathlib.Path:
    """Write the package of `skill` under `out_dir` and return its path."""
    return _write_package(_require_package(kit, skill), skill, out_dir)


def plugin_tool_name(plugin: str, tool: str) -> str:
    """`mcp__metodo__<tool>` under the name Claude Code gives the tool of a plugin's server."""
    return f"mcp__plugin_{plugin}_{MCP_SERVER}__{tool[len(MCP_PREFIX):]}"


def layout_plugin(kit: Kit, skill: str, dest, local_mcp: bool = False, repo=None, render_tools: bool = False) -> dict:
    """Lay the package of `skill` out as a plugin folder in `dest`, which is absent or empty."""
    plan = _require_package(kit, skill)
    dest = pathlib.Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise BuildError(f"{dest} is not an empty folder: a plugin is laid out in a folder of its own")
    entries = list(plan["entries"])
    tools = str(kit.tools)
    prefix = f"skills/{skill}/"
    render_tools = bool(render_tools or local_mcp)
    if render_tools:
        entries = [(name, data.replace(TOKEN.encode(), tools.encode()) if name.startswith(prefix) else data)
                   for name, data in entries]
    if local_mcp:
        # Every name of the server's tools, declared or only mentioned, as the plugin exposes it.
        exposed = plugin_tool_name(plan["name"], MCP_PREFIX).encode()
        entries = [(name, data.replace(MCP_PREFIX.encode(), exposed) if name.startswith(prefix) else data)
                   for name, data in entries]
        env = {"METODO_TOOLS": tools, **({"METODO_REPO": str(repo)} if repo is not None else {})}
        server = {"command": "python3", "args": [f"{tools}/mcp/server.py"], "env": env}
        entries.append((".mcp.json", _json_bytes({"mcpServers": {MCP_SERVER: server}})))
    for name, data in entries:
        path = pathlib.Path(_join(dest, name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {"plugin_dir": str(dest), "name": plan["name"], "skill": skill, "invoke": f"{plan['name']}:{skill}",
            "version": plan["version"], "files": [name for name, _data in entries],
            "manifest": plan["manifest"], "local_mcp": bool(local_mcp), "rendered_tools": render_tools,
            "mcp_tools": ([plugin_tool_name(plan["name"], tool) for tool in plan["manifest"]["requires"]["mcp_tools"]]
                          if local_mcp else [])}


# -------------------------------------------------------------------------------------- targets

def _agent_skill(kit: Kit, skill: str, build: dict) -> tuple[str, str]:
    plan, problems = _inspect_package(kit, skill, build["agent_skill"])
    if plan is None:
        return "FAIL", "; ".join(problems)
    requires, count = plan["manifest"]["requires"], len(plan["manifest"]["files"])
    needs = [f"the {MCP_SERVER} MCP server ({len(requires['mcp_tools'])} tools)"] if requires["mcp_tools"] else []
    needs += [f"the kit ({', '.join(requires['kit_paths'])})"] if requires["kit_paths"] else []
    return "PASS", f"packs {count} file{'s' if count != 1 else ''}; " + ("needs " + " and ".join(needs) if needs else "stands alone")


def _validate_skill(kit: Kit, skill: str, build: dict) -> tuple[str, str]:
    fields, problems = read_front_matter(kit.skills / skill / SKILL_FILE)
    if fields is None:
        return "FAIL", f"{SKILL_FILE} has no front matter"
    if _text_field(fields, "name") != skill:
        problems.insert(0, f"name is {fields.get('name')!r} but the folder is {skill!r}")
    if not _text_field(fields, "description"):
        problems.insert(0, "description is empty or missing")
    return ("FAIL", "; ".join(problems)) if problems else ("PASS", f"{len(fields)} front matter keys well formed")


def _python_sources(build: dict) -> list[str]:
    return sorted(src for src in build.get("agent_skill", {}).get("srcs", []) if src.endswith(".py"))


def _find_checker() -> tuple[str | None, list[str], str]:
    """(path of the type checker, its strict flags, its name), or (None, [], the SKIP reason).

    A checker is run only with the strict flags CHECKERS holds for its name: one named through
    CHECKER_ENV that the table does not know would run lenient, so it is a SKIP, never a PASS.
    """
    named = os.environ.get(CHECKER_ENV, "").strip()
    for name in ([named] if named else list(CHECKERS)):
        found = shutil.which(name)
        if not found:
            continue
        known = os.path.basename(found)
        if known not in CHECKERS:
            return None, [], (f"type checker {known} has no strict argv in the table "
                              f"(known: {', '.join(CHECKERS)}), so it was not run")
        return found, list(CHECKERS[known]), known
    if named:
        return None, [], f"type checker {named} is not installed"
    return None, [], f"no type checker is installed (looked for {', '.join(CHECKERS)})"


def _checker_version(found: str) -> str:
    """What the checker prints for `--version`; an OSError when it cannot say, so nothing is cached."""
    try:
        proc = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"{found} --version did not end") from exc
    said = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0 or not said:
        raise OSError(f"{found} --version gave no version")
    return said


def _py_type(kit: Kit, skill: str, build: dict) -> tuple[str, str]:
    sources = _python_sources(build)
    if not sources:
        return "SKIP", "no Python in this skill"
    found, flags, name = _find_checker()
    if found is None:
        return "SKIP", name
    try:
        with tempfile.TemporaryDirectory(prefix="skill-build-") as scratch:
            if STRICT_PROJECT in flags:
                project = os.path.join(scratch, "pyrightconfig.json")
                pathlib.Path(project).write_bytes(_json_bytes(STRICT_PROJECT_SETTINGS))
                flags = [project if flag == STRICT_PROJECT else flag for flag in flags]
            proc = subprocess.run([found, *flags, *sources], cwd=kit.skills / skill, capture_output=True,
                                  text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "FAIL", f"{name} did not run: {_one_line(exc)}"
    if proc.returncode != 0:
        last = ((proc.stdout + proc.stderr).strip().splitlines() or ["no output"])[-1]
        return "FAIL", f"{name} exit {proc.returncode}: {_one_line(last)}"
    note = "" if CHECKERS_VERIFIED else "; its strict argv is unverified against the checker's own help"
    return "PASS", f"{name} accepts {len(sources)} file{'s' if len(sources) != 1 else ''}{note}"


def _py_test(kit: Kit, skill: str, build: dict) -> tuple[str, str]:
    decl = build["py_test"]
    modules = decl.get("modules", [])
    if not modules:
        return "SKIP", "no unittest module declared"
    cwd = _join(kit.root, decl["cwd"])
    if not os.path.isdir(cwd):
        return "FAIL", f"cwd {decl['cwd']} is not a folder of the kit"
    env = dict(os.environ, METODO_MEMORY="off", PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "FAIL", f"unittest did not run: {_one_line(exc)}"
    ran = _RAN_RE.search(proc.stderr)
    count = int(ran.group(1)) if ran else 0
    if proc.returncode != 0 or count == 0:
        last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        return "FAIL", f"unittest exit {proc.returncode}: {_one_line(last)}" if proc.returncode else "no test ran"
    note = "" if decl.get("inputs") else "; not cached: no `inputs` declared, so a change the tests read would go unseen"
    return "PASS", f"{count} test{'s' if count != 1 else ''} ran in {len(modules)} module{'s' if len(modules) != 1 else ''}{note}"


def _module_path(kit: Kit, decl: dict, module: str) -> str:
    """The file or package folder of a declared unittest module."""
    base = _join(_join(kit.root, decl["cwd"]), module.replace(".", "/"))
    return base if os.path.isdir(base) else base + ".py"


def _cacheable(target: str, build: dict) -> bool:
    """A py_test that lists no input says nothing of what its tests read: its PASS is never stored."""
    return target != "py_test" or bool(build["py_test"].get("inputs"))


def _skill_eval_path(kit: Kit) -> pathlib.Path | None:
    """The case validator: the checkout's own, else the one beside this file's kit."""
    for root in (kit.root, HERE.parent.parent):
        path = root / "08-benchmark" / "lib" / "skill_eval.py"
        if path.is_file():
            return path
    return None


def _case_dirs(kit: Kit, skill: str) -> list[pathlib.Path]:
    folder = kit.evals / skill
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "__")))


def _eval_suite(kit: Kit, skill: str, build: dict) -> tuple[str, str]:
    cases = _case_dirs(kit, skill)
    if not cases:
        return "SKIP", "no eval case yet"
    path = _skill_eval_path(kit)
    if path is None:
        return "FAIL", "08-benchmark/lib/skill_eval.py, the case validator, is not in this checkout"
    written, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ beside the validator
    try:
        spec = importlib.util.spec_from_file_location("_skill_build_skill_eval", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # whatever the validator's own code raises is a result line, never a traceback
        return "FAIL", f"the case validator {path.name} cannot be imported: {type(exc).__name__}: {_one_line(exc)}"
    finally:
        sys.dont_write_bytecode = written
    found = []
    for case in cases:
        try:
            found += [(case.name, problem) for problem in module.validate_case(case)]
        except Exception as exc:
            return "FAIL", f"the case validator stopped on {case.name}: {type(exc).__name__}: {_one_line(exc)}"
    if found:
        bad = len({name for name, _problem in found})
        return "FAIL", (f"{len(found)} problems in {bad} of {len(cases)} cases; "
                        f"first: {found[0][0]}: {_one_line(found[0][1])}")
    return "PASS", f"{len(cases)} case{'s' if len(cases) != 1 else ''} valid"


RUNNERS = {"agent_skill": _agent_skill, "validate_skill_test": _validate_skill, "py_type_test": _py_type,
           "py_test": _py_test, "eval_suite": _eval_suite}


# ---------------------------------------------------------------------------------------- cache

def _tree(label: str, path) -> list[tuple[str, bytes]]:
    """(label/relative path, bytes) of a file or of every file under a folder, sorted; no mtime."""
    path = str(path)
    if os.path.isfile(path):
        return [(label, pathlib.Path(path).read_bytes())]
    if not os.path.isdir(path):
        return [(label, b"\0missing")]
    found = []
    for current, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in CACHE_PARTS)
        for name in sorted(f for f in filenames if f not in CACHE_PARTS):
            full = os.path.join(current, name)
            relative = pathlib.Path(os.path.relpath(full, path)).as_posix()
            found.append((f"{label}/{relative}", pathlib.Path(full).read_bytes()))
    return sorted(found)


def _target_inputs(kit: Kit, skill: str, target: str, build: dict) -> list[tuple[str, bytes]]:
    """What only this target reads, beyond the files of the skill folder."""
    if target == "agent_skill":
        names, error = kit.catalog()
        listed = "\n".join(sorted(names)) if names is not None else f"unreadable: {error}"
        exists = [(f"dep:{path}", str(os.path.exists(_join(kit.root, path))).encode())
                  for path in build["agent_skill"]["kit_paths"]]
        return [("catalog", listed.encode("utf-8"))] + exists
    if target == "py_type_test":
        if not _python_sources(build):
            return []
        found, flags, name = _find_checker()
        if found is None:
            return [("checker", name.encode("utf-8", "surrogateescape"))]
        # The version too: a new release of the checker may reject what the last one accepted.
        return [("checker", "\0".join([found, *flags]).encode("utf-8", "surrogateescape")),
                ("checker-version", _checker_version(found).encode("utf-8", "surrogateescape"))]
    if target == "py_test":
        declared = build["py_test"]
        parts = [part for path in declared.get("inputs", []) for part in _tree(f"input:{path}", _join(kit.root, path))]
        for module in declared.get("modules", []):  # what runs is an input, listed or not
            parts += _tree(f"module:{module}", _module_path(kit, declared, module))
        return parts
    if target == "eval_suite":
        validator = _skill_eval_path(kit)
        return _tree("evals", kit.evals / skill) + (_tree("validator", validator) if validator else [])
    return []


def _target_hash(kit: Kit, skill: str, target: str, build: dict, skill_files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    parts = [("runner", str(RUNNER_VERSION).encode()), ("target", f"{skill}:{target}".encode("utf-8"))]
    for label, data in parts + skill_files + _target_inputs(kit, skill, target, build):
        for part in (label.encode("utf-8", "surrogateescape"), data):
            digest.update(len(part).to_bytes(8, "big"))  # length-prefixed: no two splits collide
            digest.update(part)
    return digest.hexdigest()


def _cache_get(kit: Kit, skill: str, target: str, key: str) -> str | None:
    """The reason of the stored PASS of this target under this hash, else None."""
    try:
        stored = json.loads((kit.cache / f"{skill}.{target}.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if isinstance(stored, dict) and stored.get("hash") == key and stored.get("status") == "PASS":
        return str(stored.get("reason", ""))
    return None


def _cache_put(kit: Kit, skill: str, target: str, key: str, reason: str) -> None:
    try:
        kit.cache.mkdir(parents=True, exist_ok=True)
        path = kit.cache / f"{skill}.{target}.json"
        partial = path.with_name(path.name + ".tmp")
        partial.write_bytes(_json_bytes({"hash": key, "status": "PASS", "reason": reason, "runner_version": RUNNER_VERSION}))
        os.replace(partial, path)
    except OSError:
        pass  # a cache that cannot be written costs a second run, never a result


# ------------------------------------------------------------------------------------- executor

def _result(skill: str, target: str, status: str, reason: str, cached: bool = False) -> dict:
    return {"skill": skill, "target": target, "status": status, "reason": _one_line(reason), "cached": cached}


def run_skill(kit: Kit, skill: str, use_cache: bool = True) -> list[dict]:
    """Run every declared target of `skill`; a target whose hash has a stored PASS is not run."""
    if not (kit.skills / skill / BUILD_FILE).is_file():
        return [_result(skill, "BUILD", "SKIP", f"no {BUILD_FILE}")]
    build, problems = load_build(kit, skill)
    if build is None:
        return [_result(skill, "BUILD", "FAIL", problem) for problem in problems]
    skill_files = None
    if use_cache:
        try:
            skill_files = _tree("skill", kit.skills / skill)
        except OSError:
            skill_files = None  # a file that cannot be read: nothing is taken from the cache
    results = []
    for target in TARGETS:
        if target not in build:
            continue
        key = None
        if skill_files is not None and _cacheable(target, build):
            try:
                key = _target_hash(kit, skill, target, build, skill_files)
            except OSError:
                key = None
        stored = _cache_get(kit, skill, target, key) if key else None
        if stored is not None:
            results.append(_result(skill, target, "PASS", f"cached: {stored}", cached=True))
            continue
        status, reason = RUNNERS[target](kit, skill, build)
        if status == "PASS" and key:
            _cache_put(kit, skill, target, key, reason)
        results.append(_result(skill, target, status, reason))
    return results


def build_skill(kit: Kit, skill: str, out_dir) -> list[dict]:
    """Pack `skill`: one result line, PASS with the zip and its sha256, or why it was not packed."""
    if not (kit.skills / skill / BUILD_FILE).is_file():
        return [_result(skill, "BUILD", "SKIP", f"no {BUILD_FILE}")]
    build, problems = load_build(kit, skill)
    if build is None:
        return [_result(skill, "BUILD", "FAIL", problem) for problem in problems]
    if "agent_skill" not in build:
        return [_result(skill, "agent_skill", "SKIP", "not declared")]
    plan, problems = _inspect_package(kit, skill, build["agent_skill"])
    if plan is None:
        return [_result(skill, "agent_skill", "FAIL", "; ".join(problems))]
    path = _write_package(plan, skill, out_dir)
    return [_result(skill, "agent_skill", "PASS", f"{path} sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")]


# -------------------------------------------------------------------------------------- command

def _selected(kit: Kit, args) -> list[str]:
    if args.all and args.skills:
        raise UsageError("name skills or pass --all, not both")
    if args.all:
        return sorted(p.name for p in kit.skills.iterdir() if (p / SKILL_FILE).is_file())
    if not args.skills:
        raise UsageError("name at least one skill, or pass --all")
    for skill in args.skills:
        if not _SKILL_RE.match(skill) or not (kit.skills / skill).is_dir():
            raise UsageError(f"no such skill under 02-skills: {skill!r}")
    return list(dict.fromkeys(args.skills))


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would print a usage block and exit; the contract is one line
        raise UsageError(message)


def main(argv: list[str] | None = None, kit_root=None) -> int:
    parser = _Parser(prog="skill-build.sh", description="Build and test the skills from their BUILD.json.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    test = commands.add_parser("test", help="run the declared targets; exit 1 on any FAIL")
    test.add_argument("--no-cache", action="store_true", help="run every target; read and store nothing")
    test.add_argument("--json", metavar="FILE", help="also write the results as JSON")
    build = commands.add_parser("build", help="write <out>/<skill>/<skill>-<version>.zip")
    build.add_argument("--out", metavar="DIR", help="default: 03-tools/out/skill-build/dist")
    for command in (test, build):
        command.add_argument("skills", nargs="*", metavar="SKILL", help="a folder name under 02-skills")
        command.add_argument("--all", action="store_true", help="every skill")
    try:
        args = parser.parse_args(argv)
        kit = Kit(kit_root)
        results: list[dict] = []
        for skill in _selected(kit, args):
            if args.command == "test":
                results += run_skill(kit, skill, use_cache=not args.no_cache)
            else:
                results += build_skill(kit, skill, args.out or kit.out / "dist")
        for result in results:
            print(f"{result['status']} {result['skill']}:{result['target']} {result['reason']}")
        counts = {status: sum(r["status"] == status for r in results) for status in ("PASS", "FAIL", "SKIP")}
        if getattr(args, "json", None):
            report = {"runner_version": RUNNER_VERSION, "command": args.command, "counts": counts, "results": results}
            pathlib.Path(args.json).write_bytes(_json_bytes(report))
        cached = sum(r["cached"] for r in results)
        print(f"skill-build: {counts['PASS']} PASS ({cached} cached), {counts['FAIL']} FAIL, "
              f"{counts['SKIP']} SKIP (a SKIP is not a pass)", file=sys.stderr)
        return 1 if counts["FAIL"] else 0
    except UsageError as exc:
        print(f"skill-build: {_one_line(exc)} ({USAGE})", file=sys.stderr)
        return 2
    except (BuildError, OSError) as exc:
        print(f"skill-build: {_one_line(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
