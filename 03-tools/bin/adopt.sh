#!/usr/bin/env bash
# Adapts a tools instance (a directory synced from this kit with
# bin/sync-instance.sh, e.g. ~/<project>-tools) to ONE project: writes the
# instance's config/project.json, the only per-project file.
#
# - A project.json that is missing, or byte-identical to the kit's own
#   config/project.json (synced but never adapted), is rebuilt from a GENERIC
#   skeleton + the facts lib/detect_repo.py reads from <repo> (language, build
#   files, base ref, ticket keys, test globs) + the owner's --answers.
# - A project.json already adapted by hand is preserved: only missing keys are
#   filled (generic, never critical-flow example values); docs_root is always set.
# - --critical-flow-example keeps the critical-flow domain start: its defaults in
#   project.json and the 4 full examples from config/examples/critical-flow/
#   (dep-boundaries, invariants-checks, duplication-targets,
#   property-hierarchy-map) copied over config/.
# - Run from the kit itself it refuses (exit 2): adapting the kit's tracked
#   template is almost always a mistake. Create an instance first
#   (bin/sync-instance.sh <instance>) and run <instance>/bin/adopt.sh, or
#   pass --allow-kit.
#
# Usage:
#   bin/adopt.sh <repo> <audit-folder> [--critical-flow-example] [--answers <json|file>]
#                  [--dry-run] [--allow-kit] [--kit <kit-03-tools-dir>]
#
# <audit-folder>: where the project's documentation lives (change cards,
#   invariants...), stored as given (typically "~/something"); readers expand ~.
# --answers: owner-interview values that win over detection, as inline JSON or
#   a JSON file. Keys: property_order, critical_properties, critical_paths,
#   ticket_keys (lists of strings), language (string). The deprecated key
#   money_paths is still accepted and written as critical_paths.
# --dry-run: print the resulting project.json and the pending steps; write nothing.
# --kit: the kit's 03-tools/, whose config/project.json is the never-adapted
#   template (default: $METODO_KIT, else this directory if it is the kit, else
#   ~/metodologia-de-trabajo/03-tools).
#
# Ends with a deterministic list of the pending human steps: what detection
# cannot decide, each with the file to fill in.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo> <audit-folder> [--critical-flow-example] [--answers <json|file>] [--dry-run] [--allow-kit] [--kit <dir>]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec python3 - "$TOOLS_ROOT" "$@" <<'PYEOF'
import argparse
import copy
import json
import os
import shutil
import sys
from pathlib import Path

tools_root = Path(sys.argv[1])
sys.path.insert(0, str(tools_root / "lib"))

parser = argparse.ArgumentParser(prog="adopt.sh")
parser.add_argument("repo")
parser.add_argument("audit_folder")
parser.add_argument("--critical-flow-example", action="store_true")
parser.add_argument("--answers", default=None)
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--allow-kit", action="store_true")
parser.add_argument("--kit", default=None)
args = parser.parse_args(sys.argv[2:])


def die(message: str) -> None:
    print(f"adopt.sh: {message}", file=sys.stderr)
    sys.exit(2)


def is_kit(root: Path) -> bool:
    return (root.parent / "01-roles").is_dir() and (root.parent / "05-adopt").is_dir()


repo = Path(args.repo).expanduser()
if not repo.is_dir():
    die(f"repo is not a directory: {args.repo}")
repo = repo.resolve()
config_dir = tools_root / "config"
config_path = config_dir / "project.json"
examples_dir = config_dir / "examples" / "critical-flow"

if is_kit(tools_root) and not (args.allow_kit or args.dry_run):
    die(f"{tools_root} is the kit itself; its config/project.json is the tracked template every instance starts from.\n"
        "  Create an instance and adapt that one instead:\n"
        f"    {tools_root}/bin/sync-instance.sh <instance>   (e.g. ~/<project>-tools)\n"
        "    <instance>/bin/adopt.sh <repo> <audit-folder>\n"
        "  or pass --allow-kit to adapt the kit's template on purpose.")

