#!/usr/bin/env python3
"""Selects the Gradle tasks for the modules a change touches (sectors), so
the agent loop does not run the full battery for every edit. The full
battery is still owned by the repo's pre-push and by CI.

Changes = git diff --name-only <base>...HEAD (three dots: what the branch
contributes) plus the dirty tree and untracked files, unless
--committed-only. `full_required` is true when the change touches a shared
build file, a glob from `test_sectors.full_required_globs`, or any path
with no sector: in that case there is no shortcut and the skill escalates
to the full battery.

Usage:
    lib/test_sectors.py <repo> [--base REF] [--committed-only] [--config project.json]
    lib/test_sectors.py <repo> --check-verify <tools/verify/verify.sh> [--config project.json]

--check-verify checks that every task in the map exists in the repo's
verify.sh CHECK_TASKS (exit 1 if any does not): it is the anti-drift gate.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, rdd_risk, toolenv  # noqa: E402
from lib import role_contract_validator as rcv  # noqa: E402

DEFAULT_BASE = "origin/develop"
DEFAULT_FULL_GLOBS = ["app/libs/**", "**/proguard*.pro", "gradle/**", "gradlew*", "**/build.gradle", "tools/verify/**"]
CHECK_TASKS_RE = re.compile(r"CHECK_TASKS=\((.*?)\n\)", re.DOTALL)
CASE_ARM_RE = re.compile(r"^\s*([A-Za-z0-9_./-]+)/\*\)\s*add_module_task", re.MULTILINE)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True)


def changed_files(repo: Path, base: str, committed_only: bool) -> tuple[list[dict], str | None, bool]:
    resolved = _git(repo, "rev-parse", "--verify", "-q", f"{base}^{{commit}}", check=False)
    base_ok = resolved.returncode == 0
    files: dict[str, str] = {}
    merge_base = None
    if base_ok:
        merge_base = _git(repo, "merge-base", base, "HEAD").stdout.strip()
        for line in _git(repo, "diff", "--name-only", f"{base}...HEAD").stdout.splitlines():
            if line.strip():
                files[line.strip()] = "committed"
    if not committed_only:
        for line in _git(repo, "status", "--porcelain", "--untracked-files=all").stdout.splitlines():
            if not line.strip():
                continue
            path = baseline._status_line_path(line)
            if path == ".claude" or path.startswith(".claude/") or "/.claude/" in path:
                continue
            files.setdefault(path, "untracked" if line.startswith("??") else "dirty")
    return [{"path": p, "source": files[p]} for p in sorted(files)], merge_base, base_ok


INCLUDE_RE = re.compile(r"""^\s*include\s*\(?\s*['"](:[^'"]+)['"]""", re.MULTILINE)


def included_projects(repo: Path) -> set[str] | None:
    """Gradle projects this lineage actually has, from settings.gradle.

    Returns None when there is no settings.gradle to read, which disables the
    filter instead of silently dropping every task.
    """
    for name in ("settings.gradle", "settings.gradle.kts"):
        path = Path(repo) / name
        if path.exists():
            return set(INCLUDE_RE.findall(path.read_text(encoding="utf-8"))) | {":"}
    return None


def task_project(task: str) -> str:
    """':payment:api:test' -> ':payment:api'. A task with no project prefix is root."""
    head, _, _ = task.rpartition(":")
    return head or ":"


def select(changed: list[dict], config: dict, projects: set[str] | None = None) -> dict:
    ts = config.get("test_sectors") or {}
    sectors = ts.get("sectors") or []
    full_globs = list(ts.get("full_required_globs") or DEFAULT_FULL_GLOBS)
    shared_build = [p for p in rcv.always_forbidden_patterns(config) if ".claude" not in p]
    exempt = list(rdd_risk.rdd_config(config)["exempt_globs"])
    gate = ts.get("credential_gate") or {}

    changed = sorted(changed, key=lambda e: e["path"])
    ignored, reasons, unmapped, sectors_hit, tasks = [], [], [], [], set()
    for entry in changed:
        path = entry["path"]
        if rdd_risk.matches_any(path, exempt):
            ignored.append(path)
            continue
        if rdd_risk.matches_any(path, shared_build):
            reasons.append({"path": path, "rule": "shared_build_files"})
        if rdd_risk.matches_any(path, full_globs):
            reasons.append({"path": path, "rule": "full_required_globs"})
        best = None
        for sector in sectors:
            for prefix in sector.get("paths", []):
                if path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                    best = (prefix, sector)
        if best is None:
            unmapped.append(path)
            reasons.append({"path": path, "rule": "unmapped"})
            continue
        if best[0] not in sectors_hit:
            sectors_hit.append(best[0])
        tasks.update(best[1].get("tasks", []))

    # A sector may name a module another lineage has and this one does not
    # (:payment:stripe on develop, :payment:tc2p on gateway-legacy-parity).
    # Asking Gradle for it fails configuration, so the task is dropped; the drop
    # forces the full battery, because a dropped test is not a passed test.
    absent = sorted(t for t in tasks if projects is not None and task_project(t) not in projects)
    if absent:
        tasks -= set(absent)
        reasons.append({"path": ", ".join(absent), "rule": "task_project_absent"})

    gated_prefixes = tuple(gate.get("task_prefixes") or [])
    return {
        "changed_files": changed,
        "absent_project_tasks": absent,
        "ignored_files": sorted(ignored),
        "sectors_hit": sorted(sectors_hit),
        "tasks": sorted(tasks),
        "credential_gate": gate or None,
        "credential_gated_tasks": sorted(t for t in tasks if gated_prefixes and t.startswith(gated_prefixes)),
        "full_required": bool(reasons),
        "full_required_reasons": sorted(reasons, key=lambda r: (r["path"], r["rule"])),
        "unmapped_files": sorted(unmapped),
    }


def parse_check_tasks(verify_text: str) -> list[str]:
    match = CHECK_TASKS_RE.search(verify_text)
    if not match:
        return []
    tasks = []
    for line in match.group(1).splitlines():
        code = line.split("#", 1)[0]
        tasks.extend(tok for tok in code.split() if tok.startswith(":"))
    return sorted(set(tasks))


def is_test_task(task: str) -> bool:
    """`--changed` is a shortcut for tests: lint and guards deliberately do not live there."""
    return "test" in task.rpartition(":")[2].lower()


def parse_changed_arms(verify_text: str) -> list[str]:
    """Prefixes that verify.sh's `--changed` mode knows how to map to a task."""
    return sorted({f"{m}/" for m in CASE_ARM_RE.findall(verify_text)})


def check_verify(config: dict, verify_path: Path, projects: set[str] | None = None) -> dict:
    verify_text = Path(verify_path).read_text(encoding="utf-8")
    known = parse_check_tasks(verify_text)
    mapped = sorted({t for s in (config.get("test_sectors") or {}).get("sectors", []) for t in s.get("tasks", [])})
    # Drift is a task this lineage HAS and verify.sh forgot. A task whose module
    # this lineage never included is a lineage difference, not drift.
    absent = sorted(t for t in mapped if projects is not None and task_project(t) not in projects)
    unknown = sorted(t for t in mapped if t not in known and t not in absent)

    # The other direction of drift, and the one that bites silently: the
    # full battery names the module's task, but `--changed` mode has no
    # `case` arm for its path, so a change to only that module prints
    # "no module with tests in range" in green and runs no test at all.
    arms = parse_changed_arms(verify_text)
    gaps = []
    # With no arms there is no `--changed` mode to keep in sync: a
    # verify.sh that only runs the full battery cannot fall short.
    for sector in (config.get("test_sectors") or {}).get("sectors", []) if arms else []:
        live = [t for t in sector.get("tasks", []) if t in known and t not in absent and is_test_task(t)]
        for prefix in sector.get("paths", []):
            if live and not any(prefix.startswith(a) or a.startswith(prefix) for a in arms):
                gaps.append({"path": prefix, "tasks": sorted(live)})

    return {
        "known_tasks": known,
        "mapped_tasks": mapped,
        "absent_project_tasks": absent,
        "unknown_tasks": unknown,
        "changed_mode": "present" if arms else "absent",
        "changed_mode_gaps": sorted(gaps, key=lambda g: g["path"]),
        "ok": not unknown and not gaps and bool(known),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--base", default=None)
    parser.add_argument("--committed-only", action="store_true")
    parser.add_argument("--config", default=None, help="config/project.json")
    parser.add_argument("--check-verify", default=None, help="path to the repo's verify.sh")
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else TOOLS_ROOT / "config" / "project.json"
    config = baseline.load_json(config_path) if config_path.exists() else {}

    if args.check_verify:
        result = check_verify(config, Path(args.check_verify), included_projects(Path(args.repo).resolve()))
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    repo = Path(args.repo).resolve()
    base = args.base or (config.get("test_sectors") or {}).get("base_ref") or DEFAULT_BASE
    changed, merge_base, base_ok = changed_files(repo, base, args.committed_only)
    payload = baseline.base_envelope(TOOLS_ROOT, baseline.git_head_sha(repo), toolenv.tool_versions(TOOLS_ROOT), baseline.is_repo_dirty(repo))
    payload.update({"base": base, "base_resolved": base_ok, "merge_base": merge_base, "committed_only": args.committed_only})
    payload.update(select(changed, config, included_projects(repo)))
    print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
