#!/usr/bin/env python3
"""Duplication detector (CPD) over the Kotlin repo, with a fixed calibration.

Wraps `pmd cpd` (vendor/pmd-bin-*/bin/pmd) and normalizes its XML into a
deterministic JSON: clusters sorted by (tokens desc, first file asc) and a
pairwise map of duplicated tokens per file pair. If PMD could not be
downloaded (vendor/config/tools.lock.json in status "unavailable"), falls
back to its own line-window hash detector, unambiguously labeled as a
heuristic ("tool": "fallback-linehash", "epistemic": "Inferido").

`--calibrate` also recalibrates over the candidate files declared in
config/duplication-targets.json (or --calibrate-files, for a one-off sweep
that does not touch the config) at the 50/75/100/150 token thresholds, and
writes that table to out/<repo_sha>/duplication-calibration.json: it is
the input bin/metrics.sh uses to decide the default --min-tokens for the
full-repo analysis. See config/examples/critical-flow/duplication-targets.json
for a real example of targets (3 ViewModel candidates from a payments
domain).

Usage:
    lib/duplication_cpd.py <repo> [--min-tokens N] [--files a.kt,b.kt,...]
    lib/duplication_cpd.py <repo> --calibrate [--calibrate-files a.kt,b.kt,...]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, repo_scan, toolenv  # noqa: E402

CPD_NAMESPACE = {"c": "https://pmd-code.org/schema/cpd-report"}
FALLBACK_WINDOW_LINES = 12
CALIBRATION_THRESHOLDS = (50, 75, 100, 150)
DUPLICATION_TARGETS_CONFIG_NAME = "duplication-targets.json"


def find_pmd_bin(tools_root: Path) -> Path | None:
    candidates = sorted((tools_root / "vendor").glob("pmd-bin-*/bin/pmd"))
    return candidates[0] if candidates else None


def _pmd_available(tools_root: Path) -> bool:
    pmd_bin = find_pmd_bin(tools_root)
    if pmd_bin is None or not pmd_bin.exists():
        return False
    lock_path = tools_root / "config" / "tools.lock.json"
    if not lock_path.exists():
        return True
    lock = baseline.load_json(lock_path)
    return lock.get("pmd", {}).get("status") != "unavailable"


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def run_pmd_cpd(pmd_bin: Path, repo_root: Path, abs_files: list[Path], min_tokens: int) -> dict:
    fd, file_list_path = tempfile.mkstemp(prefix="cpd-files-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(str(f) for f in abs_files))
        import subprocess

        proc = subprocess.run(
            [
                str(pmd_bin), "cpd",
                "--minimum-tokens", str(min_tokens),
                "--language", "kotlin",
                "--format", "xml",
                "--file-list", file_list_path,
                "--no-fail-on-violation",
                "--no-fail-on-error",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        os.unlink(file_list_path)
    return _parse_pmd_xml(proc.stdout, repo_root)


def _parse_pmd_xml(xml_text: str, repo_root: Path) -> dict:
    clusters = []
    pairwise: dict[str, int] = {}
    if not xml_text.strip():
        return {"clusters": clusters, "pairwise": pairwise}

    root = ET.fromstring(xml_text)
    for dup in root.findall("c:duplication", CPD_NAMESPACE):
        tokens = int(dup.get("tokens"))
        lines = int(dup.get("lines"))
        occurrences = []
        for f in dup.findall("c:file", CPD_NAMESPACE):
            rel = _rel(Path(f.get("path")), repo_root)
            occurrences.append({
                "file": rel,
                "start_line": int(f.get("line")),
                "end_line": int(f.get("endline")),
            })
        occurrences.sort(key=lambda o: (o["file"], o["start_line"]))
        clusters.append({"tokens": tokens, "lines": lines, "occurrences": occurrences})

        distinct = sorted({o["file"] for o in occurrences})
        for i in range(len(distinct)):
            for j in range(i + 1, len(distinct)):
                key = f"{distinct[i]}|{distinct[j]}"
                pairwise[key] = pairwise.get(key, 0) + tokens

    clusters.sort(key=_cluster_sort_key)
    return {"clusters": clusters, "pairwise": pairwise}


def _cluster_sort_key(cluster: dict) -> tuple:
    first = cluster["occurrences"][0] if cluster["occurrences"] else {"file": "", "start_line": 0}
    return (-cluster["tokens"], first["file"], first["start_line"])


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def fallback_linehash(repo_root: Path, abs_files: list[Path], min_tokens: int,
                       window: int = FALLBACK_WINDOW_LINES) -> dict:
    """Dependency-free heuristic: groups `window`-line normalized windows
    (whitespace collapsed, no indentation) that match exactly across two
    or more files. `min_tokens` is approximated by counting space-separated
    words inside the window; it is a deliberately rough approximation,
    hence the "epistemic": "Inferido" label."""
    buckets: dict[str, list[tuple[str, int]]] = {}
    for f in abs_files:
        if not f.exists():
            continue
        rel = _rel(f, repo_root)
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        normalized = [_normalize_line(line) for line in lines]
        for start in range(0, max(0, len(normalized) - window + 1)):
            block = normalized[start:start + window]
            if all(part == "" for part in block):
                continue
            key = "\x1f".join(block)
            buckets.setdefault(key, []).append((rel, start + 1))

    clusters = []
    pairwise: dict[str, int] = {}
    for key, occ in buckets.items():
        distinct_files = {f for f, _ in occ}
        if len(distinct_files) < 2:
            continue
        approx_tokens = sum(len(part.split()) for part in key.split("\x1f"))
        if approx_tokens < min_tokens:
            continue
        occurrences = sorted(
            ({"file": f, "start_line": s, "end_line": s + window - 1} for f, s in occ),
            key=lambda o: (o["file"], o["start_line"]),
        )
        clusters.append({
            "tokens": approx_tokens,
            "lines": window,
            "occurrences": occurrences,
            "tool": "fallback-linehash",
            "epistemic": "Inferido",
        })
        distinct = sorted(distinct_files)
        for i in range(len(distinct)):
            for j in range(i + 1, len(distinct)):
                pkey = f"{distinct[i]}|{distinct[j]}"
                pairwise[pkey] = pairwise.get(pkey, 0) + approx_tokens

    clusters.sort(key=_cluster_sort_key)
    return {
        "clusters": clusters,
        "pairwise": pairwise,
        "tool": "fallback-linehash",
        "epistemic": "Inferido",
    }


def analyze(tools_root: Path, repo_root: Path, rel_files: list[str], min_tokens: int) -> dict:
    abs_files = [Path(repo_root) / f for f in rel_files]
    if _pmd_available(tools_root):
        result = run_pmd_cpd(find_pmd_bin(tools_root), Path(repo_root), abs_files, min_tokens)
        result["tool"] = "pmd-cpd"
        return result
    return fallback_linehash(Path(repo_root), abs_files, min_tokens)


def choose_default_min_tokens(calibration: dict) -> int:
    """The bin/metrics.sh rule: the smallest calibrated threshold whose
    cluster count is <= 40; if none qualifies, a fixed 100."""
    for threshold in sorted((int(k) for k in calibration), key=int):
        if calibration[str(threshold)]["clusters"] <= 40:
            return threshold
    return 100


def calibrate(tools_root: Path, repo_root: Path, targets: list[str]) -> dict:
    table = {}
    for min_tokens in CALIBRATION_THRESHOLDS:
        result = analyze(tools_root, repo_root, list(targets), min_tokens)
        total_tokens = sum(c["tokens"] for c in result["clusters"])
        table[str(min_tokens)] = {
            "clusters": len(result["clusters"]),
            "tokens": total_tokens,
            "tool": result.get("tool", "pmd-cpd"),
            "pairwise": result["pairwise"],
        }
    return table


def default_main_files(repo_root: Path) -> list[str]:
    modules = repo_scan.list_modules(repo_root)
    return [rel for _module, rel in repo_scan.kotlin_files(repo_root, modules, "main")]


CPD_CONFIG_PATH_NAME = "cpd.json"


def cpd_config_path(tools_root: Path) -> Path:
    return tools_root / "config" / CPD_CONFIG_PATH_NAME


def duplication_targets_config_path(tools_root: Path) -> Path:
    return tools_root / "config" / DUPLICATION_TARGETS_CONFIG_NAME


def load_calibration_targets(tools_root: Path) -> list[str]:
    """Reads the duplication candidate files from
    config/duplication-targets.json. Empty (or the file missing) is a
    valid configuration: it means "this project has not declared
    candidates yet", but --calibrate without --calibrate-files needs at
    least one, so main()'s caller decides whether that is an error."""
    path = duplication_targets_config_path(tools_root)
    if not path.exists():
        return []
    return list(baseline.load_json(path).get("targets", []))


