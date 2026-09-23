#!/usr/bin/env python3
"""Assembles out/benchmark/<shaA7>..<shaB7>.json from what
shape_metrics/duplication_cpd/dep_boundaries/domain_invariants already
wrote for two shas (bin/benchmark-release.sh runs those four scripts per
sha before calling here: this module only aggregates and compares, it
never rescans).

Groups the delta in three ways: by style rule (config/style-guide-
map.json, with ARCH-006 resolved separately from duplication.json), by
protected property (config/property-hierarchy-map.json), and by change
card for each commit in the range (git log, parsed by hand, each body
passed to change_card_validator.validate/parse_fields imported
directly, never through subprocess). It also records explicitly what
was NOT measured (APK, bench timings, coverage...): a declared gap is
not the same as a hidden one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, change_card_validator, toolenv  # noqa: E402

NOT_MEASURED = [
    {
        "metric": "apk_size",
        "reason": "requires building and signing a release APK; this tools repo does not invoke Gradle",
        "how_to_get_it": "gradle assemble_prod_NON_GMSRelease on each sha, then compare the size of app/build/outputs/apk",
    },
    {
        "metric": "apk_diff",
        "reason": "requires both signed APKs and a binary/resource diff tool",
        "how_to_get_it": "apkanalyzer or diffuse on the two APKs from assemble_prod_NON_GMSRelease",
    },
    {
        "metric": "deps_diff",
        "reason": "requires resolving the Gradle dependency tree, not just reading the build files",
        "how_to_get_it": "gradle :app:dependencies (or app/deps/*.txt if the repo already versions them), diffed between shas",
    },
    {
        "metric": "boot_time_median",
        "reason": "a test bench timing with real hardware, not something a static script can measure",
        "how_to_get_it": "the physical test bench protocol (real device): stopwatch/logcat against a real PoS, median of N boots",
    },
    {
        "metric": "tap_to_approved_median",
        "reason": "same: the time of a real card tap against a physical reader",
        "how_to_get_it": "test bench with the real EMV kernel, median of N charges",
    },
    {
        "metric": "coverage",
        "reason": "requires running the tests with coverage instrumentation, not just counting them",
        "how_to_get_it": "gradle jacocoTestReport (or similar) per variant and module",
    },
    {
        "metric": "mutation_score",
        "reason": "requires a mutation engine running the full suite, far more expensive than this static analysis",
        "how_to_get_it": "pitest (or a Kotlin equivalent) on the modules with the most money at stake",
    },
]


def resolve_sha(repo_root: Path, ref: str) -> str:
    """Fails hard if `ref` does not resolve. Never triggers an implicit
    `git fetch`: if the ref is missing, that is the caller's error, not
    something this script should fix by fetching more on its own."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"ref '{ref}' does not resolve in {repo_root} (is a manual fetch needed? "
            f"this script does not do that on its own): {exc.stderr.strip()}"
        )
    return out.stdout.strip()


def metrics_dir(tools_root: Path, sha: str) -> Path:
    return tools_root / "out" / sha


def has_cached_metrics(tools_root: Path, sha: str) -> bool:
    return (metrics_dir(tools_root, sha) / "metrics.json").exists()


def load_sha_payloads(tools_root: Path, sha: str) -> dict:
    out_dir = metrics_dir(tools_root, sha)
    return {
        "metrics": baseline.load_json(out_dir / "metrics.json"),
        "duplication": baseline.load_json(out_dir / "duplication.json"),
        "deps": baseline.load_json(out_dir / "deps.json"),
        "domain_invariants": baseline.load_json(out_dir / "domain-invariants.json"),
    }


def duplication_summary(duplication_payload: dict) -> dict:
    clusters = duplication_payload["clusters"]
    return {"clusters": len(clusters), "tokens": sum(c["tokens"] for c in clusters)}


def domain_invariants_counts(payload: dict) -> dict:
    """One number per invariant: how many evidence sites the script found
    (domain_invariants.py: by_invariant[inv].evidence). Presence, not
    proof: the delta says whether the mechanism backing an invariant
    grew, shrank, or disappeared between two refs."""
    return {inv: len(entry.get("evidence", [])) for inv, entry in sorted(payload.get("by_invariant", {}).items())}


def domain_invariants_delta(payload_a: dict, payload_b: dict) -> dict:
    before, after = domain_invariants_counts(payload_a), domain_invariants_counts(payload_b)
    return {
        inv: {"before": before.get(inv, 0), "after": after.get(inv, 0), "delta": after.get(inv, 0) - before.get(inv, 0)}
        for inv in sorted(set(before) | set(after))
    }


