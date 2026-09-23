#!/usr/bin/env python3
"""Boundaries between modules: node map (config/dep-boundaries.json) against
the actual `import`s in <repo>'s Kotlin sources.

v1, tagged "Assumed"/"v1 unreviewed" in the config itself: the "nodes" are
not Gradle modules but hand-grouped packages (see the config for the
mapping). Each node's package prefixes are DERIVED by scanning `package X`
under its folders, never assumed, and are kept in the payload
(`derived_prefixes`) for the owner to review.

v1 rules (all of this comes from config/dep-boundaries.json, never hardcoded):
  - domain only imports domain/kotlin stdlib/kotlinx (domain_allowed_external_prefixes).
  - data does not import the raw prefixes in data_forbidden_raw_prefixes (typically
    android.*/androidx.*) nor any node whose name starts with data_forbidden_node_prefix.
  - the nodes listed in payment_purity_nodes do not import any of the
    prefixes in payment_purity_forbidden_prefixes (typically Android/DI/
    eventing/protobuf/room/vendor).
  - no node imports a vendor_packages package except the nodes listed in
    vendor_exempt_nodes (known and accepted legacy adapters).
  - cycle_pair declares a cycle known and discussed by the audit: both
    directions are counted as "cycle-candidate", without assuming which of
    the two is the forbidden one.

Usage:
    lib/dep_boundaries.py <repo> [--config config/dep-boundaries.json]

Writes out/<repo_sha>/deps.json and deps.md (the tools repo, not the analyzed repo).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, repo_scan, toolenv  # noqa: E402

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+(?:\.\*)?)(?:\s+as\s+\w+)?\s*$", re.MULTILINE)
FUN_NAME_RE = re.compile(r"\bfun\s+(?:<[^>]*>\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _kt_files_under(repo_root: Path, rel_dir: str) -> list[str]:
    """.kt files under `rel_dir` (already a full path inside the repo, not a
    module root that needs src/main appended), with the same exclusions as
    repo_scan (.claude/, build/)."""
    base = repo_root / rel_dir
    if not base.is_dir():
        return []
    results = []
    for path in base.rglob("*.kt"):
        rel = path.relative_to(repo_root)
        if repo_scan._is_excluded(rel.parts):  # reuses the filter, does not reimplement it
            continue
        results.append(rel.as_posix())
    return sorted(results)


def node_files(repo_root: Path, nodes: dict[str, list[str]]) -> dict[str, list[str]]:
    """{node: [.kt paths]}, without depending on whether the node matches a
    Gradle module (some nodes are subfolders of an app module). A catch-all
    node that declares a module's root is an ANCESTOR folder of more
    specific nodes: without disambiguation, its rglob would repeat those
    same files. So each file is assigned to the node whose configured
    folder is the most specific (the longest) among those that contain it:
    the same "longest prefix wins" criterion resolve_node uses for
    packages."""
    dir_entries = sorted(
        ((d, node) for node, dirs in nodes.items() for d in dirs),
        key=lambda pair: -len(pair[0]),
    )
    result: dict[str, list[str]] = {node: [] for node in nodes}
    claimed: set[str] = set()
    for dir_rel, node in dir_entries:
        for rel_path in _kt_files_under(repo_root, dir_rel):
            if rel_path in claimed:
                continue
            claimed.add(rel_path)
            result[node].append(rel_path)
    return {node: sorted(files) for node, files in result.items()}


def _first_package(repo_root: Path, rel_path: str) -> str | None:
    text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
    match = PACKAGE_RE.search(text)
    return match.group(1) if match else None


def _minimal_prefixes(packages: set[str]) -> list[str]:
    """Reduces a set of observed packages to the minimal set of prefixes
    that covers them all (if 'a.b' and 'a.b.c' are both present, only
    'a.b' remains). This way a node with many subpackages does not
    explode into a redundant list, and still covers subpackages not yet
    seen."""
    accepted: list[str] = []
    for pkg in sorted(packages, key=len):
        if not any(pkg == p or pkg.startswith(p + ".") for p in accepted):
            accepted.append(pkg)
    return sorted(accepted)


def derive_prefixes(repo_root: Path, files_by_node: dict[str, list[str]]) -> dict[str, list[str]]:
    result = {}
    for node, files in files_by_node.items():
        packages = {p for p in (_first_package(repo_root, f) for f in files) if p}
        result[node] = _minimal_prefixes(packages)
    return result


def _prefix_index(derived_prefixes: dict[str, list[str]]) -> list[tuple[str, str]]:
    """List of (prefix, node) sorted from longest to shortest prefix, so
    resolving an import always picks the most specific node."""
    pairs = [(prefix, node) for node, prefixes in derived_prefixes.items() for prefix in prefixes]
    return sorted(pairs, key=lambda pair: -len(pair[0]))


def resolve_node(import_target: str, prefix_index: list[tuple[str, str]]) -> str | None:
    target = import_target[:-2] if import_target.endswith(".*") else import_target
    for prefix, node in prefix_index:
        if target == prefix or target.startswith(prefix + "."):
            return node
    return None


def _imports_with_lines(repo_root: Path, rel_path: str) -> list[tuple[int, str]]:
    text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*import\s+([\w.]+(?:\.\*)?)(?:\s+as\s+\w+)?\s*$", line)
        if match:
            out.append((i, match.group(1)))
    return out


def _fun_names(repo_root: Path, rel_path: str) -> set[str]:
    text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
    return set(FUN_NAME_RE.findall(text))


def find_violations(
    repo_root: Path,
    config: dict,
    files_by_node: dict[str, list[str]],
    prefix_index: list[tuple[str, str]],
) -> tuple[list[dict], dict[str, int]]:
    violations = []
    edges: dict[str, int] = {}

    domain_allowed = tuple(config["domain_allowed_external_prefixes"])
    data_forbidden_raw = tuple(config["data_forbidden_raw_prefixes"])
    data_forbidden_node_prefix = config["data_forbidden_node_prefix"]
    payment_purity_nodes = set(config["payment_purity_nodes"])
    payment_purity_forbidden = tuple(config["payment_purity_forbidden_prefixes"])
    vendor_packages = tuple(config["vendor_packages"])
    vendor_exempt_nodes = set(config["vendor_exempt_nodes"])

    for node, files in files_by_node.items():
        for rel_path in files:
            for line, target in _imports_with_lines(repo_root, rel_path):
                to_node = resolve_node(target, prefix_index)

                if to_node is not None and to_node != node:
                    key = f"{node}->{to_node}"
                    edges[key] = edges.get(key, 0) + 1

                if node == "domain":
                    if to_node == "domain" or target.startswith(domain_allowed):
                        pass
                    else:
                        violations.append({
                            "file": rel_path, "line": line, "import": target,
                            "from_node": node, "to_node": to_node or target,
                            "rule": "domain-purity",
                        })

                if node == "data":
                    if target.startswith(data_forbidden_raw):
                        violations.append({
                            "file": rel_path, "line": line, "import": target,
                            "from_node": node, "to_node": target,
                            "rule": "data-boundary",
                        })
                    elif to_node is not None and to_node.startswith(data_forbidden_node_prefix):
                        violations.append({
                            "file": rel_path, "line": line, "import": target,
                            "from_node": node, "to_node": to_node,
                            "rule": "data-boundary",
                        })

                if node in payment_purity_nodes and target.startswith(payment_purity_forbidden):
                    violations.append({
                        "file": rel_path, "line": line, "import": target,
                        "from_node": node, "to_node": to_node or target,
                        "rule": "payment-purity",
                    })

                if target.startswith(vendor_packages) and node not in vendor_exempt_nodes:
                    violations.append({
                        "file": rel_path, "line": line, "import": target,
                        "from_node": node, "to_node": to_node or target,
                        "rule": "vendor-lockdown",
                    })

    violations.sort(key=lambda v: (v["file"], v["line"], v["rule"]))
    return violations, edges


def find_cycle_candidates(
    repo_root: Path,
    config: dict,
    files_by_node: dict[str, list[str]],
    prefix_index: list[tuple[str, str]],
) -> dict:
    node_a, node_b = config["cycle_pair"]
    directions = {f"{node_a}->{node_b}": (node_a, node_b), f"{node_b}->{node_a}": (node_b, node_a)}
    result = {key: {"count": 0, "occurrences": []} for key in directions}

    for key, (src, dst) in directions.items():
        for rel_path in files_by_node.get(src, []):
            for line, target in _imports_with_lines(repo_root, rel_path):
                if resolve_node(target, prefix_index) == dst:
                    result[key]["count"] += 1
                    result[key]["occurrences"].append(f"{rel_path}:{line}")
        result[key]["occurrences"].sort()
    return result


def find_adapter_law_candidates(
    repo_root: Path, files_by_node: dict[str, list[str]]
) -> list[dict]:
    """Name-based heuristic (Inferred): a file in app-ui/app-framework
    declares a function whose name also exists in domain or payment-api.
    Name match, nothing more: it does not look at signatures or types."""
    reference_names: dict[str, list[str]] = {}
    for node in ("domain", "payment-api"):
        for rel_path in files_by_node.get(node, []):
            for name in _fun_names(repo_root, rel_path):
                reference_names.setdefault(name, []).append(rel_path)

    candidates = []
    for node in ("app-ui", "app-framework"):
        for rel_path in files_by_node.get(node, []):
            text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), start=1):
                match = FUN_NAME_RE.search(line)
                if not match:
                    continue
                name = match.group(1)
                matches = reference_names.get(name)
                if matches:
                    candidates.append({
                        "file": rel_path,
                        "line": i,
                        "function": name,
                        "matches": sorted(set(matches)),
                        "epistemic": "Inferido",
                    })
    candidates.sort(key=lambda c: (c["file"], c["line"]))
    return candidates


def build_deps(repo_root: Path, config: dict) -> dict:
    files_by_node = node_files(repo_root, config["nodes"])
    derived_prefixes = derive_prefixes(repo_root, files_by_node)
    prefix_index = _prefix_index(derived_prefixes)

    violations, edges = find_violations(repo_root, config, files_by_node, prefix_index)
    cycle_candidates = find_cycle_candidates(repo_root, config, files_by_node, prefix_index)
    adapter_law_candidates = find_adapter_law_candidates(repo_root, files_by_node)

    nodes_seen = {node: len(files) for node, files in files_by_node.items()}

    return {
        "nodes_seen": dict(sorted(nodes_seen.items())),
        "derived_prefixes": {n: derived_prefixes[n] for n in sorted(derived_prefixes)},
        "edges_count_by_pair": dict(sorted(edges.items())),
        "violations": violations,
        "cycle_candidates": cycle_candidates,
        "adapter_law_candidates": adapter_law_candidates,
    }


def render_markdown(payload: dict) -> str:
    lines = ["# dep_boundaries", "", f"repo_sha: `{payload['repo_sha']}`", ""]

    lines += ["## Nodes seen (.kt files under their folders)", "", "| node | files | derived prefixes |", "|---|---|---|"]
    for node in sorted(payload["nodes_seen"]):
        prefixes = ", ".join(payload["derived_prefixes"].get(node, [])) or "-"
        lines.append(f"| {node} | {payload['nodes_seen'][node]} | {prefixes} |")

    lines += ["", "## Edges between nodes (import count)", "", "| from -> to | imports |", "|---|---|"]
    for pair in sorted(payload["edges_count_by_pair"]):
        lines.append(f"| {pair} | {payload['edges_count_by_pair'][pair]} |")

    lines += ["", f"## Violations ({len(payload['violations'])})", "", "| file | line | import | from | to | rule |", "|---|---|---|---|---|---|"]
    for v in payload["violations"]:
        lines.append(f"| {v['file']} | {v['line']} | {v['import']} | {v['from_node']} | {v['to_node']} | {v['rule']} |")

    lines += ["", "## Candidate cycle (counts both directions, does not assume which is forbidden)", "", "| direction | count |", "|---|---|"]
    for key in sorted(payload["cycle_candidates"]):
        lines.append(f"| {key} | {payload['cycle_candidates'][key]['count']} |")

    lines += ["", f"## Adapter Law candidates ({len(payload['adapter_law_candidates'])}, name-based heuristic, Inferred)",
              "", "| file | line | function | matches in |", "|---|---|---|---|"]
    for c in payload["adapter_law_candidates"][:200]:
        lines.append(f"| {c['file']} | {c['line']} | {c['function']} | {', '.join(c['matches'])} |")
    if len(payload["adapter_law_candidates"]) > 200:
        lines.append(f"| ... | | | {len(payload['adapter_law_candidates']) - 200} more, see deps.json |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    config_path = Path(args.config) if args.config else TOOLS_ROOT / "config" / "dep-boundaries.json"
    config = baseline.load_json(config_path)

    content = build_deps(repo_root, config)
    versions = toolenv.tool_versions(TOOLS_ROOT)
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update(content)

    out_dir = TOOLS_ROOT / "out" / repo_sha
    baseline.write_json(out_dir / "deps.json", payload)
    (out_dir / "deps.md").write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