def load_fixed_min_tokens(tools_root: Path) -> int:
    """Reads the fixed threshold from config/cpd.json. Recalibrating is a
    deliberate change (with its own change card), not something each run
    decides on its own: that is why this fails hard if the file does not
    exist, instead of inventing a default value."""
    path = cpd_config_path(tools_root)
    if not path.exists():
        raise SystemExit(
            f"no calibrated threshold at {path}: run "
            f"'lib/duplication_cpd.py <repo> --calibrate' first"
        )
    return baseline.load_json(path)["min_tokens"]


def write_calibration(tools_root: Path, repo_root: Path, repo_sha: str, versions: dict,
                       repo_dirty: bool, targets: list[str]) -> int:
    """Runs the sweep over `targets`, leaves the full evidence in
    out/<repo_sha>/duplication-calibration.json, and fixes the threshold
    for normal use in config/cpd.json. Returns the chosen threshold."""
    calibration_table = calibrate(tools_root, repo_root, targets)
    chosen_default = choose_default_min_tokens(calibration_table)

    calibration_payload = baseline.base_envelope(tools_root, repo_sha, versions, repo_dirty)
    calibration_payload.update({
        "targets": sorted(targets),
        "thresholds": calibration_table,
        "chosen_default_min_tokens": chosen_default,
    })
    out_dir = tools_root / "out" / repo_sha
    baseline.write_json(out_dir / "duplication-calibration.json", calibration_payload)

    baseline.write_json(cpd_config_path(tools_root), {
        "min_tokens": chosen_default,
        "calibrated_on": repo_sha,
        "note": "recalibrating is a change with a change card",
    })
    return chosen_default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--min-tokens", type=int, default=None)
    parser.add_argument("--files", default=None, help="comma-separated list, relative to the repo")
    parser.add_argument(
        "--calibrate", action="store_true",
        help="sweeps the thresholds over the targets in config/duplication-targets.json (or --calibrate-files) and fixes config/cpd.json (deliberate change)",
    )
    parser.add_argument(
        "--calibrate-files", default=None,
        help="comma-separated list; overrides config/duplication-targets.json for this --calibrate run, without touching the file",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    versions = toolenv.tool_versions(TOOLS_ROOT)
    out_dir = TOOLS_ROOT / "out" / repo_sha

    if args.calibrate:
        if args.calibrate_files:
            targets = sorted(f.strip() for f in args.calibrate_files.split(",") if f.strip())
        else:
            targets = sorted(load_calibration_targets(TOOLS_ROOT))
        if not targets:
            raise SystemExit(
                f"no calibration files configured at "
                f"{duplication_targets_config_path(TOOLS_ROOT)} (or pass --calibrate-files a.kt,b.kt,...)"
            )
        chosen_default = write_calibration(TOOLS_ROOT, repo_root, repo_sha, versions, repo_dirty, targets)
        min_tokens = args.min_tokens if args.min_tokens is not None else chosen_default
    else:
        min_tokens = args.min_tokens if args.min_tokens is not None else load_fixed_min_tokens(TOOLS_ROOT)

    if args.files:
        rel_files = sorted(f.strip() for f in args.files.split(",") if f.strip())
    else:
        rel_files = default_main_files(repo_root)

    result = analyze(TOOLS_ROOT, repo_root, rel_files, min_tokens)
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update({
        "min_tokens": min_tokens,
        "files_analyzed": rel_files,
        "clusters": result["clusters"],
        "pairwise": result["pairwise"],
        "tool": result.get("tool", "pmd-cpd"),
    })
    baseline.write_json(out_dir / "duplication.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