SHAPE_TOTAL_FIELDS_EXCLUDED = frozenset({"fun_length_histogram"})

RESERVED_KEY_ARCH_006 = "ARCH-006"
METRIC_DIRECTIONS_KEY = "metric_directions"

# fun_length_histogram is deliberately left out of
# config/style-guide-map.json: shape_metrics._rule_signals blindly sums
# repo_totals.get(name, 0) for every name hanging off any key in that
# JSON (metric_directions included), and fun_length_histogram is a dict
# of buckets, not an integer: summing it there blows up with TypeError.
# It is declared here, not in the config, and is neutral just like
# loc/files_count/fun_count.
IMPLICIT_NEUTRAL_METRIC_BASES = frozenset({"fun_length_histogram"})


def rule_deltas(style_guide_map: dict, metrics_a: dict, metrics_b: dict, dup_a: dict, dup_b: dict) -> tuple[dict, dict]:
    """(by_rule, unmapped_metrics). ARCH-006 does not come from
    shape_metrics' rule_signals (that mechanism only sums shape_metrics.py
    metrics): it comes from duplication.json, separately."""
    signals_a, signals_b = metrics_a["rule_signals"], metrics_b["rule_signals"]

    by_rule = {}
    for rule_id in sorted(style_guide_map):
        if rule_id in (RESERVED_KEY_ARCH_006, METRIC_DIRECTIONS_KEY):
            continue
        before, after = signals_a.get(rule_id), signals_b.get(rule_id)
        if before is None and after is None:
            continue
        by_rule[rule_id] = {"before": before, "after": after, "delta": (after or 0) - (before or 0)}

    dup_before, dup_after = duplication_summary(dup_a), duplication_summary(dup_b)
    by_rule[RESERVED_KEY_ARCH_006] = {
        "before": dup_before,
        "after": dup_after,
        "delta": {
            "clusters": dup_after["clusters"] - dup_before["clusters"],
            "tokens": dup_after["tokens"] - dup_before["tokens"],
        },
    }

    # metric_directions is direction metadata (lower/higher_is_better,
    # neutral), not a style rule: if it entered mapped_names, its
    # metric_names would vanish from unmapped_metrics without gaining a
    # real row in by_rule (excluded above, in the loop itself).
    mapped_names = {
        name for rule_id, names in style_guide_map.items() if rule_id != METRIC_DIRECTIONS_KEY for name in names
    }
    all_names = set(metrics_a["totals"]) - SHAPE_TOTAL_FIELDS_EXCLUDED
    unmapped = {}
    for name in sorted(all_names - mapped_names):
        before, after = metrics_a["totals"][name], metrics_b["totals"][name]
        unmapped[name] = {"before": before, "after": after, "delta": after - before}

    return by_rule, unmapped


def property_groups(property_hierarchy: dict, by_rule: dict) -> dict:
    """Groups by_rule according to config/property-hierarchy-map.json,
    respecting its property_order. A rule with no entry in 'rules' falls
    into a separate bucket instead of getting lost; a rule whose declared
    property is NOT in property_order (possible: the map says "v1 not
    reviewed") is also reported, at the end, instead of silently
    disappearing."""
    rules_meta = property_hierarchy.get("rules", {})
    order = list(property_hierarchy.get("property_order", []))
    fallback = "(no property assigned)"

    groups: dict[str, dict] = {prop: {} for prop in order}
    for rule_id, delta in by_rule.items():
        prop = rules_meta.get(rule_id, {}).get("property", fallback)
        groups.setdefault(prop, {})[rule_id] = delta

    extra_keys = sorted(k for k in groups if k not in order and k != fallback)
    ordered_keys = order + extra_keys + ([fallback] if fallback in groups else [])

    return {
        "status": property_hierarchy.get("status", "unknown"),
        "property_order": order,
        "groups": {key: groups[key] for key in ordered_keys},
    }


def _totals_delta_by_base_name(totals_delta: dict) -> dict[str, int]:
    """totals_delta carries keys 'totals.<name>' (and, for the histogram,
    'totals.fun_length_histogram.<bucket>'). Grouped by the first segment
    after 'totals.' so the delta of a shape_metrics metric can be looked
    up by its bare name, without the caller needing to know the prefix.
    Histogram buckets are summed together: the exact shape does not
    matter, only that it changed (it is neutral either way)."""
    out: dict[str, int] = {}
    for key, entry in totals_delta.get("changed", {}).items():
        base = key.removeprefix("totals.").split(".", 1)[0]
        out[base] = out.get(base, 0) + entry["delta"]
    return out