# ------------------------------------------------------------------ answers
ANSWER_LISTS = ("property_order", "critical_properties", "critical_paths", "ticket_keys")
# Renamed answer keys still accepted: deprecated name -> current name.
DEPRECATED_ANSWERS = {"money_paths": "critical_paths"}
answers: dict = {}
if args.answers is not None:
    raw = args.answers
    if not raw.lstrip().startswith("{"):
        try:
            raw = Path(raw).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            die(f"--answers: cannot read {args.answers}: {exc.strerror}")
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"--answers: not valid JSON ({exc.msg})")
    if not isinstance(answers, dict):
        die("--answers: must be a JSON object")
    for old, new in DEPRECATED_ANSWERS.items():
        if old in answers:
            value = answers.pop(old)
            answers.setdefault(new, value)
    unknown = sorted(set(answers) - set(ANSWER_LISTS) - {"language"})
    if unknown:
        die(f"--answers: unknown keys {unknown}; accepted: {sorted(ANSWER_LISTS + ('language',))}")
    for key in ANSWER_LISTS:
        value = answers.get(key)
        if key in answers and not (isinstance(value, list) and all(isinstance(v, str) and v for v in value)):
            die(f"--answers: {key} must be a list of non-empty strings")
    if "language" in answers and not (isinstance(answers["language"], str) and answers["language"]):
        die("--answers: language must be a non-empty string")

# ------------------------------------------------------------------ template
def kit_template_bytes() -> bytes | None:
    candidates = []
    if args.kit:
        candidates.append(Path(args.kit).expanduser())
    elif os.environ.get("METODO_KIT"):
        candidates.append(Path(os.environ["METODO_KIT"]).expanduser())
    elif is_kit(tools_root):
        candidates.append(tools_root)
    else:
        candidates.append(Path.home() / "metodologia-de-trabajo" / "03-tools")
    for kit in candidates:
        try:
            return (kit / "config" / "project.json").read_bytes()
        except OSError:
            pass
    return None


template_bytes = kit_template_bytes()
current_bytes = config_path.read_bytes() if config_path.exists() else None
if current_bytes is not None:
    try:
        current = json.loads(current_bytes)
    except json.JSONDecodeError as exc:
        die(f"{config_path} is not valid JSON ({exc.msg}); fix it by hand first")
    if not isinstance(current, dict):
        die(f"{config_path} must hold a JSON object")
else:
    current = {}

if current_bytes is None:
    state = "missing"
elif template_bytes is not None and current_bytes == template_bytes:
    state = "template"
else:
    state = "hand-adapted"

try:
    template = json.loads(template_bytes) if template_bytes else {}
except json.JSONDecodeError:
    template = {}
if not isinstance(template, dict):
    template = {}

# ------------------------------------------------------------------ detection
import build_files  # noqa: E402  (lib/ of this tools directory)
import detect_repo  # noqa: E402

facts = detect_repo.detect(repo)

GENERIC_ORDER = ["Correctness", "Data integrity", "Security", "Recoverability", "Auditability", "UX"]
GENERIC_CRITICAL = ["Correctness", "Data integrity", "Security"]
BUILD_FULL_GLOBS = {
    "gradle": ["**/proguard*.pro", "gradle/**", "gradlew*", *build_files.GRADLE_BUILD_GLOBS],
    "maven": ["**/pom.xml", ".mvn/**", "mvnw*"],
    "xcode": ["**/*.xcodeproj/**", "**/*.xcworkspace/**"],
}


def tests_globs() -> list[str]:
    return sorted({g for globs in facts["tests_globs"].values() for g in globs})


