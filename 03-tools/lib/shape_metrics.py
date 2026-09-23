#!/usr/bin/env python3
"""Shape metrics over a repo's Kotlin sources (P0, no real AST).

Everything that is not a direct textual count (`var`, `!!`, `lateinit`, ...) is
heuristic and declares itself as such: the function-length histogram uses a
naive brace-depth counter (it does not distinguish a brace inside a string
template), which is why it carries "epistemic": "Inferido" in the payload
itself instead of pretending compiler-level precision.

Usage:
    lib/shape_metrics.py <repo> [--modules a,b]

Writes out/<repo_sha>/metrics.json and metrics.md (the tools repo, not the
analyzed repo).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, repo_scan, toolenv  # noqa: E402

FUN_MODIFIERS = (
    "public", "private", "protected", "internal", "open", "final", "abstract",
    "override", "suspend", "inline", "external", "actual", "expect", "infix",
    "operator", "tailrec", "inner", "crossinline", "noinline", "vararg",
    "lateinit", "const", "sealed", "data", "annotation", "companion", "value",
)
FUN_DECL_RE = re.compile(r"^\s*(?:(?:" + "|".join(FUN_MODIFIERS) + r")\s+)*fun\s+[<\w]")
VAR_RE = re.compile(r"\bvar\b")
BANG_BANG_RE = re.compile(r"!!")
LATEINIT_RE = re.compile(r"\blateinit\b")
GLOBAL_SCOPE_RE = re.compile(r"\bGlobalScope\b")
RUN_BLOCKING_RE = re.compile(r"\brunBlocking\b")
LOG_IMPORT_RE = re.compile(r"android\.util\.Log")
LOG_CALL_RE = re.compile(r"Log\.[dweiv]\(")
PRINTLN_RE = re.compile(r"println\(")
PRINT_STACK_TRACE_RE = re.compile(r"printStackTrace\(")
ELSE_ARROW_RE = re.compile(r"else\s*->")
TEST_ANNOTATION_RE = re.compile(r"@Test\b")
LINT_ISSUE_RE = re.compile(r"<issue\b")

HISTOGRAM_BUCKETS = ("1-20", "21-50", "51-100", "101+")

NUMERIC_FIELDS = (
    "loc", "non_blank_loc", "fun_count", "var_count", "bang_bang_count",
    "lateinit_count", "global_scope_count", "run_blocking_count",
    "android_util_log_count", "log_call_count", "println_count",
    "print_stack_trace_count", "else_arrow_count",
)


def _bucket_for_length(n: int) -> str:
    if n <= 20:
        return "1-20"
    if n <= 50:
        return "21-50"
    if n <= 100:
        return "51-100"
    return "101+"


def _find_fun_end_line(lines: list[str], start: int, limit: int) -> int:
    """Brace-depth heuristic: advances from `start` until the brace that
    opens the body closes again. An expression-body function with no
    braces (`fun foo() = x`) counts as a single line."""
    depth = 0
    seen_open = False
    for i in range(start, limit):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}":
                depth -= 1
        if seen_open and depth <= 0:
            return i
    return start


def _fun_length_histogram(lines: list[str]) -> dict:
    decl_indices = [i for i, line in enumerate(lines) if FUN_DECL_RE.match(line)]
    histogram = {b: 0 for b in HISTOGRAM_BUCKETS}
    n_lines = len(lines)
    for idx, start in enumerate(decl_indices):
        limit = decl_indices[idx + 1] if idx + 1 < len(decl_indices) else n_lines
        end_line = _find_fun_end_line(lines, start, limit)
        length = end_line - start + 1
        histogram[_bucket_for_length(length)] += 1
    return histogram


def analyze_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "loc": len(lines),
        "non_blank_loc": sum(1 for line in lines if line.strip()),
        "fun_count": sum(1 for line in lines if FUN_DECL_RE.match(line)),
        "fun_length_histogram": _fun_length_histogram(lines),
        "var_count": len(VAR_RE.findall(text)),
        "bang_bang_count": len(BANG_BANG_RE.findall(text)),
        "lateinit_count": len(LATEINIT_RE.findall(text)),
        "global_scope_count": len(GLOBAL_SCOPE_RE.findall(text)),
        "run_blocking_count": len(RUN_BLOCKING_RE.findall(text)),
        "android_util_log_count": len(LOG_IMPORT_RE.findall(text)),
        "log_call_count": len(LOG_CALL_RE.findall(text)),
        "println_count": len(PRINTLN_RE.findall(text)),
        "print_stack_trace_count": len(PRINT_STACK_TRACE_RE.findall(text)),
        "else_arrow_count": len(ELSE_ARROW_RE.findall(text)),
    }


def _empty_totals() -> dict:
    totals = {field: 0 for field in NUMERIC_FIELDS}
    totals["files_count"] = 0
    totals["files_over_500"] = 0
    totals["fun_length_histogram"] = {b: 0 for b in HISTOGRAM_BUCKETS}
    return totals


def _add_file_to_totals(totals: dict, file_metrics: dict) -> None:
    for field in NUMERIC_FIELDS:
        totals[field] += file_metrics[field]
    totals["files_count"] += 1
    if file_metrics["loc"] > 500:
        totals["files_over_500"] += 1
    for bucket, count in file_metrics["fun_length_histogram"].items():
        totals["fun_length_histogram"][bucket] += count


def _rule_signals(repo_totals: dict, style_guide_map: dict) -> dict:
    signals = {}
    for rule_id in sorted(style_guide_map):
        metric_names = style_guide_map[rule_id]
        if not metric_names:
            signals[rule_id] = None
        else:
            signals[rule_id] = sum(repo_totals.get(name, 0) for name in metric_names)
    return signals


def build_metrics(repo_root: Path, modules: list[str], style_guide_map: dict) -> dict:
    per_file = []
    module_totals: dict[str, dict] = {}
    repo_totals = _empty_totals()

    for module, rel_path in repo_scan.kotlin_files(repo_root, modules, "main"):
        metrics = analyze_file(repo_root / rel_path)
        per_file.append({"path": rel_path, "module": module, **metrics})
        module_totals.setdefault(module, _empty_totals())
        _add_file_to_totals(module_totals[module], metrics)
        _add_file_to_totals(repo_totals, metrics)

    test_counts_by_module: dict[str, int] = {}
    for module, rel_path in repo_scan.kotlin_files(repo_root, modules, "test"):
        text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
        count = len(TEST_ANNOTATION_RE.findall(text))
        test_counts_by_module[module] = test_counts_by_module.get(module, 0) + count

    lint_baseline_path = repo_root / "app" / "lint-baseline.xml"
    lint_baseline_issue_count = 0
    if lint_baseline_path.exists():
        text = lint_baseline_path.read_text(encoding="utf-8", errors="replace")
        lint_baseline_issue_count = len(LINT_ISSUE_RE.findall(text))

    return {
        "files": sorted(per_file, key=lambda f: f["path"]),
        "modules": {m: module_totals[m] for m in sorted(module_totals)},
        "totals": repo_totals,
        "test_counts_by_module": dict(sorted(test_counts_by_module.items())),
        "lint_baseline_issue_count": lint_baseline_issue_count,
        "rule_signals": _rule_signals(repo_totals, style_guide_map),
    }


def render_markdown(payload: dict) -> str:
    lines = ["# shape_metrics", "", f"repo_sha: `{payload['repo_sha']}`", "",
              "## Repo totals", "", "| metric | value |", "|---|---|"]
    totals = payload["totals"]
    for key in sorted(k for k in totals if k != "fun_length_histogram"):
        lines.append(f"| {key} | {totals[key]} |")

    lines += ["", "### Function-length histogram (repo)", "",
              "| bucket | functions |", "|---|---|"]
    for bucket in HISTOGRAM_BUCKETS:
        lines.append(f"| {bucket} | {totals['fun_length_histogram'][bucket]} |")

    lines += ["", "## By module", "",
              "| module | files | loc | fun_count | files_over_500 |", "|---|---|---|---|---|"]
    for module in sorted(payload["modules"]):
        m = payload["modules"][module]
        lines.append(f"| {module} | {m['files_count']} | {m['loc']} | {m['fun_count']} | {m['files_over_500']} |")

    lines += ["", "## Tests by module (@Test)", "", "| module | @Test |", "|---|---|"]
    for module, count in sorted(payload["test_counts_by_module"].items()):
        lines.append(f"| {module} | {count} |")

    lines += ["", f"## lint-baseline.xml: {payload['lint_baseline_issue_count']} issues"]

    lines += ["", "## Signals per style rule", "", "| rule | signal |", "|---|---|"]
    for rule_id in sorted(payload["rule_signals"]):
        value = payload["rule_signals"][rule_id]
        lines.append(f"| {rule_id} | {value if value is not None else '-'} |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--modules", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    all_modules = repo_scan.list_modules(repo_root)
    requested = args.modules.split(",") if args.modules else None
    modules = repo_scan.filter_modules(all_modules, requested)
    style_guide_map = baseline.load_json(TOOLS_ROOT / "config" / "style-guide-map.json")

    content = build_metrics(repo_root, modules, style_guide_map)
    versions = toolenv.tool_versions(TOOLS_ROOT)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update(content)

    out_dir = TOOLS_ROOT / "out" / repo_sha
    baseline.write_json(out_dir / "metrics.json", payload)
    (out_dir / "metrics.md").write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