def _direction_for(base_name: str, metric_directions: dict) -> str | None:
    if base_name in IMPLICIT_NEUTRAL_METRIC_BASES:
        return "neutral"
    return metric_directions.get(base_name)


def classified_deltas(style_guide_map: dict, payload: dict) -> list[dict]:
    """Collects, with its declared direction (config/style-guide-map.json
    -> metric_directions), each payload delta for which that direction
    exists. Leaves out any metric without a declared direction: it never
    invents a verdict for what is not in the config."""
    metric_directions = style_guide_map.get(METRIC_DIRECTIONS_KEY, {})
    items: list[dict] = []

    for base, delta in _totals_delta_by_base_name(payload["totals_delta"]).items():
        direction = _direction_for(base, metric_directions)
        if direction:
            items.append({"metric": base, "delta": delta, "direction": direction})

    dup_delta = payload["by_rule"][RESERVED_KEY_ARCH_006]["delta"]
    for sub_key, canonical in (("clusters", "duplication_clusters"), ("tokens", "duplication_tokens")):
        direction = metric_directions.get(canonical)
        if direction:
            items.append({"metric": canonical, "delta": dup_delta[sub_key], "direction": direction})

    direction = metric_directions.get("dep_boundaries_violations")
    if direction:
        items.append({
            "metric": "dep_boundaries_violations", "delta": payload["dep_violations"]["delta"], "direction": direction,
        })

    direction = metric_directions.get("tests_total")
    if direction:
        items.append({"metric": "tests_total", "delta": payload["tests_total"]["delta"], "direction": direction})

    for field, entry in payload["domain_invariants_delta"].items():
        direction = metric_directions.get(field)
        if direction:
            items.append({"metric": field, "delta": entry["delta"], "direction": direction})

    return items


def by_direction(style_guide_map: dict, payload: dict) -> dict:
    """Classifies each delta with a known direction into 'mejora' (moved
    the good way), 'empeora' (moved the bad way), or 'sin_direccion'
    (neutral: it changed, but no direction is the good one). A zero delta
    says nothing and enters no bucket: that is why 'loc: +9369' can no
    longer sneak under "What improves" just by existing."""
    buckets: dict[str, list[dict]] = {"mejora": [], "empeora": [], "sin_direccion": []}
    for item in classified_deltas(style_guide_map, payload):
        delta, direction = item["delta"], item["direction"]
        if delta == 0:
            continue
        if direction == "neutral":
            bucket = "sin_direccion"
        elif direction == "higher_is_better":
            bucket = "mejora" if delta > 0 else "empeora"
        elif direction == "lower_is_better":
            bucket = "mejora" if delta < 0 else "empeora"
        else:
            continue
        buckets[bucket].append(item)
    for key in buckets:
        buckets[key].sort(key=lambda e: e["metric"])
    return buckets