def block(name: str) -> dict:
    value = template.get(name)
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def generic_skeleton() -> dict:
    rdd = {"enabled": True, "review_authority": "kit", "mode": "warn", "hook_modes": {},
           "exempt_globs": ["**/*.md", "docs/**"], "low_max_changed_lines": 120}
    rdd.update(block("rdd"))
    rdd["tests_globs"] = tests_globs()
    rdd["lens_paths"] = {}
    memory = {"enabled": True, "engram_project": ""}
    memory.update(block("memory"))
    full_globs = set(facts["shared_build_files"])
    for name in facts["build_systems"]:
        full_globs.update(BUILD_FULL_GLOBS.get(name, ()))
    sectors = block("test_sectors")
    sectors.update({"base_ref": facts["base_ref"] or "", "full_required_globs": sorted(full_globs), "sectors": []})
    skeleton = {
        "_comment": ("The only file a project fills in to adapt the kit. Generated by bin/adopt.sh from "
                     "lib/detect_repo.py facts and the owner's answers; review every field by hand."),
        "property_order": list(GENERIC_ORDER),
        "critical_properties": list(GENERIC_CRITICAL),
        "critical_paths": [],
        "shared_build_files": list(facts["shared_build_files"]),
        "invariant_prefix": "INV",
        "extra_invariant_tokens": [],
        "language": facts["primary_language"] or "",
        "rdd": rdd,
        "memory": memory,
        "test_sectors": sectors,
    }
    if facts["ticket_keys"]:
        skeleton["ticket_keys"] = list(facts["ticket_keys"])
    return skeleton


def critical_flow_defaults(config: dict) -> None:
    config.setdefault("_comment", "The only file a new project has to fill in to adapt the kit.")
    config.setdefault("shared_build_files", list(build_files.GRADLE_BUILD_GLOBS))
    config.setdefault("critical_paths", ["booking/", "framework/booking/", "ui/booking/"])
    config.setdefault("property_order", [
        "Capacity", "Booking status", "Request identity", "Integrity",
        "Auditability", "Recoverability", "Security", "UX",
    ])
    config.setdefault("invariant_prefix", "INV")
    config.setdefault("extra_invariant_tokens", ["ARCH-006"])
    config.setdefault("language", "kotlin")
    config.setdefault("ticket_keys", ["DEV", "BOOK"])


filled: list[str] = []
if args.critical_flow_example:
    config = dict(current)
    critical_flow_defaults(config)
    mode = "critical-flow example (its defaults for missing keys)"
elif state in ("missing", "template"):
    config = generic_skeleton()
    mode = f"rebuilt from the generic skeleton + detection (project.json was {'missing' if state == 'missing' else 'the kit template, never adapted'})"
else:
    config = dict(current)
    skeleton = generic_skeleton()
    hand_hierarchy = "property_order" in config
    for key, value in skeleton.items():
        if key == "critical_properties" and hand_hierarchy:
            continue  # a generic critical set must not mix with a hand-written hierarchy
        if key == "critical_paths" and "money_paths" in config:
            continue  # the deprecated spelling already declares them; readers still honor it
        if key not in config:
            config[key] = value
            filled.append(key)
    mode = "preserved (adapted by hand); filled missing keys: " + (", ".join(sorted(filled)) or "none")

config["docs_root"] = args.audit_folder
for key, value in answers.items():
    config[key] = value
if "property_order" in answers and "critical_properties" not in answers:
    config["critical_properties"] = list(answers["property_order"])  # strictest until the owner narrows it
if "critical_properties" in config and "property_order" in config:
    outside = sorted(set(config["critical_properties"]) - set(config["property_order"]))
    if outside:
        die(f"critical_properties not in property_order: {outside}")

rendered = json.dumps(config, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

# ------------------------------------------------------------------ write
print("== config/project.json ==")
print(f"  {mode}")
print(f"  docs_root -> {args.audit_folder}")
if args.dry_run:
    print("  dry-run: nothing written; the result would be:")
    sys.stdout.write(rendered)
else:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rendered, encoding="utf-8")

EXAMPLE_FILES = ("dep-boundaries.json", "invariants-checks.json", "duplication-targets.json",
                 "property-hierarchy-map.json")
if args.critical_flow_example:
    print("== copying examples/critical-flow to config/ (critical-flow domain) ==")
    for name in EXAMPLE_FILES:
        src, dst = examples_dir / name, config_dir / name
        if dst.is_file() and dst.read_bytes() != src.read_bytes():
            print(f"  ~ config/{name} (overwritten with the critical-flow example: check the diff if you had already touched it)")
        else:
            print(f"  + config/{name}")
        if not args.dry_run:
            shutil.copyfile(src, dst)
else:
    print("== config/" + ", ".join(EXAMPLE_FILES) + " ==")
    print("  stay at their generic minimal placeholder (or as they already were); "
          "use --critical-flow-example to start from the critical-flow examples")

