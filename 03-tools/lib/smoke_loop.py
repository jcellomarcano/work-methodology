#!/usr/bin/env python3
"""Full-loop smoke: proves the review-receipt loop runs end to end (change
card -> receipt start -> captures -> finalize) on a THROWAWAY local clone,
and leaves machine-readable evidence the benchmark can read to accept a
kit arm.

The user's repo is only read: `git clone --no-hardlinks` copies it into a
temp dir, every smoke commit lands on the clone's `metodo-smoke` branch,
and receipts, hook ledgers and round dirs live under the same temp dir
(METODO_RDD_DIR, METODO_HOOKS_DIR). METODO_MEMORY=off keeps engram out.
Its `git status --porcelain`, HEAD and refs are compared before and after.

Scenarios, each one a commit on the clone and a receipt:
  low                    tests-only (or `What it risks: none`) change:
                         the three low-tier scripts captured -> approved.
  low-role-contract-control
                         a fresh low-tier commit whose role_contract run
                         declares a scope (--scope-glob) that excludes the
                         committed path: the real script FAILs (outside the
                         allowlist) -> rejected (negative control).
  medium                 a non-test source path, a card that risks a
                         property: scripts + generic-challenger and
                         generic-verifier FIXTURES written through
                         round_output.py -> approved.
  medium-broken-control  a fresh commit, a BROKEN finding and no judge
                         -> rejected (negative control).

Every kit piece is called through its CLI with the instance config
(METODO_PROJECT_CONFIG, else <tools-root>/config/project.json). The base
is the config's test_sectors.base_ref when it resolves in the clone and
isolates the smoke commits (no diff to the clone's HEAD); otherwise the
commit the smoke branched from.

Usage:
    lib/smoke_loop.py <repo> [--tools <tools-root>] [--keep] [--out <file>]

Output: the report on stdout and in --out (default
<tools-root>/out/smoke/<repo_sha>.json): sorted keys, no timestamps, no
absolute paths. Exit 0 PASS, 1 FAIL, 2 usage (not a git repo, no commits,
or an --out inside the repo that git does not ignore).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, rdd_risk  # noqa: E402
from lib import change_card_validator as ccv  # noqa: E402
from lib import role_contract_validator as rcv  # noqa: E402

SCHEMA_VERSION = "1.0.0"
SMOKE_BRANCH = "metodo-smoke"
SMOKE_DATE = "2026-01-01T00:00:00+0000"
SMOKE_IDENTITY = {
    "GIT_AUTHOR_NAME": "metodo-smoke", "GIT_AUTHOR_EMAIL": "smoke@metodo.invalid", "GIT_AUTHOR_DATE": SMOKE_DATE,
    "GIT_COMMITTER_NAME": "metodo-smoke", "GIT_COMMITTER_EMAIL": "smoke@metodo.invalid", "GIT_COMMITTER_DATE": SMOKE_DATE,
}
# Inherited git variables that would point the smoke's git calls elsewhere.
GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
LOW_SCRIPTS = ("script:role_contract", "script:comment_gate", "script:docs_lint")
NA_PROPERTIES = frozenset({"Auditabilidad", "Auditability", "UX"})
PROBE_NAME = "metodo_smoke_probe.txt"
# A scope no smoke path matches: role_contract finds the committed path outside it.
OUT_OF_SCOPE_GLOB = "metodo_smoke_declared_scope/**"
NOT_MEASURED = (
    "medium scenarios: generic-challenger and generic-verifier outputs are FIXTURES written through round_output.py "
    "(wiring proof, not agent quality); no agent ran",
    "high tier: owner consent, two adversaries on opus and generic-judge are not exercised",
    "script verdicts: finalize rejects on a role_contract FAIL or a docs_lint offender; comment_gate emits facts, "
    "not a verdict, so no scenario proves a comment is judged (that is the generic-comment-gate agent's call)",
    "low-role-contract-control: the role_contract FAIL is real script output, provoked by a deliberately mis-declared "
    "scope glob, not by a contract-forbidden path",
    "docs_lint ran over the throwaway clone with the instance caps, not over the docs_root the caps file names",
    "verify_sectors / verify_commit batteries and test_sectors full_required are not run",
    "harness hooks (push/PR gate, output validation on close, response lint) and the MCP transport are not exercised: "
    "the smoke calls the CLIs directly",
)


class UsageError(Exception):
    pass


# ----------------------------------------------------------------------------- git helpers

def _clean_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    env.update(extra or {})
    return env


def _git(repo: Path, *args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
                          env=env if env is not None else _clean_env())


def resolve_repo(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_dir():
        raise UsageError(f"not a directory: {path}")
    top = _git(candidate, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or not top.stdout.strip():
        raise UsageError(f"not a git repository: {path}")
    repo = Path(top.stdout.strip()).resolve()
    if _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False).returncode != 0:
        raise UsageError(f"the repository has no commits: {path}")
    return repo


def snapshot(repo: Path) -> dict:
    """Read-only view of the user's repo. --no-optional-locks keeps `git
    status` from refreshing (writing) the index."""
    return {
        "status": _git(repo, "--no-optional-locks", "status", "--porcelain").stdout,
        "head": _git(repo, "rev-parse", "HEAD").stdout.strip(),
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
    }


def tool_sha(tools: Path) -> str | None:
    proc = _git(tools, "rev-parse", "HEAD", check=False)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ----------------------------------------------------------------------------- config-derived choices

def config_path_for(tools: Path) -> Path:
    return Path(os.environ.get("METODO_PROJECT_CONFIG") or tools / "config" / "project.json").expanduser()


def _concretize(glob: str) -> str | None:
    if "[" in glob:
        return None
    path = glob
    if path.startswith("**/"):
        path = "metodo_smoke/" + path[3:]
    path = path.replace("/**/", "/metodo_smoke/")
    if path.endswith("/**") or path == "**":
        path = path[:-2] + PROBE_NAME
    path = path.replace("**", "metodo_smoke").replace("*", "metodo_smoke").replace("?", "x").lstrip("/")
    return path or None


def _risky(path: str, config: dict) -> bool:
    shared = [p for p in rcv.always_forbidden_patterns(config) if ".claude" not in p]
    critical = baseline.critical_paths(config)
    full = list((config.get("test_sectors") or {}).get("full_required_globs") or [])
    return (rdd_risk.matches_any(path, shared + full + list(rcv.ALWAYS_FORBIDDEN_CLAUDE_GLOBS))
            or any(path.startswith(m) for m in critical))


def low_path(config: dict, clone: Path) -> str | None:
    """A concrete path that matches one of rdd.tests_globs and none of the
    exempt, shared-build, critical-path or full-required globs: a tests-only change."""
    rdd = rdd_risk.rdd_config(config)
    for glob in rdd["tests_globs"]:
        path = _concretize(glob)
        if (path and rdd_risk.glob_match(path, glob) and not rdd_risk.matches_any(path, rdd["exempt_globs"])
                and not _risky(path, config) and not (clone / path).is_dir()):
            return path
    return None


def source_path(config: dict, clone: Path) -> str:
    """A non-test, non-exempt path that no high-tier rule matches."""
    rdd = rdd_risk.rdd_config(config)
    skip = list(rdd["exempt_globs"]) + list(rdd["tests_globs"])
    for path in ("metodo_smoke/" + PROBE_NAME, PROBE_NAME, "metodo_smoke_probe/" + PROBE_NAME, "metodo_smoke.probe"):
        if not rdd_risk.matches_any(path, skip) and not _risky(path, config) and not (clone / path).is_dir():
            return path
    raise UsageError("no smoke source path escapes the config's exempt/tests/shared-build globs")


def card_property(config: dict) -> str:
    order, critical = ccv.properties_from_config(config)
    configured = list(config.get("property_order") or sorted(order))
    calm = [p for p in configured if p not in critical]
    for preferred in ("UX", "Auditability", "Auditabilidad"):
        if preferred in calm:
            return preferred
    return calm[0] if calm else configured[0]


def card_invariant(config: dict, prop: str) -> str:
    if prop in NA_PROPERTIES:
        return "n/a"
    extra = list(ccv.extra_invariant_tokens_from_config(config))
    return extra[0] if extra else f"{ccv.invariant_prefix_from_config(config)}-01"


def change_card(config: dict, path: str, risks_property: bool) -> str:
    prop = card_property(config)
    risks = f"{prop}, a probe file in a throwaway clone [Inferred]" if risks_property else "none [Measured]"
    return "\n".join([
        "## Change card",
        f"**Why**: the kit smoke needs a committed candidate at {path} to drive the receipt loop [Measured]",
        f"**For what**: {prop} [Inferred]",
        f"**What it risks**: {risks}",
        "**When**: kit init smoke, before the benchmark accepts a kit arm [Measured]",
        f"**How**: one commit on the {SMOKE_BRANCH} branch of a throwaway clone [Measured]",
        "**How far**: never touches the user's repo; undone by deleting the temporary clone [Measured]",
        "**How we'll know**: the receipt finalize verdict read by smoke_loop.py [Tested]",
        f"**Invariant**: {card_invariant(config, prop)}",
        "**Ticket**: no ticket",
        "",
    ])


def challenger_doc(scenario: str, path: str, lens: str, verdict: str) -> dict:
    broken = verdict == "BROKEN"
    return {
        "round": f"smoke-{scenario}",
        "role": "generic-challenger",
        "summary": "FIXTURE: wiring proof written by smoke_loop.py, not an agent output",
        "findings": [{
            "id": "F-01",
            "lens": lens,
            "claim": f"{path} is an inert probe file with no caller",
            "attack": "look for a caller that loads the probe",
            "failure_scenario": ("negative control: a BROKEN finding with no judge must reject the receipt" if broken
                                 else "none found: nothing loads the probe"),
            "evidence": [path],
            "verdict": verdict,
            "epistemic": "Inferred",
            "simpler_alternative": "none",
        }],
        "not_covered": ["FIXTURE: no agent ran"],
    }


def verifier_doc(scenario: str) -> dict:
    return {
        "change_card_id": f"metodo-smoke-{scenario}",
        "battery": ["fixture"],
        "commands_executed": [],
        "verdict": "PASS",
        "evidence": ["FIXTURE: no battery ran; wiring proof written by smoke_loop.py"],
        "not_covered": ["verify_sectors"],
    }


# ----------------------------------------------------------------------------- the run

class Smoke:
    def __init__(self, repo: Path, tools: Path, tmp: Path):
        self.repo = repo
        self.tools = tools
        self.tmp = tmp
        self.clone = tmp / "clone"
        self.config_path = config_path_for(tools)
        self.config = baseline.load_json(self.config_path) if self.config_path.exists() else {}
        self.paths_touched: list[str] = []
        (tmp / "rdd").mkdir()
        (tmp / "hooks").mkdir()
        (tmp / "nohooks").mkdir()
        (tmp / "cards").mkdir()
        (tmp / "fixtures").mkdir()
        (tmp / "gitconfig").write_text("", encoding="utf-8")
        self.env = _clean_env({
            "METODO_MEMORY": "off",
            "METODO_RDD_DIR": str(tmp / "rdd"),
            "METODO_HOOKS_DIR": str(tmp / "hooks"),
            "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            **SMOKE_IDENTITY,
        })
        if self.config_path.exists():
            self.env["METODO_PROJECT_CONFIG"] = str(self.config_path)
        self.base = ""
        self.base_source = ""

    # -- plumbing

    def _config_args(self) -> list[str]:
        return ["--config", str(self.config_path)] if self.config_path.exists() else []

    def _py(self, name: str, *args: str) -> list[str]:
        return [sys.executable, str(self.tools / "lib" / name), *args]

    def _run(self, argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(argv, capture_output=True, text=True, env=self.env, input=stdin, cwd=str(self.tmp))

    def _git_clone(self, *args: str) -> subprocess.CompletedProcess:
        return self._run(["git", "-c", f"core.hooksPath={self.tmp / 'nohooks'}", "-c", "commit.gpgsign=false",
                          "-C", str(self.clone), *args])

    @staticmethod
    def _json(proc: subprocess.CompletedProcess):
        try:
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

    # -- setup

    def prepare(self) -> list[dict]:
        steps = []
        proc = self._run(["git", "-c", f"core.hooksPath={self.tmp / 'nohooks'}", "clone", "--quiet", "--no-hardlinks",
                          str(self.repo), str(self.clone)])
        steps.append({"step": "clone", "exit_code": proc.returncode, "ok": proc.returncode == 0})
        if proc.returncode != 0:
            return steps
        proc = self._git_clone("checkout", "--quiet", "-b", SMOKE_BRANCH)
        steps.append({"step": f"branch {SMOKE_BRANCH}", "exit_code": proc.returncode, "ok": proc.returncode == 0})
        self.base, self.base_source = self._pick_base()
        return steps

    def _pick_base(self) -> tuple[str, str]:
        start = self._git_clone("rev-parse", "HEAD").stdout.strip()
        ref = ((self.config.get("test_sectors") or {}).get("base_ref") or "").strip()
        if ref and self._git_clone("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0:
            diff = self._git_clone("diff", "--name-only", f"{ref}...HEAD")
            if diff.returncode == 0 and not diff.stdout.strip():
                return ref, "config:test_sectors.base_ref"
        return start, "smoke-parent"

    # -- one scenario

    def commit(self, path: str, line: str, message: str) -> dict:
        target = self.clone / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if path not in self.paths_touched:
            self.paths_touched.append(path)
        add = self._git_clone("add", "--", path)
        if add.returncode != 0:
            return {"step": "commit", "exit_code": add.returncode, "ok": False}
        proc = self._git_clone("commit", "--quiet", "--no-verify", "-m", message)
        return {"step": "commit", "exit_code": proc.returncode, "ok": proc.returncode == 0}

    def scripts(self, round_dir: Path, declared_scope: list[str] | None = None) -> list[tuple[str, list[str]]]:
        contract = self.tools.parent / "01-roles" / "agents" / "generic-proposer.contract.json"
        if not contract.exists():
            contract = self.clone / ".claude" / "agents" / "generic-proposer.contract.json"
        caps_src = self.tools / "config" / "docs-caps.json"
        caps = (baseline.load_json(caps_src).get("caps") or {}) if caps_src.exists() else {}
        caps_file = round_dir.parent / f"{round_dir.name}-docs-caps.json"
        baseline.write_json(caps_file, {"docs_root": str(self.clone), "caps": caps})
        rng = f"{self.base}..HEAD"
        globs = self.paths_touched if declared_scope is None else declared_scope
        scope = [x for p in globs for x in ("--scope-glob", p)]
        return [
            ("script:role_contract", self._py("role_contract_validator.py", "--contract", str(contract), "--repo", str(self.clone),
                                              "--range", rng, *scope, *self._config_args())),
            ("script:comment_gate", self._py("comment_gate.py", "--repo", str(self.clone), "--range", rng, *self._config_args())),
            ("script:docs_lint", self._py("docs_lint.py", str(caps_file))),
        ]

    def scenario(self, name: str, tier: str, expected: str, path: str, risks_property: bool, finding: str | None,
                 declared_scope: list[str] | None = None) -> dict:
        result = {"name": name, "tier": None, "expected_verdict": expected, "verdict": None, "steps": [], "pass": False}
        steps = result["steps"]
        round_dir = self.tmp / "rounds" / name
        round_dir.mkdir(parents=True)

        def done() -> dict:
            result["pass"] = (all(s["ok"] for s in steps) and result["tier"] == tier and result["verdict"] == expected)
            return result

        steps.append(self.commit(path, f"metodo smoke probe: {name}", f"chore: metodo smoke {name}"))
        if not steps[-1]["ok"]:
            return done()

        card = self.tmp / "cards" / f"{name}.md"
        card.write_text(change_card(self.config, path, risks_property), encoding="utf-8")
        proc = self._run(self._py("change_card_validator.py", *self._config_args(), str(card)))
        steps.append({"step": "change_card_validate", "exit_code": proc.returncode, "ok": proc.returncode == 0})
        if not steps[-1]["ok"]:
            return done()

        proc = self._run(self._py("rdd_receipt.py", *self._config_args(), "start", "--repo", str(self.clone), "--base", self.base,
                                  "--round-dir", str(round_dir), "--change-card", str(card)))
        receipt = self._json(proc) or {}
        result["tier"] = (receipt.get("risk") or {}).get("tier")
        steps.append({"step": "receipt_start", "exit_code": proc.returncode, "ok": proc.returncode == 0 and result["tier"] == tier})
        if not steps[-1]["ok"]:
            return done()
        tree = receipt["tree_sha"]

        artifacts: list[tuple[str, Path]] = []
        for role, argv in self.scripts(round_dir, declared_scope):
            proc = self._run(argv)
            parsed = self._json(proc)
            ok = proc.returncode in (0, 1) and isinstance(parsed, dict)
            steps.append({"step": role, "exit_code": proc.returncode, "ok": ok})
            if not ok:
                return done()
            artifact = round_dir / f"{role.replace(':', '-')}.json"
            artifact.write_text(proc.stdout, encoding="utf-8")
            artifacts.append((role, artifact))

        if finding is not None:
            lens = (receipt.get("risk") or {}).get("lens_focus") or "simplicidad"
            for role, doc in (("generic-challenger", challenger_doc(name, path, lens, finding)),
                              ("generic-verifier", verifier_doc(name))):
                fixture = self.tmp / "fixtures" / f"{name}-{role}.json"
                baseline.write_json(fixture, doc)
                proc = self._run(self._py("round_output.py", "--round-dir", str(round_dir), "--role", role, "--document", str(fixture),
                                          "--repo", str(self.clone), *self._config_args()))
                written = self._json(proc) or {}
                ok = proc.returncode == 0 and written.get("verdict") == "PASS" and bool(written.get("path"))
                steps.append({"step": f"output_write {role}", "exit_code": proc.returncode, "ok": ok})
                if not ok:
                    return done()
                artifacts.append((role, round_dir / Path(written["path"]).name))

        for role, artifact in artifacts:
            proc = self._run(self._py("rdd_receipt.py", *self._config_args(), "capture", "--tree", tree, "--role", role,
                                      "--file", str(artifact), "--repo", str(self.clone)))
            steps.append({"step": f"capture {role}", "exit_code": proc.returncode, "ok": proc.returncode == 0})
            if not steps[-1]["ok"]:
                return done()

        proc = self._run(self._py("rdd_receipt.py", *self._config_args(), "finalize", "--tree", tree))
        result["verdict"] = (self._json(proc) or {}).get("verdict")
        steps.append({"step": "finalize", "exit_code": proc.returncode,
                      "ok": proc.returncode in (0, 1) and result["verdict"] == expected})
        return done()

    def run(self) -> tuple[list[dict], list[dict]]:
        setup = self.prepare()
        if not all(s["ok"] for s in setup):
            return setup, []
        low = low_path(self.config, self.clone)
        src = source_path(self.config, self.clone)
        scenarios = [
            self.scenario("low", "low", "approved", low or src, False, None),
            self.scenario("low-role-contract-control", "low", "rejected", low or src, False, None,
                          declared_scope=[OUT_OF_SCOPE_GLOB]),
            self.scenario("medium", "medium", "approved", src, True, "OK"),
            self.scenario("medium-broken-control", "medium", "rejected", src, True, "BROKEN"),
        ]
        return setup, scenarios


def build_report(tools: Path, before: dict, after: dict, base_source: str, setup: list[dict], scenarios: list[dict]) -> dict:
    sha = tool_sha(tools)
    not_measured = list(NOT_MEASURED)
    if sha is None:
        not_measured.append("tool_sha: the tools root is not a git repository")
    loop_ran = bool(scenarios) and all(s["pass"] for s in scenarios)
    untouched = before == after
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool_sha": sha,
        "repo_sha": before["head"],
        "base_source": base_source or None,
        "setup": setup,
        "scenarios": scenarios,
        "not_measured": not_measured,
        "user_repo_untouched": untouched,
        "loop_ran": loop_ran,
        "verdict": "PASS" if loop_ran and untouched else "FAIL",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("--tools", default=None, help="tools root (default: this kit's 03-tools)")
    parser.add_argument("--keep", action="store_true", help="keep the temp dir and print its path on stderr")
    parser.add_argument("--out", default=None, help="report path (default <tools-root>/out/smoke/<repo_sha>.json)")
    args = parser.parse_args(argv)

    try:
        repo = resolve_repo(args.repo)
        tools = Path(args.tools).expanduser().resolve() if args.tools else TOOLS_ROOT
        if not (tools / "lib" / "rdd_receipt.py").exists():
            raise UsageError(f"not a tools root (no lib/rdd_receipt.py): {args.tools}")
        before = snapshot(repo)
        out = Path(args.out).expanduser() if args.out else tools / "out" / "smoke" / f"{before['head']}.json"
        if _inside(out, repo) and _git(repo, "check-ignore", "-q", str(out.resolve()), check=False).returncode != 0:
            raise UsageError("--out lands inside the repo on a path git does not ignore: the smoke never writes into the user's repo")
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="metodo-smoke-"))
    code = None
    try:
        smoke = Smoke(repo, tools, tmp)
        setup, scenarios = smoke.run()
        base_source = smoke.base_source
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        code = 2
    finally:
        if args.keep:
            print(f"kept: {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    if code is not None:
        return code

    report = build_report(tools, before, snapshot(repo), base_source, setup, scenarios)
    baseline.write_json(out, report)
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
