#!/usr/bin/env python3
"""Run a check command and record it: the green proof the done gate reads
(context-method §6, done-gate.md §3). A hook never sees a Bash exit code,
so a run counts only when it went through this wrapper.

    bin/run-check.sh <name> [--runs-dir DIR] [--cwd DIR] -- <command...>

The command runs unchanged in --cwd (default: the current directory), with
stdout and stderr merged and streamed through to the caller. Its exit code
is this script's exit code (a signal death becomes 128 + signal, a missing
command 127). Exit 2 before running anything on a usage error: no `--`, no
command, a bad name, a cwd outside a git repo, or a runs dir that lands in a
path of the target repo git does not ignore.

One line per run is appended to <runs>/runs.jsonl (default
<tools>/out/runs, or $METODO_RUNS_DIR), sorted compact JSON:
    argv, cwd (relative to the repo), dirty, elapsed_ms, exit, head_sha,
    log (<seq>.log, the combined output, next to runs.jsonl), name,
    output_sha256 (of that log), schema_version, seq, tree_sha, worktree_sha.
No wall-clock time is recorded. "After the last edit" is decided by
`worktree_sha`, a fingerprint of HEAD^{tree} plus the content of every
changed, deleted or untracked (not ignored) path at the moment the command
started: any later edit changes it, a commit of the same bytes does not
change the tested content, and the same tree always gives the same value.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")
USAGE = "usage: run-check.sh <name> [--runs-dir DIR] [--cwd DIR] -- <command...>"


class UsageError(Exception):
    pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)


def repo_root(path: Path) -> Path | None:
    probe = _git(path, "rev-parse", "--show-toplevel")
    return Path(probe.stdout.decode().strip()).resolve() if probe.returncode == 0 else None


def _rev(repo: Path, ref: str) -> str | None:
    probe = _git(repo, "rev-parse", "--verify", "-q", ref)
    return probe.stdout.decode().strip() if probe.returncode == 0 else None


def status_entries(repo: Path) -> list[tuple[str, str]]:
    """(XY, path) per path `git status` reports (tracked changes, deletions,
    untracked not ignored; a rename gives its source as "D "), sorted by path,
    excluding .claude/ (agent worktrees, like baseline.is_repo_dirty)."""
    out = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.decode("utf-8", "surrogateescape")
    fields = out.split("\0")
    entries: dict[str, str] = {}
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        entries[path] = status
        if status[0] in "RC" or status[1] in "RC":
            if i < len(fields) and fields[i] and status[0] == "R":
                entries.setdefault(fields[i], "D ")  # the rename's source is gone from the tree
            i += 1
    return sorted(((s, p) for p, s in entries.items() if not p.startswith(".claude/")), key=lambda e: e[1])


def changed_paths(repo: Path) -> list[str]:
    return [path for _, path in status_entries(repo)]


def _content_sha(path: Path) -> str:
    if path.is_symlink():
        return "link:" + hashlib.sha256(os.readlink(path).encode("utf-8", "surrogateescape")).hexdigest()
    if path.is_dir():
        return "dir"
    if not path.exists():
        return "absent"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def worktree_fingerprint(repo: Path) -> dict:
    """{head_sha, tree_sha, dirty, worktree_sha}; read-only (no index, no object written)."""
    repo = Path(repo)
    head = _rev(repo, "HEAD")
    tree = _rev(repo, "HEAD^{tree}") if head else None
    paths = changed_paths(repo)
    digest = hashlib.sha256(f"tree {tree or '-'}\n".encode())
    for rel in paths:
        digest.update(f"{rel}\0{_content_sha(repo / rel)}\n".encode("utf-8", "surrogateescape"))
    return {"dirty": bool(paths), "head_sha": head, "tree_sha": tree, "worktree_sha": digest.hexdigest()}


def default_runs_dir() -> Path:
    return Path(os.environ.get("METODO_RUNS_DIR") or TOOLS_ROOT / "out" / "runs")


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_runs_dir(runs_dir: Path, repo: Path) -> None:
    if _inside(runs_dir, repo) and _git(repo, "check-ignore", "-q", str(runs_dir)).returncode != 0:
        raise UsageError(f"refusing to record inside the target repo ({repo}) on a path git does not ignore: {runs_dir}")


def parse_args(argv: list[str]) -> dict:
    if not argv or argv[0].startswith("-"):
        raise UsageError("the first argument is the check name")
    name, rest = argv[0], argv[1:]
    if not NAME_RE.match(name):
        raise UsageError(f"bad name {name!r}: letters, digits, . _ / - (≤ 80)")
    if "--" not in rest:
        raise UsageError("missing `--` before the command")
    split = rest.index("--")
    options, command = rest[:split], rest[split + 1:]
    if not command:
        raise UsageError("no command after `--`")
    opts = {"runs_dir": None, "cwd": None}
    i = 0
    while i < len(options):
        key = options[i]
        if key not in ("--runs-dir", "--cwd") or i + 1 >= len(options):
            raise UsageError(f"unknown or incomplete option {key!r}")
        opts[key[2:].replace("-", "_")] = options[i + 1]
        i += 2
    return {"name": name, "command": command, **opts}


def _next_log(runs_dir: Path) -> tuple[int, Path]:
    """Claims the next free <seq>.log atomically (exclusive create)."""
    taken = [int(p.stem) for p in runs_dir.glob("*.log") if p.stem.isdigit()]
    seq = max(taken, default=0) + 1
    while True:
        path = runs_dir / f"{seq}.log"
        try:
            path.open("xb").close()
            return seq, path
        except FileExistsError:
            seq += 1


def _execute(command: list[str], cwd: Path, log: Path) -> tuple[int, str, int]:
    digest = hashlib.sha256()
    start = time.monotonic()
    out = getattr(sys.stdout, "buffer", None)
    with log.open("wb") as sink:
        def emit(data: bytes) -> None:
            sink.write(data)
            digest.update(data)
            if out is not None:
                out.write(data)
                out.flush()
        try:
            proc = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except (FileNotFoundError, PermissionError) as exc:
            emit(f"run-check: cannot execute {command[0]}: {exc.strerror or exc}\n".encode())
            code = 127 if isinstance(exc, FileNotFoundError) else 126
            return code, digest.hexdigest(), int((time.monotonic() - start) * 1000)
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read1(1 << 14), b""):
            emit(chunk)
        code = proc.wait()
    if code < 0:
        code = 128 - code
    return code, digest.hexdigest(), int((time.monotonic() - start) * 1000)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv)
        cwd = Path(args["cwd"] or os.getcwd()).expanduser().resolve()
        repo = repo_root(cwd) if cwd.is_dir() else None
        if repo is None:
            raise UsageError(f"{cwd} is not inside a git repo")
        runs_dir = Path(args["runs_dir"]).expanduser().resolve() if args["runs_dir"] else default_runs_dir().resolve()
        check_runs_dir(runs_dir, repo)
    except UsageError as exc:
        print(f"run-check: {exc}\n{USAGE}", file=sys.stderr)
        return 2
    fingerprint = worktree_fingerprint(repo)
    runs_dir.mkdir(parents=True, exist_ok=True)
    seq, log = _next_log(runs_dir)
    code, output_sha, elapsed = _execute(args["command"], cwd, log)
    record = {"argv": args["command"], "cwd": cwd.relative_to(repo).as_posix() or ".", "elapsed_ms": elapsed, "exit": code,
              "log": log.name, "name": args["name"], "output_sha256": output_sha, "schema_version": SCHEMA_VERSION,
              "seq": seq, **fingerprint}
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with (runs_dir / "runs.jsonl").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(line + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