# ------------------------------------------------------------------ report
print()
print("== decided by detection (review) ==")
langs = ", ".join(f"{l['name']} ({l['files']})" for l in facts["languages"]) or "none"
print(f"  languages: {langs}")
print(f"  build system: {facts['build_system'] or 'none'}; shared_build_files: {', '.join(facts['shared_build_files']) or 'none'}")
print(f"  base_ref: {facts['base_ref'] or 'none'}")
print(f"  ticket_keys: {', '.join(facts['ticket_keys']) or 'none'}")
print(f"  rdd.tests_globs: {', '.join(tests_globs()) or 'none'}")

pending: list[str] = []
generic_hierarchy = config.get("property_order") == GENERIC_ORDER
if "property_order" not in answers:
    pending.append("confirm the property hierarchy, in tie-break order"
                   + (" (still the generic placeholder)" if generic_hierarchy else "")
                   + " -> config/project.json:property_order")
if "critical_properties" not in answers:
    if "critical_properties" in config:
        pending.append("confirm critical_properties (they require an invariant in the card and large-model adversaries)"
                       " -> config/project.json:critical_properties")
    else:
        pending.append("declare critical_properties for your hierarchy (absent: the validator falls back to its"
                       " built-in list) -> config/project.json:critical_properties")
if "critical_paths" not in answers:
    pending.append("declare the critical-flow paths (the path outranks the card) -> config/project.json:critical_paths")
if not config.get("ticket_keys"):
    pending.append("declare ticket_keys (none detected in the last 500 subjects; absent = shape-only checks)"
                   " -> config/project.json:ticket_keys")
if not config.get("language"):
    pending.append("declare the main language (none detected) -> config/project.json:language")
if not (config.get("test_sectors") or {}).get("base_ref"):
    pending.append("declare the integration branch (none detected) -> config/project.json:test_sectors.base_ref")
if not (config.get("rdd") or {}).get("lens_paths"):
    pending.append("map the review lenses to paths (flujo-critico, jamas-peor-que-antes, tests-anti-flake)"
                   " -> config/project.json:rdd.lens_paths")
if not (config.get("test_sectors") or {}).get("sectors"):
    pending.append("map paths to their test tasks (empty = every change requires the full suite)"
                   " -> config/project.json:test_sectors.sectors")
pending += [
    "write the invariants INV-01..NN with today's guarantee (test / guard / script / none), file:line@sha and gap"
    f" -> {args.audit_folder}/invariants.md",
    "declare the invariant presence checks and invariant_prefix -> config/invariants-checks.json",
    "declare the allowed and forbidden dependency edges -> config/dep-boundaries.json",
    "set the capped base documents -> config/docs-caps.json",
    "write the conventions (language base + deltas with stable IDs and a detector) -> <repo>/CONVENTIONS.md (committed)",
    f"write how the method applies here (paths, names, owner) -> {args.audit_folder}/CONTEXT-PACK.md",
    "fix the project vocabulary, one word per concept -> CONVENTIONS.md",
    "Owner: who decides and at which gates; emergency lane and who signs it off -> CONTEXT-PACK.md",
    "what an agent does when the owner is unavailable (wait, delegate, wait cap) -> CONTEXT-PACK.md",
    "custody of the tools instance: remote, copy, paths that never leave -> CONTEXT-PACK.md",
    "a real environment, one session: where who holds it is written down -> CONTEXT-PACK.md",
]
print()
print("== pending human steps (detection cannot decide these) ==")
for index, step in enumerate(pending, 1):
    print(f"  [ ] {index:2d}. {step}")

print()
print("== next commands ==")
print(f"  {tools_root}/bin/fetch-tools.sh")
print(f"  {tools_root}/bin/install.sh {repo} --runtime all --tools {tools_root}")
print(f"  python3 {tools_root}/lib/duplication_cpd.py {repo} --calibrate   (sets config/cpd.json)")
print(f"  {tools_root}/bin/metrics.sh {repo} --save   (first baseline, on a clean sha)")
print(f"  {tools_root}/bin/cartography.sh {repo}")
PYEOF
