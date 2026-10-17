#!/usr/bin/env python3
"""One command from zero to a working kit instance (kit-init S1, S3, S8, S10).

Orchestrates the kit's own CLIs over a target repo, in order, and records
every step as {step, status: done|skipped|warn|fail, detail, fix}:

   1 preflight    git repo with >= 1 commit, python3 >= 3.11, git; notes
                  missing optional tools (java, node >= 22.6, claude / pi)
   2 instance     bin/sync-instance.sh <instance>; a directory this run
                  creates gets `git init` and ONE commit
                  (`chore: kit instance from <kit sha>`); an existing one is
                  never committed in
   3 adapt        <instance>/bin/adopt.sh <repo> <audit> --kit <kit> [--answers]
   4 scaffolds    invariants.md, CONTEXT-PACK.md, CONVENTIONS.md.template in
                  the audit folder; never overwritten, never inside the repo
   5 fetch        <instance>/bin/fetch-tools.sh (unless --no-fetch); failure warns
   6 calibrate    duplication_cpd.py --calibrate when config/cpd.json is still
                  the kit's copy, PMD is fetched and targets are declared
   7 install      <kit>/bin/install.sh <repo> --runtime <r> --tools <instance>
   8 baseline     <instance>/bin/metrics.sh <repo> --save (unless --no-baseline)
   9 map          <instance>/bin/cartography.sh <repo>, best effort
  10 doctor       the kit's lib/doctor.py (the instance has no 01-roles/)
  11 smoke        the kit's lib/smoke_loop.py with the instance's config
                  (METODO_PROJECT_CONFIG) on a throwaway clone (unless --no-smoke)
  12 suggestions  lib/suggest.py over config/suggestions.json (never installs)
  13 report       <instance>/out/init/<repo_sha>.json

Every checklist item (05-adopt/checklist.md) the run cannot do is a
pending human step naming its file. Personal assets are never copied
(bin/sync-instance.sh excludes them); global configs are read only with
--read-global-config.

Usage:
    lib/init_kit.py <repo> [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all]
                    [--answers <json|file>] [--engram-project NAME] [--no-fetch] [--no-baseline]
                    [--no-smoke] [--read-global-config] [--dry-run]
    lib/init_kit.py <repo> --uninstall [--instance <dir>] [--audit <dir>] [--purge]
                    [--runtime claude|pi|all] [--dry-run]

Defaults: --instance ~/<repo_name>-tools, --audit ~/<repo_name>-audit,
--runtime all; repo_name comes from lib/detect_repo.py.

The report has sorted keys, no timestamps and no absolute paths (<repo>,
<instance>, <audit>, <kit>, ~/...) and describes the resulting STATE, not
the actions taken, so a second run over an unchanged repo writes it byte
for byte the same. Actions (created, kept, updated) go to stderr only.
Stdout carries the report (or, with --dry-run, the plan).

Exit: 0 when the doctor has no FAIL and the smoke (if run) passed; 1
otherwise; 2 usage or preflight (nothing written).

A run that creates the instance also writes <instance>/out/init/manifest.json
(git-ignored): the instance HEAD, the sha256 of every uncommitted file it
leaves (the adapted config) and of the audit scaffolds it wrote. --purge
reads it to tell init's own changes from the owner's.

--uninstall (kit-init S13) unplugs the kit from the repo and keeps the
instance and the audit folder:
   1 uninstall  <kit>/bin/install.sh <repo> --uninstall --runtime <r> --tools <instance>
                (removes only what is byte-identical to the kit's render)
   2 doctor     <kit>/lib/doctor.py <repo> --absent --runtime <r> (kit_absent)
   3 purge      only with --purge: deletes the instance when the repo ended
                kit_absent and the instance is its own git repo with init's
                single commit and no uncommitted change other than the ones the
                manifest records; deletes the audit folder
                when every file in it is an init scaffold, byte-identical to
                what init writes. Otherwise refuses and lists why.
   4 report     <instance>/out/uninstall/<repo_sha>.json (stdout only when the
                instance is gone): {removed, kept_modified, kept_in_use,
                not_found, kit_absent, instance, audit, doctor, steps, ...}
--dry-run prints the plan, the purge verdicts and what is still installed;
it writes nothing. Exit 0 when kit_absent (and a requested purge was not
refused), 1 when something kit-owned remains, 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT_TOOLS = Path(__file__).resolve().parent.parent
KIT_ROOT = KIT_TOOLS.parent
sys.path.insert(0, str(KIT_TOOLS))

from lib import baseline, detect_repo, suggest  # noqa: E402

SCHEMA_VERSION = "1.0.0"
RUNTIMES = ("claude", "pi", "all")
STEPS = ("preflight", "instance", "adapt", "scaffolds", "fetch", "calibrate", "install", "baseline", "map",
         "doctor", "smoke", "suggestions")
SECTIONS = {1: "1. Declare", 2: "2. Write", 3: "3. Tools", 4: "4. People and gates", 5: "5. Start"}
MIN_PYTHON = (3, 11)
CHILD_ENV_DROP = ("METODO_PROJECT_CONFIG", "METODO_TOOLS")
PLACEHOLDERS = {
    "<repo>": "the target repo",
    "<instance>": "the tools instance (--instance)",
    "<audit>": "the project's audit folder (--audit)",
    "<kit>": "the kit's 03-tools",
    "~": "the user's home",
}
PENDING_RE = re.compile(r"^\s+\[ \]\s+\d+\.\s+(.*)$")
TIMEOUTS = {"fetch": 1800, "smoke": 1800, "default": 900}
SCAFFOLDS = ("invariants.md", "CONTEXT-PACK.md", "CONVENTIONS.md.template")
MANIFEST = Path("out") / "init" / "manifest.json"
INIT_COMMIT_PREFIX = "chore: kit instance from "
ITEM_RE = re.compile(r"^  ([-!.=]) (\S+) \((removed|not found|kept: [^)]+)\)$")

# What adopt.sh prints when it runs; used only if it could not run, so a
# failed adapt still leaves nothing out.
FALLBACK_PENDING = (
    ("confirm the property hierarchy, in tie-break order", "<instance>/config/project.json:property_order"),
    ("confirm critical_properties (they require an invariant in the card and large-model adversaries)",
     "<instance>/config/project.json:critical_properties"),
    ("declare the critical-flow paths (the path outranks the card)", "<instance>/config/project.json:critical_paths"),
    ("write the invariants INV-01..NN with today's guarantee (test / guard / script / none), file:line@sha and gap",
     "<audit>/invariants.md"),
    ("declare the invariant presence checks and invariant_prefix", "<instance>/config/invariants-checks.json"),
    ("declare the allowed and forbidden dependency edges", "<instance>/config/dep-boundaries.json"),
    ("set the capped base documents", "<instance>/config/docs-caps.json"),
    ("write the conventions (language base + deltas with stable IDs and a detector)", "<repo>/CONVENTIONS.md (committed)"),
    ("write how the method applies here (paths, names, owner)", "<audit>/CONTEXT-PACK.md"),
    ("fix the project vocabulary, one word per concept", "<repo>/CONVENTIONS.md"),
    ("Owner: who decides and at which gates; emergency lane and who signs it off", "<audit>/CONTEXT-PACK.md"),
    ("what an agent does when the owner is unavailable (wait, delegate, wait cap)", "<audit>/CONTEXT-PACK.md"),
    ("custody of the tools instance: remote, copy, paths that never leave", "<audit>/CONTEXT-PACK.md"),
    ("a real environment, one session: where who holds it is written down", "<audit>/CONTEXT-PACK.md"),
)
START_PENDING = (
    ("write the first change card and validate it by script (python3 <instance>/lib/change_card_validator.py "
     "<card>); work in the lane the validator returns", "<instance>/config/change-card.template.md"),
    ("run the first round of two adversaries with facts from scripts; write the minutes with the template",
     "<kit>/../04-templates/round-minutes.md"),
    ("first benchmark: last shipped tag against the candidate; fill not_measured with how to get it",
     "<instance>/bin/benchmark-release.sh"),
    ("owner's review of the rule -> property map, row by row (every row is born Assumed)",
     "<instance>/config/property-hierarchy-map.json"),
)


class UsageError(Exception):
    pass


# ----------------------------------------------------------------------------- paths and placeholders

class Paths:
    def __init__(self, repo: Path, instance: Path, audit: Path, audit_arg: str, home: Path):
        self.repo, self.instance, self.audit, self.audit_arg, self.home = repo, instance, audit, audit_arg, home
        pairs: list[tuple[str, str]] = []
        for path, label in ((repo, "<repo>"), (instance, "<instance>"), (audit, "<audit>"), (KIT_TOOLS, "<kit>"),
                            (KIT_ROOT, "<kit>/..")):
            for form in {str(path), os.path.realpath(path), os.path.abspath(path)}:
                pairs.append((form.rstrip(os.sep), label))
        if audit_arg.startswith("~/"):
            pairs.append((audit_arg.rstrip("/"), "<audit>"))
        for form in {str(home), os.path.realpath(home)}:
            pairs.append((form.rstrip(os.sep), "~"))
        self.pairs = sorted({p for p in pairs if p[0]}, key=lambda p: len(p[0]), reverse=True)

    def show(self, text: str) -> str:
        for absolute, label in self.pairs:
            text = re.sub(re.escape(absolute) + r"(?![\w-])", lambda _m, l=label: l, text)
        return text

    def sanitize(self, obj):
        if isinstance(obj, str):
            return self.show(obj)
        if isinstance(obj, list):
            return [self.sanitize(v) for v in obj]
        if isinstance(obj, dict):
            return {self.show(k): self.sanitize(v) for k, v in obj.items()}
        return obj


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _inside(path: Path, root: Path) -> bool:
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _tilde(path: Path, home: Path) -> str:
    for base in (str(home), os.path.realpath(home)):
        if str(path).startswith(base.rstrip(os.sep) + os.sep):
            return "~/" + os.path.relpath(str(path), base)
    return str(path)


# ----------------------------------------------------------------------------- processes

def child_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}
    env["METODO_KIT"] = str(KIT_TOOLS)
    env.update(extra or {})
    return env


class Proc:
    def __init__(self, code: int, out: str, err: str):
        self.code, self.out, self.err = code, out, err

    def last_line(self) -> str:
        for text in (self.err, self.out):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                return lines[-1][:240]
        return f"exit {self.code}"


def run(argv: list[str], timeout: int | None = None, cwd: Path | None = None, env: dict | None = None) -> Proc:
    try:
        proc = subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=child_env(env),
                              timeout=timeout or TIMEOUTS["default"], cwd=str(cwd) if cwd else None,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Proc(124, "", f"timed out after {timeout or TIMEOUTS['default']}s")
    except OSError as exc:
        return Proc(127, "", f"could not run {argv[0]}: {exc.strerror}")
    return Proc(proc.returncode, proc.stdout or "", proc.stderr or "")


def _git(cwd: Path, *args: str) -> Proc:
    return run(["git", "-C", str(cwd), *args])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def porcelain_paths(root: Path) -> list[str]:
    """Paths `git status` reports in root (untracked files one by one, ignored ones never)."""
    proc = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if proc.code != 0:
        return []
    fields, paths, skip = proc.out.split("\0"), [], False
    for field in fields:
        if skip:
            skip = False
            continue
        if len(field) < 4:
            continue
        if field[0] in "RC":
            skip = True  # the next field is the rename source
        paths.append(field[3:])
    return sorted(set(paths))


def say(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def echo_changes(proc: Proc) -> None:
    """Installers and the sync print `  + ` (new) and `  ~ ` (updated); `  = ` is unchanged."""
    for line in (proc.out + proc.err).splitlines():
        if line.startswith(("  + ", "  ~ ")):
            say(line)


# ----------------------------------------------------------------------------- scaffolds

def invariants_template(prefix: str) -> str:
    return "\n".join([
        "# Invariants",
        "",
        "Scaffold written by bin/init.sh; fill it in by hand (05-adopt/checklist.md, section 2). One row per",
        "invariant: what must always hold, today's guarantee, and the gap. Whatever has no guarantee is a finding,",
        "not philosophy.",
        "",
        "- Guarantee mechanism: test / guard / script / none.",
        "- Evidence: `file:line@sha` of the test, guard or script that holds it today (empty when none).",
        "- Tag: [Measured] / [Tested] / [Inferred] / [Assumed].",
        "- Gap: what breaks it today, or none.",
        "",
        "| ID | Invariant | Guarantee mechanism | Evidence (file:line@sha) | Tag | Gap |",
        "|---|---|---|---|---|---|",
        f"| {prefix}-01 |  |  |  |  |  |",
        f"| {prefix}-02 |  |  |  |  |  |",
        f"| {prefix}-NN |  |  |  |  |  |",
        "",
    ])


def context_pack_template(kit_tools: Path) -> str:
    source = kit_tools.parent / "CONTEXT-PACK.md"
    text = source.read_text(encoding="utf-8") if source.is_file() else "# Context pack\n"
    return text.rstrip("\n") + "\n" + "\n".join([
        "",
        "## How this applies here",
        "",
        "<!-- Written by bin/init.sh: fill in one short paragraph per line, then delete this comment. -->",
        "",
        "- Paths: where the critical flow lives, and what is off-limits to agents.",
        "- Names: the project's word for each concept (device, server, vendor...).",
        "- Owner: who decides, and at which gates; the emergency lane and who signs it off.",
        "- Owner unavailable: what an agent does (wait, delegate, wait cap).",
        "- Custody of the tools instance: remote, copy, which paths can never leave.",
        "- Real environment: who holds it, and where that is written down.",
        "",
    ])


def conventions_template(kit_tools: Path, language: str | None) -> str:
    digest = kit_tools.parent / "06-languages" / f"{language}.md" if language else None
    if digest is not None and digest.is_file():
        base = (f"Base: the kit's digest 06-languages/{language}.md (the official guide for {language}, its verbatim "
                "rules and the typical house rules). It is not restated here.")
    elif language:
        base = (f"Base: the kit has no 06-languages/{language}.md digest; start from the language's official style "
                "guide, and read any digest under 06-languages/ for the expected shape.")
    else:
        base = ("Base: no main language was detected; start from the language's official style guide, and read any "
                "digest under 06-languages/ for the expected shape.")
    return "\n".join([
        "# CONVENTIONS.md · template",
        "",
        "Written by bin/init.sh in the audit folder. Copy it to the target repo as CONVENTIONS.md, fill it in and",
        "commit it there: the committed file is what agents and reviewers read (00-principles/methodology.md,",
        "section 5).",
        "",
        base,
        "",
        "Write only the deltas: what this project does differently from the base, or adds to it. Each rule gets a",
        "stable ID that is never reused or renumbered (CONV-01, CONV-02, ...; a retired rule keeps its ID with",
        "status silenced), a declared detector (compiler, lint, guard test, script, human review) and a status",
        "(active, silenced, proposed).",
        "",
        "| ID | Rule | Why | Detector | Status |",
        "|---|---|---|---|---|",
        "| CONV-01 |  |  |  | proposed |",
        "",
        "## Vocabulary",
        "",
        "One word per concept (what the device is called, the server, the vendor...).",
        "",
        "| Concept | The word we use | Words we do not use |",
        "|---|---|---|",
        "|  |  |  |",
        "",
    ])


def write_scaffolds(audit: Path, kit_tools: Path, language: str | None, prefix: str) -> list[str]:
    """Writes the audit-folder scaffolds that do not exist yet; never
    overwrites. Returns the names written, in a fixed order."""
    written = []
    for name, render in (("invariants.md", lambda: invariants_template(prefix)),
                         ("CONTEXT-PACK.md", lambda: context_pack_template(kit_tools)),
                         ("CONVENTIONS.md.template", lambda: conventions_template(kit_tools, language))):
        target = audit / name
        if target.exists() or target.is_symlink():
            continue
        audit.mkdir(parents=True, exist_ok=True)
        with open(target, "x", encoding="utf-8") as fh:
            fh.write(render())
        written.append(name)
    return written


# ----------------------------------------------------------------------------- the run

class Init:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.steps: list[dict] = []
        self.pending: list[tuple[int, str, str]] = []
        self.adapt_pending: list[tuple[str, str]] = []
        self.answers_path: str | None = None
        self.preflight_warns: list[str] = []
        self.preflight_fixes: list[str] = []

    # -- bookkeeping

    def record(self, step: str, status: str, detail: str, fix: str | None = None) -> dict:
        entry = {"step": step, "status": status, "detail": detail, "fix": fix}
        self.steps.append(entry)
        say(f"  {status:<7} {step}: {self.paths.show(detail) if hasattr(self, 'paths') else detail}")
        return entry

    def todo(self, section: int, step: str, file: str) -> None:
        self.pending.append((section, step, file))

    # -- 1 preflight (read-only)

    def preflight(self) -> None:
        args = self.args
        if shutil.which("git") is None:
            raise UsageError("git is not on PATH")
        if sys.version_info < MIN_PYTHON:
            raise UsageError(f"python3 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required, found {sys.version.split()[0]}")
        if not ((KIT_ROOT / "01-roles").is_dir() and (KIT_ROOT / "02-skills").is_dir()):
            raise UsageError(f"{KIT_TOOLS} is not the kit's 03-tools: run bin/init.sh from the kit")
        target = Path(args.repo).expanduser()
        if not target.is_dir():
            raise UsageError(f"not a directory: {args.repo}")
        top = _git(target, "rev-parse", "--show-toplevel")
        if top.code != 0 or not top.out.strip():
            raise UsageError(f"not a git repository: {args.repo}")
        repo = Path(top.out.strip()).resolve()
        if _inside(repo, KIT_ROOT) or _inside(KIT_ROOT, repo):
            raise UsageError(f"{args.repo} is the kit (or holds it): init adapts and installs into a target repo, "
                             "never into the kit checkout")
        head = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        if head.code != 0:
            raise UsageError(f"the repository has no commits: {args.repo} (commit once, then rerun)")
        self.repo = repo
        self.repo_sha = head.out.strip()
        self.facts = detect_repo.detect(repo)
        home = _home()
        name = self.facts["repo_name"]
        instance = Path(os.path.abspath(Path(args.instance).expanduser() if args.instance else home / f"{name}-tools"))
        audit = Path(os.path.abspath(Path(args.audit).expanduser() if args.audit else home / f"{name}-audit"))
        for label, path in (("--instance", instance), ("--audit", audit)):
            if _inside(path, repo):
                raise UsageError(f"{label} {path} is inside the target repo: the kit never writes its instance or the "
                                 "audit folder into the repo")
            if _inside(path, KIT_ROOT) or _inside(KIT_TOOLS, path):
                raise UsageError(f"{label} {path} is inside the kit (or holds it): pick a directory outside the kit")
        if _inside(audit, instance) or _inside(instance, audit):
            raise UsageError("--instance and --audit must be two separate directories")
        if instance.exists() and not instance.is_dir():
            raise UsageError(f"--instance {instance} exists and is not a directory")
        if args.answers is not None:
            raw = args.answers
            if not raw.lstrip().startswith("{"):
                answers_file = Path(raw).expanduser()
                try:
                    raw = answers_file.read_text(encoding="utf-8")
                except OSError as exc:
                    raise UsageError(f"--answers: cannot read {args.answers}: {exc.strerror}")
                self.answers_path = str(answers_file.resolve())
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise UsageError(f"--answers: not valid JSON ({exc.msg})")
            if not isinstance(parsed, dict):
                raise UsageError("--answers: must be a JSON object")
            self.answers = parsed
        else:
            self.answers = {}
        self.audit_arg = _tilde(audit, home)
        self.paths = Paths(repo, instance, audit, self.audit_arg, home)
        self.instance, self.audit = instance, audit

        # optional tools: warn, never fail
        runtimes = ("claude", "pi") if args.runtime == "all" else (args.runtime,)
        entries = [e for e in suggest.load_entries() if e["id"] in ("java", "node")]
        for entry in suggest.suggest(repo, None, args.runtime, False, entries=entries):
            if entry["status"] != "present":
                reason = entry["why"].split("Detected: ", 1)[-1]
                purpose = "vendored jars" if entry["id"] == "java" else "pi extension, node >= 22.6"
                self.preflight_warns.append(f"{entry['id']} ({purpose}): {reason}")
                if entry["command"]:
                    self.preflight_fixes.append(entry["command"])
        for runtime in runtimes:
            if shutil.which(runtime) is None:
                self.preflight_warns.append(f"{runtime} is not on PATH (runtime {runtime})")
                self.preflight_fixes.append(f"install the {runtime} CLI, or pass --runtime "
                                            f"{'pi' if runtime == 'claude' else 'claude'}")

    def plan(self) -> list[tuple[str, str]]:
        a, inst, kit, repo = self.args, self.instance, KIT_TOOLS, self.repo
        answers = f" --answers {a.answers!r}" if a.answers is not None else ""
        engram = f" --engram-project {a.engram_project}" if a.engram_project else ""
        out = lambda kind: inst / "out" / kind / f"{self.repo_sha}.json"  # noqa: E731
        return [
            ("preflight", f"{repo} is a git repo at {self.repo_sha[:12]}; python3, git checked"),
            ("instance", f"bash {kit}/bin/sync-instance.sh {inst}"
                         + ("" if inst.exists() else f" (new: git init + one commit 'chore: kit instance from <kit sha>')")),
            ("adapt", f"bash {inst}/bin/adopt.sh {repo} {self.audit_arg} --kit {kit}{answers}"),
            ("scaffolds", f"invariants.md, CONTEXT-PACK.md, CONVENTIONS.md.template in {self.audit} (only missing ones)"),
            ("fetch", "skipped (--no-fetch)" if a.no_fetch else f"bash {inst}/bin/fetch-tools.sh"),
            ("calibrate", f"python3 {inst}/lib/duplication_cpd.py {repo} --calibrate (only if config/cpd.json is the "
                          "kit's copy, PMD is fetched and targets are declared)"),
            ("install", f"bash {kit}/bin/install.sh {repo} --runtime {a.runtime} --tools {inst}{engram}"),
            ("baseline", "skipped (--no-baseline)" if a.no_baseline else f"bash {inst}/bin/metrics.sh {repo} --save"),
            ("map", f"bash {inst}/bin/cartography.sh {repo} (best effort)"),
            ("doctor", f"python3 {kit}/lib/doctor.py {repo} --tools {inst} --runtime {a.runtime} --out {out('doctor')}"),
            ("smoke", "skipped (--no-smoke)" if a.no_smoke else
                      f"METODO_PROJECT_CONFIG={inst}/config/project.json python3 {kit}/lib/smoke_loop.py {repo} "
                      f"--tools {kit} --out {out('smoke')}"),
            ("suggestions", f"python3 {kit}/lib/suggest.py {repo} --tools {inst} --runtime {a.runtime}"
                            + (" --read-global-config" if a.read_global_config else "")),
            ("report", f"{out('init')}"),
        ]

    # -- 2 instance

    def step_instance(self) -> bool:
        inst = self.instance
        created = not inst.exists()
        self.instance_created = False
        if created:
            inst.mkdir(parents=True)
        proc = run(["bash", KIT_TOOLS / "bin" / "sync-instance.sh", inst])
        echo_changes(proc)
        if proc.code != 0:
            self.record("instance", "fail", f"bin/sync-instance.sh failed: {proc.last_line()}",
                        "<kit>/bin/sync-instance.sh <instance>")
            return False
        if created and not (inst / ".git").exists():
            gitignore = KIT_TOOLS / ".gitignore"
            if gitignore.is_file() and not (inst / ".gitignore").exists():
                shutil.copyfile(gitignore, inst / ".gitignore")
            kit_head = _git(KIT_ROOT, "rev-parse", "--short=12", "HEAD")
            kit_sha = kit_head.out.strip() if kit_head.code == 0 and kit_head.out.strip() else "unknown"
            identity = [] if _git(inst, "config", "user.email").code == 0 else [
                "-c", "user.name=metodo-init", "-c", "user.email=init@metodo.invalid"]
            for argv in (["init", "-q"], ["add", "-A"],
                         [*identity, "commit", "-q", "--no-verify", "-m", f"chore: kit instance from {kit_sha}"]):
                step = _git(inst, *argv)
                if step.code != 0:
                    self.record("instance", "fail", f"git {argv[-1] if argv[0] != 'init' else 'init'} in the new "
                                f"instance failed: {step.last_line()}", "git -C <instance> status")
                    return False
            self.instance_created = True
            say(f"  + new instance at {inst}, one commit: chore: kit instance from {kit_sha}")
        else:
            say(f"  = existing instance at {inst} (refreshed; never committed in)")
        self.instance_is_git = _git(inst, "rev-parse", "--verify", "--quiet", "HEAD").code == 0
        if self.instance_is_git:
            self.record("instance", "done", "synced from <kit>; git repository with a HEAD (tool_sha is set); "
                        "personal assets are never synced")
        else:
            fix = "git -C <instance> init && git -C <instance> add -A && git -C <instance> commit -m 'kit instance'"
            self.record("instance", "warn", "synced from <kit>; not a git repository, so tool_sha is null and "
                        "baselines cannot be saved", fix)
            self.todo(3, f"make the tools instance a git repository and commit it: {fix}", "<instance>/.git")
        return True

    # -- 3 adapt

    def step_adapt(self) -> None:
        self.audit.mkdir(parents=True, exist_ok=True)
        argv = ["bash", self.instance / "bin" / "adopt.sh", self.repo, self.audit_arg, "--kit", KIT_TOOLS]
        if self.args.answers is not None:
            argv += ["--answers", self.answers_path or self.args.answers]
        proc = run(argv)
        if proc.code != 0:
            self.record("adapt", "fail", f"adopt.sh failed: {proc.last_line()}",
                        "<instance>/bin/adopt.sh <repo> <audit> --kit <kit>")
            return
        for line in proc.out.splitlines():
            match = PENDING_RE.match(line)
            if match:
                text, _, file = match.group(1).rpartition(" -> ")
                self.adapt_pending.append((text or match.group(1), file))
        source = "detection and --answers" if self.answers else "detection"
        self.record("adapt", "done", f"<instance>/config/project.json adapted to <repo> from {source}; "
                    f"docs_root {self.audit_arg}; {len(self.adapt_pending)} decisions left to the owner")

    # -- 4 scaffolds

    def step_scaffolds(self) -> None:
        config = self.instance_config()
        prefix = str(config.get("invariant_prefix") or "INV")
        language = self.facts["primary_language"]
        try:
            written = write_scaffolds(self.audit, KIT_TOOLS, language, prefix)
            self.scaffolds_written = written
        except OSError as exc:
            self.record("scaffolds", "fail", f"could not write in <audit>: {exc.strerror}", "<audit>")
            return
        for name in ("invariants.md", "CONTEXT-PACK.md", "CONVENTIONS.md.template"):
            say(f"  {'+' if name in written else '='} {self.audit / name}")
        digest = f"06-languages/{language}.md" if language and (KIT_ROOT / "06-languages" / f"{language}.md").is_file() \
            else "no language digest"
        self.record("scaffolds", "done", "invariants.md, CONTEXT-PACK.md and CONVENTIONS.md.template present in "
                    f"<audit> (never overwritten; CONVENTIONS template points to {digest})")

    def instance_config(self) -> dict:
        try:
            data = baseline.load_json(self.instance / "config" / "project.json")
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    # -- 5 fetch

    def vendor_state(self) -> tuple[bool, str]:
        try:
            lock = baseline.load_json(self.instance / "config" / "tools.lock.json")
        except (OSError, ValueError):
            return False, "config/tools.lock.json missing"
        problems = []
        for name in sorted(lock if isinstance(lock, dict) else {}):
            entry = lock[name] if isinstance(lock[name], dict) else {}
            if entry.get("status") == "unavailable":
                problems.append(f"{name} unavailable")
            elif not entry.get("path") or not (self.instance / str(entry["path"])).exists():
                problems.append(f"{name} not fetched")
        if problems or not lock:
            return False, ", ".join(problems) or "no pinned tools in the lock"
        return True, "pinned tools present: " + ", ".join(sorted(lock))

    def step_fetch(self) -> None:
        fix = "<instance>/bin/fetch-tools.sh"
        if self.args.no_fetch:
            ok, state = self.vendor_state()
            self.record("fetch", "skipped", f"--no-fetch; {state}", None if ok else fix)
        else:
            proc = run(["bash", self.instance / "bin" / "fetch-tools.sh"], timeout=TIMEOUTS["fetch"])
            ok, state = self.vendor_state()
            if proc.code == 0 and ok:
                self.record("fetch", "done", state)
            else:
                why = state if proc.code == 0 else f"fetch-tools.sh exit {proc.code}: {proc.last_line()}; {state}"
                self.record("fetch", "warn", why, fix)
        if not ok:
            self.todo(3, f"fetch the pinned jars (detekt, PMD, ktlint; needs network and java): {fix}",
                      "<instance>/config/tools.lock.json")

    # -- 6 calibrate

    def step_calibrate(self) -> None:
        cpd = self.instance / "config" / "cpd.json"
        kit_cpd = KIT_TOOLS / "config" / "cpd.json"
        command = "python3 <instance>/lib/duplication_cpd.py <repo> --calibrate"
        calibrated = cpd.is_file() and (not kit_cpd.is_file() or cpd.read_bytes() != kit_cpd.read_bytes())
        if not calibrated:
            try:
                targets = list(baseline.load_json(self.instance / "config" / "duplication-targets.json").get("targets") or [])
            except (OSError, ValueError, AttributeError):
                targets = []
            pmd = sorted((self.instance / "vendor").glob("pmd-bin-*/bin/pmd"))
            vendor_ok, _ = self.vendor_state()
            reasons = []
            if not (pmd and vendor_ok):
                reasons.append("PMD is not fetched")
            if not targets:
                reasons.append("no candidate files in config/duplication-targets.json")
            if reasons:
                self.record("calibrate", "skipped", "config/cpd.json is still the kit's uncalibrated copy: "
                            + "; ".join(reasons), command)
                self.todo(3, "calibrate the duplication threshold once: list 2-4 candidate files in "
                          f"duplication-targets.json, fetch PMD, then run {command} (fixes config/cpd.json)",
                          "<instance>/config/duplication-targets.json")
                return
            proc = run([sys.executable, self.instance / "lib" / "duplication_cpd.py", self.repo, "--calibrate"])
            if proc.code != 0:
                self.record("calibrate", "warn", f"duplication_cpd.py --calibrate failed: {proc.last_line()}", command)
                self.todo(3, f"calibrate the duplication threshold once: {command}", "<instance>/config/cpd.json")
                return
        try:
            min_tokens = baseline.load_json(cpd).get("min_tokens")
        except (OSError, ValueError, AttributeError):
            min_tokens = None
        self.record("calibrate", "done", f"config/cpd.json calibrated (min_tokens {min_tokens}); recalibrating is a "
                    "change with its own change card")

    # -- 7 install

    def step_install(self) -> None:
        argv = ["bash", KIT_TOOLS / "bin" / "install.sh", self.repo, "--runtime", self.args.runtime,
                "--tools", self.instance]
        if self.args.engram_project:
            argv += ["--engram-project", self.args.engram_project]
        proc = run(argv)
        echo_changes(proc)
        fix = f"<kit>/bin/install.sh <repo> --runtime {self.args.runtime} --tools <instance>"
        if proc.code != 0:
            self.record("install", "fail", f"install.sh failed: {proc.last_line()}", fix)
            return
        self.record("install", "done", f"kit installed in <repo> for runtime {self.args.runtime} with tools "
                    "<instance> (local files only: .claude/, .pi/, .mcp.json, .git/info/exclude)")
        if self.args.runtime in ("pi", "all"):
            self.todo(3, "trust the project in pi once (/trust, or --approve for one run) so it loads the guards "
                      "extension", "<repo>/.pi/extensions/metodo-hooks.ts")

    # -- 8 baseline

    def step_baseline(self) -> None:
        command = "<instance>/bin/metrics.sh <repo> --save"
        saved = (self.instance / "baselines" / f"{self.repo_sha}.json").is_file()
        done_detail = "baseline for the repo HEAD saved under <instance>/baselines/ (latest points at a saved one)"
        pending = ("save the first baseline on a clean tree (commit or stash first): " + command,
                   "<instance>/baselines/latest")
        if saved:
            self.record("baseline", "done", done_detail)
            return
        if self.args.no_baseline:
            self.record("baseline", "skipped", "--no-baseline", command)
            self.todo(3, *pending)
            return
        if not any((self.repo / name).is_file() for name in ("settings.gradle", "settings.gradle.kts")):
            self.record("baseline", "warn", "no settings.gradle(.kts) in the repo: metrics.sh measures Gradle/Kotlin "
                        "modules only today; nothing saved", command)
            self.todo(3, "no baseline for this repo yet: metrics.sh needs a settings.gradle(.kts) (its shape metrics "
                      "are Gradle/Kotlin-only); re-run " + command + " once the repo has one or the kit ships "
                      "language-agnostic metrics", "<instance>/baselines/latest")
            return
        if baseline.is_repo_dirty(self.repo):
            self.record("baseline", "warn", "the repo has uncommitted changes: a dirty tree is not a reference point; "
                        "nothing saved", command)
            self.todo(3, *pending)
            return
        if not getattr(self, "instance_is_git", False):
            self.record("baseline", "warn", "the instance is not a git repository (tool_sha null): nothing saved", command)
            self.todo(3, *pending)
            return
        proc = run(["bash", self.instance / "bin" / "metrics.sh", self.repo, "--save"])
        if proc.code != 0 or not (self.instance / "baselines" / f"{self.repo_sha}.json").is_file():
            self.record("baseline", "warn", f"metrics.sh --save failed: {proc.last_line()}", command)
            self.todo(3, *pending)
            return
        self.record("baseline", "done", done_detail)

    # -- 9 map

    def step_map(self) -> None:
        command = "<instance>/bin/cartography.sh <repo>"
        proc = run(["bash", self.instance / "bin" / "cartography.sh", self.repo])
        if proc.code != 0:
            self.record("map", "warn", f"cartography.sh failed (it is Gradle-oriented): {proc.last_line()}", command)
            self.todo(3, f"draw the first map by hand or fix what blocks it: {command}",
                      "<instance>/config/dep-boundaries.json")
            return
        self.record("map", "done", f"first map at <instance>/out/{self.repo_sha}/cartography.md; review by hand the "
                    "boundary config it proposes")

    # -- 10 doctor

    def step_doctor(self) -> dict:
        out = self.instance / "out" / "doctor" / f"{self.repo_sha}.json"
        proc = run([sys.executable, KIT_TOOLS / "lib" / "doctor.py", self.repo, "--tools", self.instance,
                    "--runtime", self.args.runtime, "--out", out])
        try:
            report = json.loads(proc.out)
        except json.JSONDecodeError:
            report = None
        if not isinstance(report, dict):
            self.record("doctor", "fail", f"doctor.py did not report: {proc.last_line()}",
                        "python3 <kit>/lib/doctor.py <repo> --tools <instance> --table")
            return {"verdict": "FAIL", "kit_installed": False, "report": None}
        summary = report.get("summary") or {}
        failed = [c for c in report.get("checks", []) if c.get("status") == "FAIL"]
        detail = (f"verdict {report.get('verdict')}, kit_installed {str(bool(report.get('kit_installed'))).lower()} "
                  f"(PASS {summary.get('PASS', 0)}, WARN {summary.get('WARN', 0)}, FAIL {summary.get('FAIL', 0)}, "
                  f"SKIP {summary.get('SKIP', 0)})")
        if failed:
            detail += "; FAIL: " + ", ".join(c["id"] for c in failed)
        fix = "; ".join(f"{c['id']}: {c['fix']}" for c in failed if c.get("fix")) or None
        self.record("doctor", "done" if report.get("verdict") == "PASS" else "fail", detail, fix)
        return {"verdict": report.get("verdict"), "kit_installed": bool(report.get("kit_installed")),
                "report": f"<instance>/out/doctor/{self.repo_sha}.json"}

    # -- 11 smoke

    def step_smoke(self) -> dict:
        # The kit's code with the instance's config: smoke_loop.py looks for the role
        # contract under <tools>/../01-roles/, which only the kit has (an instance and
        # the throwaway clone do not carry it). The instance's lib/ is a byte copy.
        command = "METODO_PROJECT_CONFIG=<instance>/config/project.json python3 <kit>/lib/smoke_loop.py <repo>"
        if self.args.no_smoke:
            self.record("smoke", "skipped", "--no-smoke: the loop was not proven", command)
            return {"verdict": "SKIPPED", "loop_ran": False, "report": None}
        out = self.instance / "out" / "smoke" / f"{self.repo_sha}.json"
        proc = run([sys.executable, KIT_TOOLS / "lib" / "smoke_loop.py", self.repo, "--tools", KIT_TOOLS,
                    "--out", out], timeout=TIMEOUTS["smoke"],
                   env={"METODO_PROJECT_CONFIG": str(self.instance / "config" / "project.json")})
        try:
            report = json.loads(proc.out)
        except json.JSONDecodeError:
            report = None
        if not isinstance(report, dict):
            self.record("smoke", "fail", f"smoke_loop.py did not report: {proc.last_line()}", command)
            return {"verdict": "FAIL", "loop_ran": False, "report": None}
        scenarios = ", ".join(f"{s.get('name')} {s.get('verdict')}{'' if s.get('pass') else ' (unexpected)'}"
                              for s in report.get("scenarios") or []) or "no scenario ran"
        detail = ("kit code, instance config; "
                  f"verdict {report.get('verdict')}, loop_ran {str(bool(report.get('loop_ran'))).lower()}, "
                  f"user_repo_untouched {str(bool(report.get('user_repo_untouched'))).lower()}; {scenarios}")
        self.record("smoke", "done" if report.get("verdict") == "PASS" else "fail", detail,
                    None if report.get("verdict") == "PASS" else command + " --keep")
        return {"verdict": report.get("verdict"), "loop_ran": bool(report.get("loop_ran")),
                "report": f"<instance>/out/smoke/{self.repo_sha}.json"}

    # -- 12 suggestions

    def step_suggestions(self) -> list[dict]:
        found = suggest.suggest(self.repo, self.instance, self.args.runtime, self.args.read_global_config)
        for entry in found:
            for key in ("why", "command"):
                if isinstance(entry[key], str):
                    entry[key] = entry[key].replace("<tools>", "<instance>")
        counts = {s: sum(1 for e in found if e["status"] == s) for s in ("present", "missing", "unknown")}
        self.record("suggestions", "done", f"{counts['present']} present, {counts['missing']} missing, "
                    f"{counts['unknown']} unknown (nothing installed; global configs "
                    f"{'read for one key' if self.args.read_global_config else 'not read'})")
        return found

    # -- pending steps

    def pending_steps(self) -> list[dict]:
        items: list[tuple[int, str, str]] = []
        source = self.adapt_pending or list(FALLBACK_PENDING)
        for text, file in source:
            if "CONVENTIONS.md (committed)" in file:
                text += "; start from <audit>/CONVENTIONS.md.template"
            items.append((self.section_for(text, file), text, self.file_for(file)))
        items += self.pending
        items += [(5, text, file) for text, file in START_PENDING]
        if getattr(self, "instance_is_git", False):
            status = _git(self.instance, "status", "--porcelain")
            changed = sorted({l[3:].strip() for l in status.out.splitlines() if l.strip()})
            if changed:
                shown = ", ".join(f"<instance>/{c}" for c in changed[:5]) + (", ..." if len(changed) > 5 else "")
                items.append((3, "review the instance's uncommitted changes (the adapted config) and commit them "
                              "yourself: git -C <instance> diff", shown))
        seen, result = set(), []
        for section, text, file in sorted(items, key=lambda i: i[0]):
            key = (text, file)
            if key in seen:
                continue
            seen.add(key)
            result.append({"section": SECTIONS[section], "step": text, "file": file})
        return result

    @staticmethod
    def section_for(text: str, file: str) -> int:
        lowered = text.lower()
        if any(k in lowered for k in ("owner:", "owner is unavailable", "custody", "real environment")):
            return 4
        if "vocabulary" in lowered:
            return 1
        if file.endswith(("invariants.md", "CONTEXT-PACK.md")) or "CONVENTIONS.md" in file:
            return 2
        return 1

    def file_for(self, file: str) -> str:
        if file.startswith("config/"):
            return "<instance>/" + file
        if file == "CONVENTIONS.md":
            return "<repo>/CONVENTIONS.md"
        if file == "CONTEXT-PACK.md":
            return "<audit>/CONTEXT-PACK.md"
        return file

    # -- driver

    def skip_rest(self, after: str, reason: str) -> None:
        for name in STEPS[STEPS.index(after) + 1:]:
            if not any(s["step"] == name for s in self.steps):
                self.record(name, "skipped", f"not run: {reason}")

    def execute(self) -> int:
        a = self.args
        say(f"init: {self.facts['repo_name']} at {self.repo_sha[:12]}, runtime {a.runtime}")
        if self.preflight_warns:
            self.record("preflight", "warn", "optional tools missing: " + "; ".join(self.preflight_warns),
                        "; ".join(dict.fromkeys(self.preflight_fixes)) or None)
        else:
            self.record("preflight", "done", f"git repository at {self.repo_sha[:12]}; python3 and git present; "
                        "optional tools present")
        doctor = {"verdict": None, "kit_installed": False, "report": None}
        smoke = {"verdict": None, "loop_ran": False, "report": None}
        suggestions: list[dict] = []
        if self.step_instance():
            self.step_adapt()
            self.step_scaffolds()
            self.step_fetch()
            self.step_calibrate()
            self.step_install()
            self.step_baseline()
            self.step_map()
            doctor = self.step_doctor()
            smoke = self.step_smoke()
            suggestions = self.step_suggestions()
        else:
            self.skip_rest("instance", "the instance step failed")
        report = {
            "schema_version": SCHEMA_VERSION,
            "repo_sha": self.repo_sha,
            "repo_name": self.facts["repo_name"],
            "runtime": a.runtime,
            "placeholders": PLACEHOLDERS,
            "steps": self.steps,
            "pending_human_steps": self.pending_steps(),
            "suggestions": suggestions,
            "doctor": doctor,
            "smoke": smoke,
            "ready_for_benchmark": bool(doctor.get("kit_installed")) and bool(smoke.get("loop_ran")),
        }
        report = self.paths.sanitize(report)
        text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        if getattr(self, "instance_created", False):
            self.write_manifest()
        out = self.instance / "out" / "init" / f"{self.repo_sha}.json"
        if self.instance.is_dir():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        self.summary(report, out if self.instance.is_dir() else None)
        smoke_ok = a.no_smoke or smoke.get("verdict") == "PASS"
        return 0 if doctor.get("verdict") == "PASS" and smoke_ok else 1

    def write_manifest(self) -> None:
        """What this run (the one that created the instance) leaves behind, so
        --purge can tell init's own uncommitted changes from the owner's."""
        head = _git(self.instance, "rev-parse", "--verify", "--quiet", "HEAD")
        if head.code != 0:
            return
        uncommitted = {}
        for rel in porcelain_paths(self.instance):
            path = self.instance / rel
            if path.is_file() and not path.is_symlink():
                uncommitted[rel] = sha256_file(path)
        audit = {name: sha256_file(self.audit / name) for name in getattr(self, "scaffolds_written", [])
                 if (self.audit / name).is_file()}
        manifest = {"schema_version": SCHEMA_VERSION, "head": head.out.strip(), "uncommitted": uncommitted,
                    "audit": audit}
        target = self.instance / MANIFEST
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def summary(self, report: dict, out: Path | None) -> None:
        say()
        say("== pending human steps ==")
        for index, item in enumerate(report["pending_human_steps"], 1):
            say(f"  [ ] {index:2d}. ({item['section']}) {item['step']} -> {item['file']}")
        say()
        say("== suggestions (nothing was installed) ==")
        for entry in report["suggestions"]:
            say(f"  {entry['status']:<8} {entry['id']}" + (f": {entry['command']}" if entry["command"] else ""))
        say()
        d, s = report["doctor"], report["smoke"]
        say(f"doctor: {d['verdict']} (kit_installed {str(d['kit_installed']).lower()})  "
            f"smoke: {s['verdict']} (loop_ran {str(s['loop_ran']).lower()})  "
            f"ready_for_benchmark: {str(report['ready_for_benchmark']).lower()}")
        if out is not None:
            say(f"report: {out}")


# ----------------------------------------------------------------------------- uninstall (S13)

class Uninstall:
    """Unplugs the kit from a repo; the instance and the audit folder stay
    unless --purge proves them untouched."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.steps: list[dict] = []

    def record(self, step: str, status: str, detail: str, fix: str | None = None) -> None:
        self.steps.append({"step": step, "status": status, "detail": detail, "fix": fix})
        say(f"  {status:<7} {step}: {self.paths.show(detail)}")

    # -- preflight (read-only)

    def preflight(self) -> None:
        args = self.args
        if shutil.which("git") is None:
            raise UsageError("git is not on PATH")
        if not ((KIT_ROOT / "01-roles").is_dir() and (KIT_ROOT / "02-skills").is_dir()):
            raise UsageError(f"{KIT_TOOLS} is not the kit's 03-tools: run bin/init.sh from the kit")
        target = Path(args.repo).expanduser()
        if not target.is_dir():
            raise UsageError(f"not a directory: {args.repo}")
        top = _git(target, "rev-parse", "--show-toplevel")
        if top.code != 0 or not top.out.strip():
            raise UsageError(f"not a git repository: {args.repo}")
        repo = Path(top.out.strip()).resolve()
        if _inside(repo, KIT_ROOT) or _inside(KIT_ROOT, repo):
            raise UsageError(f"{args.repo} is the kit (or holds it): the kit is never installed into itself")
        head = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        self.repo, self.repo_sha = repo, (head.out.strip() if head.code == 0 and head.out.strip() else None)
        self.facts = detect_repo.detect(repo)
        home = _home()
        name = self.facts["repo_name"]
        instance = Path(os.path.abspath(Path(args.instance).expanduser() if args.instance else home / f"{name}-tools"))
        audit = Path(os.path.abspath(Path(args.audit).expanduser() if args.audit else home / f"{name}-audit"))
        for label, path in (("--instance", instance), ("--audit", audit)):
            if _inside(path, repo) or _inside(repo, path):
                raise UsageError(f"{label} {path} overlaps the target repo")
            if _inside(path, KIT_ROOT) or _inside(KIT_TOOLS, path):
                raise UsageError(f"{label} {path} overlaps the kit")
            if _inside(home, path):
                raise UsageError(f"{label} {path} is the home folder (or holds it)")
        if _inside(audit, instance) or _inside(instance, audit):
            raise UsageError("--instance and --audit must be two separate directories")
        if instance.exists() and not instance.is_dir():
            raise UsageError(f"--instance {instance} exists and is not a directory")
        self.instance, self.audit = instance, audit
        self.audit_arg = _tilde(audit, home)
        self.paths = Paths(repo, instance, audit, self.audit_arg, home)

    def report_path(self) -> Path:
        return self.instance / "out" / "uninstall" / f"{self.repo_sha or 'no-sha'}.json"

    def install_argv(self) -> list:
        return ["bash", KIT_TOOLS / "bin" / "install.sh", self.repo, "--uninstall", "--runtime", self.args.runtime,
                "--tools", self.instance]

    def doctor_argv(self) -> list:
        return [sys.executable, KIT_TOOLS / "lib" / "doctor.py", self.repo, "--absent", "--runtime", self.args.runtime]

    # -- purge verdicts (read-only)

    def manifest(self) -> dict | None:
        try:
            data = baseline.load_json(self.instance / MANIFEST)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def instance_verdict(self) -> tuple[str, list[str]]:
        inst = self.instance
        if not inst.exists():
            return "not found", []
        reasons: list[str] = []
        top = _git(inst, "rev-parse", "--show-toplevel")
        if top.code != 0 or os.path.realpath(top.out.strip()) != os.path.realpath(inst):
            return "refused", ["not a git repository of its own: init always makes the instance one"]
        count = _git(inst, "rev-list", "--count", "--all")
        commits = int(count.out.strip()) if count.code == 0 and count.out.strip().isdigit() else -1
        subject = _git(inst, "log", "-1", "--format=%s", "HEAD")
        head = _git(inst, "rev-parse", "--verify", "--quiet", "HEAD").out.strip()
        if commits != 1:
            others = _git(inst, "log", "--all", "--format=%h %s")
            listed = [l for l in others.out.splitlines() if INIT_COMMIT_PREFIX not in l][:5]
            reasons.append(f"{commits} commits in the instance (init makes exactly one): " + "; ".join(listed))
        elif not subject.out.strip().startswith(INIT_COMMIT_PREFIX):
            reasons.append(f"its only commit is not init's ('{subject.out.strip()}')")
        manifest = self.manifest()
        if manifest is not None and manifest.get("head") != head:
            reasons.append("HEAD is not the commit init recorded in out/init/manifest.json")
        recorded = (manifest or {}).get("uncommitted") or {}
        for rel in porcelain_paths(inst):
            path = inst / rel
            if manifest is None:
                reasons.append(f"uncommitted change: {rel} (no init manifest to prove init made it)")
            elif rel not in recorded:
                reasons.append(f"uncommitted change init did not make: {rel}")
            elif not path.is_file() or path.is_symlink() or sha256_file(path) != recorded[rel]:
                reasons.append(f"uncommitted change differs from what init left: {rel}")
        return ("refused", reasons) if reasons else ("purge", [])

    def audit_verdict(self) -> tuple[str, list[str]]:
        audit = self.audit
        if not audit.exists():
            return "not found", []
        if audit.is_symlink() or not audit.is_dir():
            return "refused", ["not a plain directory"]
        config = {}
        try:
            data = baseline.load_json(self.instance / "config" / "project.json")
            config = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            pass
        prefix = str(config.get("invariant_prefix") or "INV")
        language = self.facts.get("primary_language")
        renders = {"invariants.md": invariants_template(prefix), "CONTEXT-PACK.md": context_pack_template(KIT_TOOLS),
                   "CONVENTIONS.md.template": conventions_template(KIT_TOOLS, language)}
        recorded = ((self.manifest() or {}).get("audit") or {})
        reasons = []
        for dirpath, dirnames, filenames in os.walk(audit):
            for name in sorted(dirnames):
                rel = os.path.relpath(os.path.join(dirpath, name), audit)
                reasons.append(f"{rel}/: a folder init never writes")
            dirnames[:] = []  # a subfolder is already owner content; do not descend
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if name not in SCAFFOLDS:
                    reasons.append(f"{name}: not an init scaffold")
                    continue
                if path.is_symlink():
                    reasons.append(f"{name}: a symlink, not the scaffold init writes")
                    continue
                digest = sha256_file(path)
                if digest != hashlib.sha256(renders[name].encode("utf-8")).hexdigest() and digest != recorded.get(name):
                    reasons.append(f"{name}: differs from the scaffold init writes (owner work)")
        return ("refused", sorted(reasons)) if reasons else ("purge", [])

    # -- dry run

    def dry_run(self) -> int:
        a = self.args
        print(f"dry-run: nothing is written. Planned uninstall for {self.repo} "
              f"({(self.repo_sha or 'no commit')[:12]}):")
        print(f"   1. uninstall: {' '.join(str(x) for x in self.install_argv())}")
        print(f"   2. doctor: {' '.join(str(x) for x in self.doctor_argv())}")
        if a.purge:
            for label, path, (verdict, reasons) in (("instance", self.instance, self.instance_verdict()),
                                                     ("audit", self.audit, self.audit_verdict())):
                what = {"purge": "would be deleted" + (" once the repo is kit_absent" if label == "instance" else ""),
                        "not found": "not found, nothing to delete"}.get(
                    verdict, "refused: " + "; ".join(reasons))
                print(f"   3. purge {label} {path}: {what}")
        else:
            print(f"   3. purge: skipped (no --purge): {self.instance} and {self.audit} stay")
        print(f"   4. report: {self.report_path()} (stdout only if the instance is gone)")
        proc = run(self.doctor_argv())
        try:
            report = json.loads(proc.out)
            left = [f"{c['id']}: {c['detail']}" for c in report.get("checks", []) if c.get("status") != "PASS"]
        except (json.JSONDecodeError, AttributeError):
            left = [f"doctor --absent did not report: {proc.last_line()}"]
        print("  installed now: " + ("nothing (kit_absent)" if not left else ""))
        for line in left:
            print(f"    {self.paths.show(line)}")
        return 0

    # -- run

    def execute(self) -> int:
        a = self.args
        say(f"uninstall: {self.facts['repo_name']} ({(self.repo_sha or 'no commit')[:12]}), runtime {a.runtime}")
        lists = {"-": set(), "!": set(), ".": set(), "=": set()}
        proc = run(self.install_argv())
        for line in (proc.out + proc.err).splitlines():
            match = ITEM_RE.match(line)
            if match:
                lists[match.group(1)].add(match.group(2))
                say(line)
        fix = f"<kit>/bin/install.sh <repo> --uninstall --runtime {a.runtime} --tools <instance>"
        if proc.code != 0:
            self.record("uninstall", "fail", f"install.sh --uninstall failed: {proc.last_line()}", fix)
        else:
            self.record("uninstall", "done", f"{len(lists['-'])} removed, {len(lists['!'])} kept (modified), "
                        f"{len(lists['='] - lists['-'])} kept (in use), {len(lists['.'] - lists['-'])} not found")
        doctor = self.step_doctor()
        instance, audit = self.step_purge(bool(doctor.get("kit_absent")))
        removed = sorted(lists["-"])
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "uninstall",
            "repo_sha": self.repo_sha,
            "repo_name": self.facts["repo_name"],
            "runtime": a.runtime,
            "placeholders": PLACEHOLDERS,
            "steps": self.steps,
            "removed": removed,
            "kept_modified": sorted(lists["!"] - lists["-"]),
            "kept_in_use": sorted(lists["="] - lists["-"]),
            "not_found": sorted(lists["."] - lists["-"]),
            "doctor": doctor,
            "kit_absent": bool(doctor.get("kit_absent")),
            "purge": bool(a.purge),
            "instance": instance,
            "audit": audit,
        }
        report = self.paths.sanitize(report)
        text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        out = self.report_path()
        if self.instance.is_dir():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        say()
        say(f"kit_absent: {str(report['kit_absent']).lower()}  instance: {instance['action']}  "
            f"audit: {audit['action']}")
        if report["kept_modified"]:
            say("kept (modified, yours to delete by hand): " + ", ".join(report["kept_modified"]))
        say(f"report: {out}" if self.instance.is_dir() else "report: stdout only (the instance is gone)")
        refused = "refused" in (instance["action"], audit["action"])
        return 0 if report["kit_absent"] and proc.code == 0 and not refused else 1

    def step_doctor(self) -> dict:
        proc = run(self.doctor_argv())
        try:
            report = json.loads(proc.out)
        except json.JSONDecodeError:
            report = None
        if not isinstance(report, dict):
            self.record("doctor", "fail", f"doctor.py --absent did not report: {proc.last_line()}",
                        "python3 <kit>/lib/doctor.py <repo> --absent --table")
            return {"verdict": "FAIL", "kit_absent": False, "failing": []}
        failing = sorted(c["id"] for c in report.get("checks", []) if c.get("status") != "PASS")
        detail = f"verdict {report.get('verdict')}, kit_absent {str(bool(report.get('kit_absent'))).lower()}"
        fixes = "; ".join(f"{c['id']}: {c['fix']}" for c in report.get("checks", []) if c.get("status") == "FAIL"
                          and c.get("fix"))
        if failing:
            detail += "; left: " + ", ".join(failing)
        self.record("doctor", "done" if report.get("kit_absent") else "fail", detail, fixes or None)
        return {"verdict": report.get("verdict"), "kit_absent": bool(report.get("kit_absent")), "failing": failing}

    def step_purge(self, kit_absent: bool) -> tuple[dict, dict]:
        if not self.args.purge:
            self.record("purge", "skipped", "no --purge: the instance and the audit folder stay")
            keep = lambda p: {"action": "kept" if p.exists() else "not found", "reasons": []}  # noqa: E731
            return keep(self.instance), keep(self.audit)
        # both verdicts first: the audit check reads the instance's config
        verdicts = {"instance": self.instance_verdict(), "audit": self.audit_verdict()}
        if not kit_absent and verdicts["instance"][0] != "not found":
            # kit files left in the repo (kept as modified) still point at the instance's hooks and server
            reasons = ["the repo is not kit_absent: kit files it still holds point at this instance "
                       "(see kept_modified and doctor.failing)"]
            verdicts["instance"] = ("refused", reasons + list(verdicts["instance"][1]))
        result = {}
        for label, path in (("instance", self.instance), ("audit", self.audit)):
            verdict, reasons = verdicts[label]
            if verdict == "purge":
                try:
                    shutil.rmtree(path)
                    result[label] = {"action": "purged", "reasons": []}
                except OSError as exc:
                    result[label] = {"action": "refused", "reasons": [f"could not delete: {exc.strerror}"]}
            elif verdict == "not found":
                result[label] = {"action": "not found", "reasons": []}
            else:
                result[label] = {"action": "refused", "reasons": reasons}
        refused = [k for k in ("instance", "audit") if result[k]["action"] == "refused"]
        detail = f"instance {result['instance']['action']}, audit {result['audit']['action']}"
        if refused:
            detail += "; " + "; ".join(f"{k}: " + ", ".join(result[k]["reasons"]) for k in refused)
        self.record("purge", "warn" if refused else "done", detail,
                    "review the listed work, move what you keep, then delete the folder by hand" if refused else None)
        return result["instance"], result["audit"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="init.sh", description="One command from zero to a working kit instance.")
    parser.add_argument("repo")
    parser.add_argument("--instance", default=None, help="tools instance (default ~/<repo_name>-tools)")
    parser.add_argument("--audit", default=None, help="audit folder (default ~/<repo_name>-audit)")
    parser.add_argument("--runtime", choices=RUNTIMES, default="all")
    parser.add_argument("--answers", default=None, help="owner answers for adopt.sh, inline JSON or a file")
    parser.add_argument("--engram-project", default=None)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--no-smoke", action="store_true")
    parser.add_argument("--read-global-config", action="store_true",
                        help="let the suggestions test ~/.claude.json and ~/.pi/agent/mcp.json for an MCP server key")
    parser.add_argument("--dry-run", action="store_true", help="print the planned steps; write nothing anywhere")
    parser.add_argument("--uninstall", action="store_true",
                        help="unplug the kit from the repo; the instance and the audit folder stay")
    parser.add_argument("--purge", action="store_true",
                        help="with --uninstall: also delete the instance and the audit folder, only when untouched")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.purge and not args.uninstall:
        print("init: --purge only applies with --uninstall", file=sys.stderr)
        return 2
    if args.uninstall:
        unplug = Uninstall(args)
        try:
            unplug.preflight()
        except UsageError as exc:
            print(f"init: {exc}", file=sys.stderr)
            return 2
        return unplug.dry_run() if args.dry_run else unplug.execute()
    init = Init(args)
    try:
        init.preflight()
    except UsageError as exc:
        print(f"init: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"dry-run: nothing is written. Planned steps for {init.repo} ({init.repo_sha[:12]}):")
        for index, (name, what) in enumerate(init.plan(), 1):
            print(f"  {index:2d}. {name}: {what}")
        if init.preflight_warns:
            print("  preflight warnings: " + "; ".join(init.preflight_warns))
        return 0
    return init.execute()


if __name__ == "__main__":
    raise SystemExit(main())
