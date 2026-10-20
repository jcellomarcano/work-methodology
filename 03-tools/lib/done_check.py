#!/usr/bin/env python3
"""Done gate: DONE-01..17 over explicit inputs before a reply says "done"
(context-method §6, odd/research/context/done-gate.md §3).

    lib/done_check.py --repo R (--reply FILE|- | --claim CLASS ...) [options]

DONE-01 reads the final reply (outside code, quotes and blockquotes) for a
claim class: done, green, committed, delivered (English and Spanish words,
plus `status: completed`, in config/done-gate.json). No claim: nothing else
runs (not even git) and the verdict is `no-claim`. Otherwise every rule is
reported, in order, as PASS, FLAG, BLOCK or SKIP (a SKIP always says why).
A failing rule reports its `mode` from the config; the shipped config has
every rule in FLAG (D2, warn first) and records the done-gate.md mode as
`target_mode`. Mode PASS turns a rule off: SKIP with its findings.

Inputs, all explicit (the gate reads files; the only subprocesses are git,
docs_lint, the repo's kit_status --check and cite_check, each with a
timeout):
  --runs FILE          runs.jsonl from bin/run-check.sh (default <tools>/out/runs/runs.jsonl or $METODO_RUNS_DIR)
  --receipts DIR       receipts (default $METODO_RDD_DIR or <tools>/out/rdd)
  --base REF           touched paths and diffs against REF (default: uncommitted changes vs HEAD)
  --session-dir DIR    out/hooks/<session>/: touched.jsonl, ledger.jsonl (no-verify, owner waivers)
  --touched FILE       extra touched.jsonl (repeatable)
  --task FILE          task document (DONE-08)     --card FILE    change card (DONE-09)
  --subagent-return F  writer return block (DONE-16; default: the reply itself)
  --known-failure S    a validation line containing S is a known failure (repeatable)
  --open-jobs N        running background jobs the harness reports (DONE-17 cannot see them)
  --temp-path P        scratch paths the session created (repeatable, DONE-17)
  --tier T             receipt tier (default: the current tree's receipt); exempt skips 02, 03, 04, 09
  --strict-tdd         DONE-03 uses its strict_tdd_mode      --refactor-only   DONE-03 is a SKIP
  --waivers FILE       owner waivers to read (repeatable; see below)
  --docs-caps FILE     docs caps (default <repo>/03-tools/config/docs-caps.json)
  --format json|block  json (default) or only the DONE-GATE block

"After the last edit" is the worktree fingerprint of lib/run_check.py: a run
proves the current tree only if its worktree_sha equals the current one.

Owner waivers are read, never written here (`--waive` is the owner's step):
one JSON line {"kind": "done-waiver", "rule": "DONE-xx", "tree_sha": ...,
"worktree_sha": ..., "reason": ..., "email": ...}. It applies while
worktree_sha equals the current one (without worktree_sha: tree_sha equal on
a clean tree); the block then shows `WAIVED by <email>: <reason>`.

Output: sorted JSON (schemas/done-check-output.schema.json), same inputs
same bytes. Exit 0 when no unwaived BLOCK, 1 on any, 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import cite_check, run_check  # noqa: E402

SCHEMA_VERSION = 1
CLAIMS = ("committed", "delivered", "done", "green")
RULE_IDS = tuple(f"DONE-{n:02d}" for n in range(1, 18))
MODES = ("PASS", "FLAG", "BLOCK")
TIERS = ("exempt", "low", "medium", "high")
DEFAULT_CONFIG = TOOLS_ROOT / "config" / "done-gate.json"
SHA_TOKEN = re.compile(r"(?<![\w/.-])([0-9a-f]{7,40})(?![\w-])")


class UsageError(Exception):
    pass


class Skip(Exception):
    pass


class Outcome:
    def __init__(self, findings=(), ok=(), fix="", flag_only=()):
        self.findings, self.ok, self.fix, self.flag_only = list(findings), list(ok), fix, list(flag_only)


def _sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


# --------------------------------------------------------------------------- claims (DONE-01)

def _claim_text(text: str) -> str:
    text = re.sub(r"(?ms)^[ \t]*```.*?(?:^[ \t]*```[^\n]*$|\Z)", " ", text)
    text = re.sub(r"(?m)^[ \t]*>.*$", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    return re.sub(r"\"[^\"\n]*\"|“[^”\n]*”|«[^»\n]*»", " ", text)


def detect_claims(text: str, config: dict) -> list[str]:
    found: set[str] = set()
    if re.search(config["status_completed"], text or ""):
        found.add("done")
    clean = _claim_text(text or "")
    for pattern in config.get("claim_exclusions", []):
        clean = re.sub(pattern, " ", clean)
    negation = re.compile(config["negation_before"])
    for claim, patterns in sorted(config["claims"].items()):
        for pattern in patterns:
            for match in re.finditer(pattern, clean, re.IGNORECASE):
                prefix = re.split(r"[.!?;\n]", clean[:match.start()])[-1]
                if not negation.search(prefix):
                    found.add(claim)
                    break
            if claim in found:
                break
    return sorted(found)


# --------------------------------------------------------------------------- helpers

def _glob_re(glob: str) -> re.Pattern:
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, globs: list[str]) -> bool:
    return any(_glob_re(g).match(path) for g in globs)


def sector_of(path: str, config: dict) -> str:
    for sector in config.get("sectors", []):
        if matches(path, sector["globs"]):
            return sector["name"]
    return path.split("/", 1)[0] if "/" in path else "."


def _read_jsonl(path: Path) -> list[dict]:
    if not path or not Path(path).is_file():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Gate:
    """Lazily computed facts shared by the rules."""

    def __init__(self, args, config: dict, reply: str, claims: list[str]):
        self.args, self.config, self.reply, self.claims = args, config, reply, claims
        self.repo = Path(args.repo).resolve()
        self.fp = run_check.worktree_fingerprint(self.repo)
        self.status = run_check.status_entries(self.repo)
        self.runs = sorted(_read_jsonl(Path(args.runs)), key=lambda r: (r.get("seq") or 0))
        self.current_runs = [r for r in self.runs if r.get("worktree_sha") == self.fp["worktree_sha"]]
        self.session = Path(args.session_dir) if args.session_dir else None
        self.ledger = _read_jsonl(self.session / "ledger.jsonl") if self.session else []
        self.receipt = self._receipt()
        self.touched = self._touched()
        self.results: dict[str, dict] = {}
        self.skip_keywords: dict[str, list[str]] = {}
        self._diff = None

    def git(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, timeout=timeout)

    def _receipt(self) -> dict | None:
        tree = self.fp["tree_sha"]
        path = Path(self.args.receipts) / f"{tree}.receipt.json" if tree else None
        if not path or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _touched(self) -> list[str]:
        paths = {p for _, p in self.status}
        if self.args.base:
            out = self.git("diff", "--name-only", "--no-renames", self.args.base)
            if out.returncode != 0:
                raise UsageError(f"--base {self.args.base}: {out.stderr.strip()}")
            paths |= {p for p in out.stdout.splitlines() if p}
        files = [Path(t) for t in self.args.touched] + ([self.session / "touched.jsonl"] if self.session else [])
        for file in files:
            for row in _read_jsonl(file):
                rel = str(row.get("path") or "")
                if rel and not rel.startswith(("/", "../")):
                    paths.add(rel)
        return sorted(p for p in paths if not p.startswith(".claude/"))

    @property
    def tier(self) -> str | None:
        return self.args.tier or ((self.receipt or {}).get("risk") or {}).get("tier")

    def exempt(self, path: str) -> bool:
        return matches(path, self.config["exempt_globs"])

    def is_test(self, path: str) -> bool:
        return matches(path, self.config["test_globs"])

    def diff(self) -> dict[str, dict]:
        """{path: {"added": [(line, text)], "removed": [text]}} vs --base or HEAD, plus untracked files."""
        if self._diff is not None:
            return self._diff
        result: dict[str, dict] = {}
        ref = self.args.base or ("HEAD" if self.fp["head_sha"] else None)
        if ref:
            out = self.git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", ref)
            current, line_no = None, 0
            for line in out.stdout.splitlines():
                if line.startswith("diff --git "):
                    current = None
                elif line.startswith("+++ "):
                    if line.startswith("+++ b/"):  # "+++ /dev/null" (a deletion) keeps the "--- a/" path
                        current = line[6:]
                        result.setdefault(current, {"added": [], "removed": []})
                elif line.startswith("--- "):
                    old = line[6:] if line.startswith("--- a/") else None
                    if old:
                        result.setdefault(old, {"added": [], "removed": []})
                        current = old
                elif line.startswith("@@"):
                    m = re.search(r"\+(\d+)", line)
                    line_no = int(m.group(1)) if m else 0
                elif current and line.startswith("+"):
                    result[current]["added"].append((line_no, line[1:]))
                    line_no += 1
                elif current and line.startswith("-"):
                    result[current]["removed"].append(line[1:])
        for xy, path in self.status:
            full = self.repo / path
            if xy == "??" and full.is_file():
                data = full.read_bytes()
                if b"\0" in data:
                    continue
                lines = data.decode("utf-8", "replace").splitlines()
                result[path] = {"added": list(enumerate(lines, start=1)), "removed": []}
        self._diff = result
        return result


# --------------------------------------------------------------------------- rules

def _need_touched(g: Gate) -> None:
    if not g.touched:
        raise Skip("no touched path known: clean tree and no --base, --touched or --session-dir")


def _last_run(runs: list[dict], name: str) -> dict | None:
    named = [r for r in runs if r.get("name") == name]
    return named[-1] if named else None


def _run_fix(g: Gate, sector: str) -> str:
    last = _last_run(g.runs, sector)
    command = " ".join(last["argv"]) if last and isinstance(last.get("argv"), list) else "<test command>"
    return f"bin/run-check.sh {sector} -- {command}"


def rule_01(g: Gate) -> Outcome:
    return Outcome(ok=["claims: " + ", ".join(g.claims)])


def rule_02(g: Gate) -> Outcome:
    _need_touched(g)
    code = [p for p in g.touched if not g.exempt(p)]
    if not code:
        return Outcome(ok=[f"only exempt paths touched ({len(g.touched)})"])
    findings, ok, missing = [], [], []
    for sector in sorted({sector_of(p, g.config) for p in code}):
        first = next(p for p in code if sector_of(p, g.config) == sector)
        last = _last_run(g.current_runs, sector)
        if last is None:
            findings.append(f"no run of sector {sector} on the current tree ({first})")
            missing.append(sector)
        elif last.get("exit") != 0:
            findings.append(f"last run of sector {sector} on the current tree exited {last.get('exit')} (seq {last.get('seq')})")
            missing.append(sector)
        else:
            ok.append(f"sector {sector}: run seq {last.get('seq')} exit 0 on the current tree")
    if missing:
        g.skip_keywords["DONE-02"] = missing
    return Outcome(findings, ok, "; ".join(_run_fix(g, s) for s in missing))


def rule_03(g: Gate) -> Outcome:
    if g.args.refactor_only:
        raise Skip("declared refactor-only (--refactor-only)")
    _need_touched(g)
    behavior = [p for p in g.touched if not g.exempt(p) and not g.is_test(p)]
    if not behavior:
        raise Skip("no behavior path touched (only tests or exempt paths)")
    findings, ok, missing = [], [], []
    for sector in sorted({sector_of(p, g.config) for p in behavior}):
        green = next((r for r in reversed(g.current_runs) if r.get("name") == sector and r.get("exit") == 0), None)
        limit = green.get("seq") if green else float("inf")
        red = next((r for r in g.runs if r.get("name") == sector and r.get("exit") not in (0, None)
                    and (r.get("seq") or 0) < limit), None)
        if red is None:
            findings.append(f"no failing run of sector {sector} recorded" + (" before its green run" if green else ""))
            missing.append(sector)
        else:
            ok.append(f"sector {sector}: red seq {red.get('seq')} before green")
    if missing:
        g.skip_keywords["DONE-03"] = missing
    return Outcome(findings, ok, "rerun the new test against the old code through bin/run-check.sh, "
                                 "or declare the exception (--refactor-only)")


def rule_04(g: Gate) -> Outcome:
    _need_touched(g)
    tests = [p for p in g.touched if g.is_test(p) and not matches(p, g.config["vendored_globs"])]
    if not tests:
        return Outcome(ok=["no test path touched"])
    patterns = {k: re.compile(v) for k, v in g.config["weakened_test"].items()}
    diff = g.diff()
    findings = []
    for path in tests:
        change = diff.get(path)
        if not change:
            continue
        added = [text for _, text in change["added"]]
        removed = change["removed"]
        count = lambda lines, key: sum(1 for line in lines if patterns[key].search(line))  # noqa: E731
        for key, label in (("test_function", "test function"), ("assertion", "assertion")):
            lost = count(removed, key) - count(added, key)
            if lost > 0:
                findings.append(f"{path}: {lost} {label}(s) removed")
        skips = count(added, "skip_marker") - count(removed, "skip_marker")
        if skips > 0:
            findings.append(f"{path}: {skips} skip/ignore/xfail marker(s) added")
    return Outcome(findings, [f"{len(tests)} test path(s): no test, assertion or skip weakened"],
                   "restore the test or assertion, or get an owner waiver")


def rule_05(g: Gate) -> Outcome:
    caps_path = Path(g.args.docs_caps) if g.args.docs_caps else g.repo / g.config["docs_caps"]
    if not caps_path.is_file():
        raise Skip(f"no docs caps config in this repo ({g.config['docs_caps']})")
    argv = ["python3", str(TOOLS_ROOT / "lib" / "docs_lint.py"), str(caps_path), "--root", str(g.repo)]
    tokens = g.repo / g.config["token_caps"]
    if tokens.is_file():
        argv += ["--tokens", str(tokens)]
    fix = "trim the doc, or add its cap to docs-caps.json with a change card"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=g.config["timeouts_s"]["docs_lint"])
        report = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return Outcome([f"docs_lint timed out after {g.config['timeouts_s']['docs_lint']}s"], fix=fix)
    except ValueError:
        return Outcome([f"docs_lint printed no JSON (exit {proc.returncode})"], fix=fix)
    findings = [f"{o['path']}: {o['actual']} > {o['limit']} {o.get('unit', 'lines')}" for o in report.get("offenders", [])]
    try:
        capped = set(json.loads(caps_path.read_text(encoding="utf-8")).get("caps", {}))
    except ValueError:
        capped = set()
    folders = {str(Path(c).parent) for c in capped}
    new = [p for xy, p in g.status if p.endswith(".md") and ("?" in xy or "A" in xy) and p not in capped
           and str(Path(p).parent) in folders]
    flag_only = [f"new doc without a cap: {p}" for p in new]
    return Outcome(findings, [f"{len(report.get('ok', []))} capped doc(s) under cap"], fix, flag_only)


def rule_06(g: Gate) -> Outcome:
    if not all((g.repo / marker).exists() for marker in g.config["kit_markers"]):
        raise Skip("not a kit checkout (" + ", ".join(g.config["kit_markers"]) + " missing)")
    fix = "03-tools/bin/kit-status.sh --write, then commit README.md"
    argv = ["python3", str(g.repo / "03-tools" / "lib" / "kit_status.py"), "--check", "--root", str(g.repo)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=g.config["timeouts_s"]["kit_status"])
    except subprocess.TimeoutExpired:
        return Outcome([f"kit-status --check timed out after {g.config['timeouts_s']['kit_status']}s"], fix=fix)
    if proc.returncode == 0:
        return Outcome(ok=["kit-status --check exit 0"])
    first = next((l for l in (proc.stdout + "\n" + proc.stderr).splitlines() if l.strip()), "")
    return Outcome([f"kit-status --check exit {proc.returncode}: {first}"], fix=fix)


def rule_07(g: Gate) -> Outcome:
    fix = "run the receipt loop (receipt_start ... receipt_finalize), or ask the owner for an ack and quote it"
    tree = g.fp["tree_sha"]
    receipt = g.receipt
    if receipt is None:
        return Outcome([f"no receipt for tree {(tree or 'none')[:7]}"], fix=fix)
    ack = receipt.get("owner_ack") if isinstance(receipt.get("owner_ack"), dict) else None
    if receipt.get("verdict") == "approved" and not (ack and ack.get("decision") == "unreviewed"):
        return Outcome(ok=[f"receipt {tree[:7]} approved"])
    if ack and ack.get("reason") and ack["reason"] in g.reply:
        return Outcome(ok=[f"owner ack ({ack.get('decision')}) recorded and quoted"])
    if ack:
        return Outcome([f"owner ack ({ack.get('decision')}) recorded but its reason is not quoted in the reply"], fix=fix)
    return Outcome([f"receipt {tree[:7]} verdict {receipt.get('verdict')}, no owner ack"], fix=fix)


def _specs_and_rows(text: str) -> tuple[list[str], list[dict]]:
    section = re.search(r"(?ms)^## Specs\b(.*?)(?=^## |\Z)", text)
    specs = re.findall(r"(?m)^\s*[-*]\s*\**\s*(S\d+)\b", section.group(1)) if section else []
    if not specs:
        specs = re.findall(r"\bS\d+\b", text)
    specs = sorted(set(specs), key=lambda s: int(s[1:]))
    rows, header = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        lower = [c.lower() for c in cells]
        if "specs" in lower and "status" in lower:
            header = {name: lower.index(name) for name in ("id", "specs", "status", "evidence") if name in lower}
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        get = lambda key: cells[header[key]] if key in header and header[key] < len(cells) else ""  # noqa: E731
        ids = set()
        for start, end in re.findall(r"S(\d+)(?:\s*[-–]\s*S?(\d+))?", get("specs")):
            ids |= {f"S{n}" for n in range(int(start), int(end or start) + 1)}
        rows.append({"id": get("id") or cells[0], "specs": ids, "status": get("status"), "evidence": get("evidence")})
    return specs, rows


def rule_08(g: Gate) -> Outcome:
    if not g.args.task:
        raise Skip("no task document given (--task)")
    if "delivered" not in g.claims and not any(re.search(p, g.reply) for p in g.config["feature_claim"]):
        raise Skip("task-level claim: the reply makes no feature or delivery claim")
    text = Path(g.args.task).read_text(encoding="utf-8")
    specs, rows = _specs_and_rows(text)
    verdicts = {m.group(1) for m in re.finditer(g.config["spec_verdict"], text)}
    findings = []
    for spec in specs:
        if spec in verdicts:
            continue
        cited = [r for r in rows if spec in r["specs"]]
        if not cited:
            findings.append(f"{spec}: no task row and no verdict")
            continue
        open_rows = [r for r in cited if not (r["status"].lower().startswith("done") and r["evidence"])]
        if open_rows:
            findings.append(f"{spec} open: " + ", ".join(f"{r['id']} ({r['status'] or 'no status'})" for r in open_rows))
    return Outcome(findings, [f"{len(specs)} spec(s) judged"], "fill the row's status and evidence, or say the spec is open")


def rule_09(g: Gate) -> Outcome:
    if not g.args.card:
        raise Skip("no change card given (--card)")
    text = Path(g.args.card).read_text(encoding="utf-8")
    labels = "|".join(re.escape(label) for label in g.config["card_how_labels"])
    m = re.search(rf"(?im)^\W*(?:{labels})\W*:\s*(.+)$", text)
    spans = re.findall(r"`([^`]+)`", m.group(1)) if m else []
    if not spans:
        raise Skip("the card's \"How we'll know\" names no command in backticks")
    ran = [" ".join(r.get("argv") or []) for r in g.current_runs] + [str(r.get("name")) for r in g.current_runs]
    missing = [s for s in spans if not any(s in line for line in ran)]
    if missing:
        g.skip_keywords["DONE-09"] = missing
    return Outcome([f"not run on the current tree: {s}" for s in missing], [f"{len(spans)} card command(s) ran"],
                   "run it through bin/run-check.sh, or list it under Not tested")


def rule_10(g: Gate) -> Outcome:
    items = [(rid, words) for rid, words in sorted(g.skip_keywords.items())
             if g.results.get(rid, {}).get("status") in ("FLAG", "BLOCK")]
    if any(row.get("kind") == "no-verify" for row in g.ledger):
        items.append(("--no-verify", ["no-verify"]))
    if not items:
        return Outcome(ok=["no skip found by DONE-02/03/09 or the ledger"])
    markers = [m.lower() for m in g.config["not_tested_markers"]]
    lower = g.reply.lower()
    sections = []
    for marker in markers:
        for m in re.finditer(re.escape(marker), lower):
            sections.append(lower[m.start():].split("\n\n", 1)[0])
    labels = ", ".join(rid for rid, _ in items)
    fix = "add a \"Not tested:\" line naming each skip"
    if not sections:
        return Outcome([f"skips ({labels}) and no \"Not tested:\" line"], fix=fix)
    joined = "\n".join(sections)
    findings = [f"{rid} skip not named (expected one of: {', '.join(words)})" for rid, words in items
                if not any(w.lower() in joined for w in words)]
    return Outcome(findings, [f"Not tested line names {labels}"], fix)


def _added_lines(g: Gate) -> list[tuple[str, int, str]]:
    out = []
    for path, change in sorted(g.diff().items()):
        if g.exempt(path) or matches(path, g.config["vendored_globs"]):
            continue
        out += [(path, n, text) for n, text in change["added"]]
    return out


def rule_11(g: Gate) -> Outcome:
    tag, ticketed = re.compile(g.config["action_tag"]), re.compile(g.config["action_tag_ticketed"])
    added = _added_lines(g)
    findings = [f"{p}:{n}: {_short(t.strip(), 60)}" for p, n, t in added if tag.search(t) and not ticketed.search(t)]
    return Outcome(findings, [f"{len(added)} added line(s): no unticketed action tag"],
                   "write TODO(KEY-###): or remove the tag")


def rule_12(g: Gate) -> Outcome:
    """Added lines only (like DONE-11): a file that already names the marker
    in prose (a tool description) is not a leftover of this change."""
    marker = re.compile(g.config["comment_marker"])
    added = _added_lines(g)
    findings = [f"{p}:{n}" for p, n, t in added if marker.search(t)]
    return Outcome(findings, [f"{len(added)} added line(s): no marker"], "run the comment-gate round")


def rule_13(g: Gate) -> Outcome:
    findings = []
    dirty = [p for _, p in g.status]
    if dirty:
        shown = ", ".join(dirty[:5]) + (f" (+{len(dirty) - 5})" if len(dirty) > 5 else "")
        findings.append(f"uncommitted: {shown}")
    commit_line = re.compile(g.config["commit_line"])
    cited = []
    for line in g.reply.splitlines():
        if not commit_line.search(line):
            continue
        for m in SHA_TOKEN.finditer(line):
            token = m.group(1)
            before = line[:m.start()].rstrip().lower()
            if re.search(r"[a-f]", token) and re.search(r"\d", token) and not before.endswith(("tree", "tool")):
                cited.append(token)
    for token in sorted(set(cited)):
        if g.git("rev-parse", "--verify", "-q", f"{token}^{{commit}}").returncode != 0:
            findings.append(f"cited sha {token} is not a commit here")
        elif g.git("merge-base", "--is-ancestor", token, "HEAD").returncode != 0:
            findings.append(f"cited sha {token} is not reachable from HEAD")
    return Outcome(findings, [f"clean tree; {len(set(cited))} cited sha(s) reachable"],
                   "commit the paths (or say \"uncommitted\") and cite shas reachable from HEAD")


def rule_14(g: Gate) -> Outcome:
    fix = "fix the cited path, line or sha"
    argv = ["python3", str(TOOLS_ROOT / "lib" / "cite_check.py"), "-", "--repo", str(g.repo)]
    try:
        proc = subprocess.run(argv, input=g.reply, capture_output=True, text=True,
                              timeout=g.config["timeouts_s"]["cite_check"])
        report = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return Outcome([f"cite_check timed out after {g.config['timeouts_s']['cite_check']}s"], fix=fix)
    except ValueError:
        return Outcome([f"cite_check printed no JSON (exit {proc.returncode})"], fix=fix)
    refs = report.get("refs", [])
    findings = []
    for ref in refs:
        if ref.get("status") in ("MISSING", "MISSING_HTTP"):
            where = ref.get("url") or f"{ref['path']}:{ref['start']}" + (f"-{ref['end']}" if ref.get("end") else "") \
                + (f" @ {ref['sha']}" if ref.get("sha") else "")
            findings.append(f"missing citation {where} (line {ref.get('line')})")
    return Outcome(findings, [f"{len(refs)} citation(s) checked, 0 missing"], fix)


def rule_15(g: Gate) -> Outcome:
    tag = re.compile(g.config["evidence_tags"])
    pasted = "```" in g.reply
    in_code, bare, tagged = False, [], 0
    for n, line in enumerate(g.reply.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not tag.search(line):
            continue
        tagged += 1
        cited = cite_check._FILE_REF.search(line) or cite_check._URL.search(line) or SHA_TOKEN.search(line)
        if not (cited or pasted or g.current_runs):
            bare.append(f"line {n}: {_short(line.strip(), 60)}")
    findings = [f"tag without citation, pasted output or run: {b}" for b in bare]
    return Outcome(findings, [f"{tagged} tagged unit(s) backed"], "cite, paste the output, or lower the tag")


def _return_block(g: Gate) -> str:
    if g.args.subagent_return:
        return Path(g.args.subagent_return).read_text(encoding="utf-8")
    return g.reply


def rule_16(g: Gate) -> Outcome:
    text = _return_block(g)
    m = re.search(r"(?im)^\s*status:\s*([\w-]+)", text)
    if not m:
        raise Skip("no subagent return block (status:) in the reply or --subagent-return")
    if m.group(1).lower() != "completed":
        return Outcome(ok=[f"status {m.group(1)}: no completion claimed"])
    lines, inside = [], False
    for line in text[m.end():].splitlines():
        if re.match(r"^\s*validation:\s*$", line):
            inside = True
            continue
        if inside:
            if re.match(r"^\s+-\s", line):
                lines.append(line.strip()[2:])
            elif line.strip() and not line.startswith((" ", "\t")):
                break
    fix = "report status: partial, or name the failure as known (--known-failure)"
    if not lines:
        return Outcome(["status: completed with no validation line"], fix=fix)
    fail, ok = re.compile(g.config["validation_fail"]), re.compile(g.config["validation_pass"])
    findings = []
    for line in lines:
        if any(k and k in line for k in g.args.known_failure):
            continue
        if fail.search(line) or not ok.search(line):
            findings.append(f"validation not green: {_short(line, 80)}")
    return Outcome(findings, [f"{len(lines)} validation line(s) green or known"], fix)


def rule_17(g: Gate) -> Outcome:
    findings = []
    if g.args.open_jobs:
        findings.append(f"{g.args.open_jobs} background job(s) still running")
    for raw in g.args.temp_path:
        path = Path(raw) if Path(raw).is_absolute() else g.repo / raw
        if path.exists():
            try:
                shown = path.resolve().relative_to(g.repo).as_posix()
            except ValueError:
                shown = raw
            findings.append(f"temp path left: {shown}")
    leftovers = [p for xy, p in g.status if xy == "??" and matches(p, g.config["temp_globs"])]
    findings += [f"untracked leftover: {p}" for p in leftovers]
    return Outcome(findings, ["no running job, no temp leftover"], "stop it, delete it, or say why it stays")


RULES = {f"DONE-{n:02d}": fn for n, fn in enumerate(
    (rule_01, rule_02, rule_03, rule_04, rule_05, rule_06, rule_07, rule_08, rule_09, rule_10, rule_11, rule_12,
     rule_13, rule_14, rule_15, rule_16, rule_17), start=1)}


# --------------------------------------------------------------------------- evaluation

def _waivers(args, g: Gate) -> dict[str, dict]:
    rows = [r for path in args.waivers for r in _read_jsonl(Path(path))] + g.ledger
    active = {}
    for row in rows:
        if row.get("kind") != "done-waiver" or row.get("rule") not in RULE_IDS:
            continue
        if row.get("worktree_sha"):
            valid = row["worktree_sha"] == g.fp["worktree_sha"]
        else:
            valid = row.get("tree_sha") == g.fp["tree_sha"] and not g.fp["dirty"]
        if valid:
            active[row["rule"]] = {"email": str(row.get("email") or "unknown"), "reason": str(row.get("reason") or "")}
    return active


def _status_for(mode: str, outcome: Outcome) -> str:
    if outcome.findings:
        return mode
    if outcome.flag_only:
        return "FLAG"  # never above FLAG, whatever the mode (done-gate.md: DONE-05 new doc)
    return "PASS"


def evaluate(g: Gate) -> list[dict]:
    waivers = _waivers(g.args, g)
    rules = []
    for rule_id in RULE_IDS:
        spec = g.config["rules"][rule_id]
        mode = spec["mode"]
        if rule_id == "DONE-03" and g.args.strict_tdd:
            mode = spec.get("strict_tdd_mode", mode)
        entry = {"id": rule_id, "mode": mode, "target_mode": spec["target_mode"], "waiver": None, "fix": ""}
        try:
            if not set(g.claims) & set(spec["claims"]):
                raise Skip(f"the claim ({', '.join(g.claims)}) does not select this rule")
            if rule_id in g.config["exempt_tier_skips"] and g.tier == "exempt":
                raise Skip("exempt tier (docs only)")
            outcome = RULES[rule_id](g)
        except Skip as exc:
            entry.update(status="SKIP", evidence=[str(exc)])
            g.results[rule_id] = entry
            rules.append(entry)
            continue
        problems = outcome.findings + outcome.flag_only
        status = _status_for(mode, outcome)
        if mode == "PASS":
            entry.update(status="SKIP" if problems else "PASS",
                         evidence=(["off in config (mode PASS)"] + problems) if problems else outcome.ok)
        else:
            entry.update(status=status, evidence=problems if problems else outcome.ok)
        if entry["status"] in ("FLAG", "BLOCK"):
            entry["fix"] = outcome.fix or "see evidence"
            entry["waiver"] = waivers.get(rule_id)
        g.results[rule_id] = entry
        rules.append(entry)
    return rules


def flag_block(rules: list[dict], tree: str | None, tool_sha: str, config: dict) -> tuple[str, dict]:
    counts = {"BLOCK": 0, "FLAG": 0, "PASS": 0, "SKIP": 0, "WAIVED": 0}
    lines = []
    limit = config["evidence_max_chars"]
    for entry in rules:
        if entry["status"] in ("FLAG", "BLOCK") and entry["waiver"]:
            counts["WAIVED"] += 1
            lines.append(f"- {entry['id']} WAIVED by {entry['waiver']['email']}: {_short(entry['waiver']['reason'], limit)}")
            continue
        counts[entry["status"]] += 1
        if entry["status"] in ("FLAG", "BLOCK"):
            lines.append(f"- {entry['id']} {entry['status']} {_short('; '.join(entry['evidence']), limit)} · fix: "
                         f"{_short(entry['fix'], limit)}")
    header = f"DONE-GATE: BLOCK {counts['BLOCK']} · FLAG {counts['FLAG']} · tree {(tree or 'none')[:7]} · tool {tool_sha[:7]}"
    cap = config["flag_block_max_lines"] - 1
    if len(lines) > cap:
        lines = lines[:cap - 1] + [f"- … {len(lines) - cap + 1} more in the JSON"]
    return "\n".join([header] + lines), counts


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True)
    p.add_argument("--reply")
    p.add_argument("--claim", action="append", default=[], choices=CLAIMS)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--runs", default=None)
    p.add_argument("--receipts", default=None)
    p.add_argument("--base")
    p.add_argument("--session-dir")
    p.add_argument("--touched", action="append", default=[])
    p.add_argument("--task")
    p.add_argument("--card")
    p.add_argument("--subagent-return")
    p.add_argument("--known-failure", action="append", default=[])
    p.add_argument("--open-jobs", type=int, default=0)
    p.add_argument("--temp-path", action="append", default=[])
    p.add_argument("--tier", choices=TIERS)
    p.add_argument("--strict-tdd", action="store_true")
    p.add_argument("--refactor-only", action="store_true")
    p.add_argument("--waivers", action="append", default=[])
    p.add_argument("--waive", help=argparse.SUPPRESS)
    p.add_argument("--reason", help=argparse.SUPPRESS)
    p.add_argument("--docs-caps")
    p.add_argument("--format", choices=("json", "block"), default="json")
    return p


def load_config(path: Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = config.get("rules") or {}
    if sorted(rules) != list(RULE_IDS):
        raise UsageError(f"{path}: rules must be exactly DONE-01..DONE-17")
    for rule_id, spec in rules.items():
        for key in ("mode", "target_mode"):
            if spec.get(key) not in MODES:
                raise UsageError(f"{path}: {rule_id}.{key} must be one of {', '.join(MODES)}")
        if not set(spec.get("claims") or []) <= set(CLAIMS):
            raise UsageError(f"{path}: {rule_id}.claims has an unknown class")
    return config


def run(args) -> tuple[dict, int]:
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read the config: {exc}")
    if args.reply == "-":
        reply = sys.stdin.read()
    elif args.reply:
        try:
            reply = Path(args.reply).read_text(encoding="utf-8")
        except OSError as exc:
            raise UsageError(f"cannot read --reply: {exc}")
    else:
        reply = ""
    claims = sorted(set(detect_claims(reply, config)) | set(args.claim))
    tool_sha, config_sha = _sha12(Path(__file__).resolve()), _sha12(config_path)
    base = {"schema_version": SCHEMA_VERSION, "tool": "done_check", "tool_sha": tool_sha, "config_sha": config_sha}
    if not claims:
        payload = dict(base, repo_sha=None, tree_sha=None, worktree_sha=None, repo_dirty=None, claims=[],
                       verdict="no-claim", counts={"BLOCK": 0, "FLAG": 0, "PASS": 0, "SKIP": 1, "WAIVED": 0},
                       rules=[{"id": "DONE-01", "status": "SKIP", "evidence": ["no claim in the reply"], "fix": "",
                               "mode": config["rules"]["DONE-01"]["mode"],
                               "target_mode": config["rules"]["DONE-01"]["target_mode"], "waiver": None}],
                       flag_block="DONE-GATE: no-claim")
        return payload, 0
    root = run_check.repo_root(Path(args.repo)) if Path(args.repo).is_dir() else None
    if root is None:
        raise UsageError(f"{args.repo} is not a git repo")
    args.runs = args.runs or str(run_check.default_runs_dir() / "runs.jsonl")
    args.receipts = args.receipts or os.environ.get("METODO_RDD_DIR") or str(TOOLS_ROOT / "out" / "rdd")
    args.repo = str(root)
    g = Gate(args, config, reply, claims)
    rules = evaluate(g)
    block, counts = flag_block(rules, g.fp["tree_sha"], tool_sha, config)
    verdict = "BLOCK" if counts["BLOCK"] else ("FLAG" if counts["FLAG"] else "PASS")
    payload = dict(base, repo_sha=g.fp["head_sha"], tree_sha=g.fp["tree_sha"], worktree_sha=g.fp["worktree_sha"],
                   repo_dirty=g.fp["dirty"], claims=claims, verdict=verdict, counts=counts, rules=rules, flag_block=block)
    return payload, 1 if counts["BLOCK"] else 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        if args.waive or args.reason:
            raise UsageError("--waive writes an owner waiver: that is the owner's step from their terminal, "
                             "not this tool's; pass the owner's file with --waivers")
        if args.open_jobs < 0:
            raise UsageError("--open-jobs must be >= 0")
        if not args.reply and not args.claim:
            raise UsageError("pass --reply FILE (or -) or --claim CLASS")
        payload, code = run(args)
    except UsageError as exc:
        print(f"done_check: {exc}", file=sys.stderr)
        return 2
    if args.format == "block":
        print(payload["flag_block"])
    else:
        print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