def parse_commit_log(repo_root: Path, ref_range: str) -> list[dict]:
    """git log with %B%n==END== as separator: %B already carries its own
    line breaks, so a standalone-line delimiter is the only safe way to
    know where one commit body ends and the next sha begins."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "log", ref_range, "--format=%H%n%B%n==END=="],
        check=True, capture_output=True, text=True,
    )
    commits = []
    for chunk in out.stdout.split("==END==\n"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, _, body = chunk.partition("\n")
        commits.append({"sha": sha.strip(), "body": body})
    return commits


def change_card_summary(repo_root: Path, ref_range: str) -> dict:
    commits = parse_commit_log(repo_root, ref_range)
    with_card = []
    for commit in commits:
        fields, _errors = change_card_validator.parse_fields(commit["body"])
        if "For what" not in fields:
            continue
        result = change_card_validator.validate(commit["body"])
        with_card.append({
            "sha": commit["sha"][:7],
            "for_what": fields.get("For what"),
            "invariant": fields.get("Invariant"),
            "verdict": result["verdict"],
        })
    with_card.sort(key=lambda c: c["sha"])
    return {
        "total_commits": len(commits),
        "commits_with_card": len(with_card),
        "k_of_n": f"{len(with_card)}-of-{len(commits)}",
        "cards": with_card,
    }


def build_benchmark(tools_root: Path, repo_root: Path, sha_a: str, sha_b: str, ref_a: str, ref_b: str) -> dict:
    payloads_a = load_sha_payloads(tools_root, sha_a)
    payloads_b = load_sha_payloads(tools_root, sha_b)

    style_guide_map = baseline.load_json(tools_root / "config" / "style-guide-map.json")
    property_hierarchy = baseline.load_json(tools_root / "config" / "property-hierarchy-map.json")

    by_rule, unmapped_metrics = rule_deltas(
        style_guide_map, payloads_a["metrics"], payloads_b["metrics"],
        payloads_a["duplication"], payloads_b["duplication"],
    )
    by_property = property_groups(property_hierarchy, by_rule)
    cards = change_card_summary(repo_root, f"{sha_a}..{sha_b}")

    totals_a, totals_b = payloads_a["metrics"]["totals"], payloads_b["metrics"]["totals"]
    totals_delta = baseline.delta({"totals": totals_a}, {"totals": totals_b})

    tests_a = sum(payloads_a["metrics"]["test_counts_by_module"].values())
    tests_b = sum(payloads_b["metrics"]["test_counts_by_module"].values())

    violations_a = len(payloads_a["deps"]["violations"])
    violations_b = len(payloads_b["deps"]["violations"])

    result = {
        "ref_a": ref_a,
        "ref_b": ref_b,
        "sha_a": sha_a,
        "sha_b": sha_b,
        "totals_delta": totals_delta,
        "tests_total": {"before": tests_a, "after": tests_b, "delta": tests_b - tests_a},
        "dep_violations": {"before": violations_a, "after": violations_b, "delta": violations_b - violations_a},
        "by_rule": by_rule,
        "unmapped_metrics": unmapped_metrics,
        "by_property": by_property,
        "domain_invariants_delta": domain_invariants_delta(payloads_a["domain_invariants"], payloads_b["domain_invariants"]),
        "change_cards": cards,
        "not_measured": NOT_MEASURED,
    }
    # by_direction reads from result (totals_delta/by_rule/dep_violations/
    # tests_total/domain_invariants_delta already set above), so it is
    # computed last and added separately instead of trying to fit it in
    # the same literal.
    result["by_direction"] = by_direction(style_guide_map, result)
    return result


def _fmt_delta(n) -> str:
    if isinstance(n, dict):
        return ", ".join(f"{k}: {_fmt_delta(v)}" for k, v in sorted(n.items()))
    return f"+{n}" if isinstance(n, (int, float)) and n > 0 else str(n)


def _fmt_value(n) -> str:
    """Like _fmt_delta but without the leading '+': a 'before'/'after' is
    an absolute value (30 files), not a change, and showing it as '+30'
    suggests otherwise."""
    if isinstance(n, dict):
        return ", ".join(f"{k}: {_fmt_value(v)}" for k, v in sorted(n.items()))
    return str(n)


def render_markdown(payload: dict) -> str:
    lines = [
        "# release benchmark", "",
        f"`{payload['ref_a']}` ({payload['sha_a'][:7]}) -> `{payload['ref_b']}` ({payload['sha_b'][:7]})", "",
    ]

    lines += ["## Summary", "", "| metric | before | after | delta |", "|---|---|---|---|"]
    totals = payload["totals_delta"]
    interesting = sorted(set(totals["added"]) | set(totals["removed"]) | set(totals["changed"]))
    for key in interesting:
        if key in totals["changed"]:
            c = totals["changed"][key]
            lines.append(f"| {key} | {c['before']} | {c['after']} | {_fmt_delta(c['delta'])} |")
    lines.append(f"| tests (total) | {payload['tests_total']['before']} | {payload['tests_total']['after']} | {_fmt_delta(payload['tests_total']['delta'])} |")
    lines.append(f"| dep_boundaries violations | {payload['dep_violations']['before']} | {payload['dep_violations']['after']} | {_fmt_delta(payload['dep_violations']['delta'])} |")

    by_dir = payload["by_direction"]
    lines += ["", "## What improves", ""]
    if by_dir["mejora"]:
        for entry in by_dir["mejora"]:
            lines.append(f"- {entry['metric']}: {_fmt_delta(entry['delta'])}")
    else:
        lines.append("- (nothing moved in the good direction)")

    lines += ["", "## What gets worse", ""]
    if by_dir["empeora"]:
        for entry in by_dir["empeora"]:
            lines.append(f"- {entry['metric']}: {_fmt_delta(entry['delta'])}")
    else:
        lines.append("- (nothing moved in the bad direction)")

    lines += ["", "## Changes without direction", ""]
    if by_dir["sin_direccion"]:
        for entry in by_dir["sin_direccion"]:
            lines.append(f"- {entry['metric']}: {_fmt_delta(entry['delta'])}")
    else:
        lines.append("- (no neutral changes)")

    lines += ["", "## Why", ""]
    cards = payload["change_cards"]
    if cards["commits_with_card"] == 0:
        lines.append(f"No commit in the range carries a change card ({cards['k_of_n']}). "
                      "This release's 'why' is not in the commits, only in the code.")
    else:
        lines.append(f"{cards['k_of_n']} commits with a card:")
        lines += ["", "| sha | For what | Invariant | verdict |", "|---|---|---|---|"]
        for card in cards["cards"]:
            lines.append(f"| {card['sha']} | {card['for_what']} | {card['invariant']} | {card['verdict']} |")

    lines += ["", "## How (deltas by style rule)", "", "| rule | before | after | delta |", "|---|---|---|---|"]
    for rule_id in sorted(payload["by_rule"]):
        d = payload["by_rule"][rule_id]
        lines.append(f"| {rule_id} | {_fmt_value(d['before'])} | {_fmt_value(d['after'])} | {_fmt_delta(d['delta'])} |")
    if payload["unmapped_metrics"]:
        lines += ["", "### Metrics without an assigned rule", "", "| metric | before | after | delta |", "|---|---|---|---|"]
        for name in sorted(payload["unmapped_metrics"]):
            d = payload["unmapped_metrics"][name]
            lines.append(f"| {name} | {d['before']} | {d['after']} | {_fmt_delta(d['delta'])} |")

    lines += ["", "### Domain invariant presence (domain_invariants)", "", "| check | before | after | delta |", "|---|---|---|---|"]
    for field in sorted(payload["domain_invariants_delta"]):
        d = payload["domain_invariants_delta"][field]
        lines.append(f"| {field} | {d['before']} | {d['after']} | {_fmt_delta(d['delta'])} |")

    lines += ["", f"## What it does (by protected property: {payload['by_property']['status']})", ""]
    for prop in payload["by_property"]["groups"]:
        rules = payload["by_property"]["groups"][prop]
        if not rules:
            continue
        lines.append(f"### {prop}")
        lines += ["", "| rule | delta |", "|---|---|"]
        for rule_id in sorted(rules):
            lines.append(f"| {rule_id} | {_fmt_delta(rules[rule_id]['delta'])} |")
        lines.append("")

    lines += ["## What was NOT measured", "", "| metric | why | how to get it |", "|---|---|---|"]
    for entry in payload["not_measured"]:
        lines.append(f"| {entry['metric']} | {entry['reason']} | {entry['how_to_get_it']} |")

    lines += ["", "## tool_versions", "", "| tool | version |", "|---|---|"]
    for tool, version in sorted(payload["tool_versions"].items()):
        lines.append(f"| {tool} | {version} |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("ref_a")
    parser.add_argument("ref_b")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    sha_a = resolve_sha(repo_root, args.ref_a)
    sha_b = resolve_sha(repo_root, args.ref_b)

    content = build_benchmark(TOOLS_ROOT, repo_root, sha_a, sha_b, args.ref_a, args.ref_b)
    versions = toolenv.tool_versions(TOOLS_ROOT)
    # the benchmark compares two shas of the analyzed repo: there is no
    # single repo_sha to describe it, so the header uses sha_b (the tip
    # of the range) as the reference, and both stay explicit in the
    # content (ref_a/sha_a, ref_b/sha_b). repo_dirty belongs to the
    # checkout passed as <repo> (normally the real working tree, not a
    # disposable worktree), not to sha_a/sha_b themselves.
    repo_dirty = baseline.is_repo_dirty(repo_root)
    payload = baseline.base_envelope(TOOLS_ROOT, sha_b, versions, repo_dirty)
    payload.update(content)

    out_dir = TOOLS_ROOT / "out" / "benchmark"
    stem = f"{sha_a[:7]}..{sha_b[:7]}"
    baseline.write_json(out_dir / f"{stem}.json", payload)
    (out_dir / f"{stem}.md").write_text(render_markdown(payload), encoding="utf-8")

    print(f"output at: {out_dir}/{stem}.json and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
