"""Deterministic JSON I/O and baseline snapshots.

Every payload in this repository goes through write_json() so repeated runs
over the same inputs produce byte-for-byte identical files: sorted keys,
fixed indentation, a trailing newline, and no timestamps/hostnames/absolute
home paths inside the payload (that goes in the run-meta.json each bin/*.sh
writes separately).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"


def write_json(path: os.PathLike | str, obj: Any) -> None:
    """Writes `obj` as deterministic JSON: sorted keys, indent=2,
    ensure_ascii=False (so non-ASCII text does not get escaped to
    \\uXXXX) and a single trailing newline. Creates parent directories
    if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def load_json(path: os.PathLike | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_head_sha(repo_dir: os.PathLike | str) -> str:
    """HEAD SHA of the repo at `repo_dir`. Fails loudly if the repo has no
    commits yet (there is nothing deterministic to return)."""
    out = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _status_line_path(line: str) -> str:
    """Extracts the path from a `git status --porcelain` line. A rename
    line ('R  old -> new') reports the destination; the quotes git puts
    around paths with special characters are stripped."""
    path = line[3:] if len(line) > 3 else line.strip()
    if " -> " in path:
        path = path.split(" -> ")[-1]
    return path.strip().strip('"')


def is_repo_dirty(repo_dir: os.PathLike | str) -> bool:
    """True if `git status --porcelain` reports anything outside `.claude/`.
    Agent worktrees live there as untracked directories and do not count
    as "the repo has uncommitted changes": they are a separate checkout."""
    out = subprocess.run(
        ["git", "-C", str(repo_dir), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        path = _status_line_path(line)
        if path == ".claude" or path.startswith(".claude/") or "/.claude/" in path:
            continue
        return True
    return False


def base_envelope(
    tools_repo_dir: os.PathLike | str, repo_sha: str, tool_versions: dict, repo_dirty: bool
) -> dict:
    """Builds the 5 mandatory header keys present in every payload. The
    caller adds its own content keys on top. `repo_dirty` is computed by
    the caller (with `is_repo_dirty` over the repo it analyzed) because
    here we do not know whether `repo_sha` came from a working tree or
    from a freshly created disposable worktree."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_sha": git_head_sha(tools_repo_dir),
        "tool_versions": tool_versions,
        "repo_sha": repo_sha,
        "repo_dirty": repo_dirty,
    }


def baseline_path(baselines_dir: os.PathLike | str, repo_sha: str, repo_dirty: bool = False) -> Path:
    suffix = "-dirty" if repo_dirty else ""
    return Path(baselines_dir) / f"{repo_sha}{suffix}.json"


def save_baseline(
    baselines_dir: os.PathLike | str,
    repo_sha: str,
    obj: Any,
    repo_dirty: bool = False,
    force: bool = False,
) -> Path:
    """Saves `obj` as the baseline for `repo_sha`. Never overwrites an
    existing baseline unless --force is explicitly requested: a baseline is
    a reference point, not a working file. With a dirty repo, --force is
    required even for the first write (a working tree with uncommitted
    changes is not a reliable reference point), and the file is named
    `<sha>-dirty.json`, never `<sha>.json`, so it is not confused with a
    clean baseline."""
    if repo_dirty and not force:
        raise RuntimeError(
            "the analyzed repo has uncommitted changes: use --force to save "
            "a baseline of a dirty working tree"
        )
    path = baseline_path(baselines_dir, repo_sha, repo_dirty)
    if path.exists() and not force:
        raise FileExistsError(f"baseline already exists: {path} (use --force to overwrite)")
    write_json(path, obj)
    return path


def _numeric_leaves(obj: Any, prefix: str = "") -> dict:
    """Flattens a nested dict to {dotted.key: value}, keeping only the
    numeric leaves (bool is excluded on purpose: it is not a metric)."""
    leaves: dict = {}
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            child_prefix = f"{prefix}.{key}" if prefix else key
            leaves.update(_numeric_leaves(obj[key], child_prefix))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        leaves[prefix] = obj
    return leaves


def delta(before: dict, after: dict, allow_tool_drift: bool = False) -> dict:
    """Compares two payloads by their numeric leaves. `added`/`removed` are
    sorted lists of keys; `changed` maps key -> {before, after, delta}
    only for the ones whose value changed.

    If `before`/`after` carry `tool_sha`/`tool_versions` (the
    base_envelope header) and they do not match, a numeric delta would be
    comparing apples to oranges: two versions of the measuring tool
    itself. With `allow_tool_drift=False` (the default) this returns a
    {"verdict": "VOID: tool drift", ...} payload instead of a delta, so
    the CLI caller can exit 2 without faking a numeric result."""
    before_sha, after_sha = before.get("tool_sha"), after.get("tool_sha")
    before_versions, after_versions = before.get("tool_versions"), after.get("tool_versions")
    drift = (before_sha is not None or after_sha is not None) and (
        before_sha != after_sha or before_versions != after_versions
    )
    if drift and not allow_tool_drift:
        return {
            "verdict": "VOID: tool drift",
            "tool_sha_before": before_sha,
            "tool_sha_after": after_sha,
            "tool_versions_before": before_versions,
            "tool_versions_after": after_versions,
        }

    before_leaves = _numeric_leaves(before)
    after_leaves = _numeric_leaves(after)
    before_keys = set(before_leaves)
    after_keys = set(after_leaves)

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed = {}
    for key in sorted(after_keys & before_keys):
        b, a = before_leaves[key], after_leaves[key]
        if a != b:
            changed[key] = {"before": b, "after": a, "delta": a - b}

    return {"added": added, "removed": removed, "changed": changed}
