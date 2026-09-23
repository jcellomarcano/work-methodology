"""The `metodo` MCP server's tool table: one entry per kit script an agent
might need, with its strict inputSchema (additionalProperties: false) and
the exact argv that gets run. A literal tuple on purpose: nothing is
discovered by scanning directories.
"""
from __future__ import annotations

import re
from pathlib import Path

from mcp import registry
from mcp.registry import Ctx, ToolSpec

S = {"type": "string"}
B = {"type": "boolean"}
I = {"type": "integer"}
A = {"type": "array", "items": S}
ROLE_ENUM = {"type": "string", "enum": [r[len("generic-"):] for r in registry.round_files.ROLES]}
SCHEMA_ENUM = {"type": "string", "enum": list(registry.round_files.SCHEMA_NAMES)}
SCRIPT_ROLE_ENUM = {"type": "string", "enum": ROLE_ENUM["enum"] + [
    "script:role_contract", "script:comment_gate", "script:docs_lint", "script:metrics", "script:dep_boundaries",
    "script:test_sectors", "script:verify_sectors", "script:verify_commit", "script:benchmark", "script:cartography"]}
DECISION_ENUM = {"type": "string", "enum": ["consent", "push-without-receipt", "accept-escalation", "unreviewed"]}
REPLY_TYPE_ENUM = {"type": "string", "enum": ["pregunta", "estado", "decision", "fallo", "investigacion", "aclaracion"]}
LANG_ENUM = {"type": "string", "enum": ["es", "en", "ca", "de"]}
AUDIENCE_ENUM = {"type": "string", "enum": ["public", "owner"]}


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _repo(args: dict, ctx: Ctx) -> str:
    return str(registry.resolve_repo(args, ctx))


def _py(ctx: Ctx, name: str) -> list[str]:
    return ["python3", str(ctx.tools_root / "lib" / name)]


def _sh(ctx: Ctx, name: str) -> list[str]:
    return ["bash", str(ctx.tools_root / "bin" / name)]


def _project_config(ctx: Ctx) -> str:
    return str(ctx.tools_root / "config" / "project.json")


def _out(ctx: Ctx, sha: str, name: str) -> Path:
    return ctx.out_dir / sha / name


def _one_of(args: dict, *keys: str) -> None:
    present = [k for k in keys if args.get(k) not in (None, "")]
    if len(present) != 1:
        raise registry.ToolError(f"pass exactly one of {', '.join(keys)}")


def _range_or_worktree(args: dict) -> list[str]:
    _one_of(args, "range", "worktree")
    return ["--range", args["range"]] if args.get("range") else ["--worktree", args["worktree"]]


def _scope_globs(args: dict) -> list[str]:
    out: list[str] = []
    for glob in args.get("scope_globs") or []:
        out += ["--scope-glob", glob]
    return out


# --------------------------------------------------------------------------- change card

def _card_argv(extract: bool):
    def argv(args, ctx):
        _one_of(args, "card_path", "card_text")
        source = args["card_path"] if args.get("card_path") else "-"
        return _py(ctx, "change_card_validator.py") + ["--config", _project_config(ctx)] + (["--extract"] if extract else []) + [source]
    return argv


def _card_stdin(args):
    return args.get("card_text")


# --------------------------------------------------------------------------- receipt

def _receipt(sub: str, *flags):
    def argv(args, ctx):
        cmd = _py(ctx, "rdd_receipt.py") + ["--config", _project_config(ctx), sub]
        for flag, key, kind in flags:
            value = args.get(key)
            if kind == "repo":
                try:
                    cmd += [flag, _repo(args, ctx)]
                except registry.ToolError:
                    if sub in ("start", "status"):
                        raise
                continue
            if value in (None, "", [], False):
                continue
            if kind == "list":
                for item in value:
                    cmd += [flag, item]
            elif kind == "flag":
                cmd += [flag]
            else:
                cmd += [flag, str(value)]
        if sub == "start" and "--base" not in cmd:
            cmd += ["--base", (ctx.project_config.get("test_sectors") or {}).get("base_ref") or "origin/develop"]
        return cmd
    return argv


# --------------------------------------------------------------------------- reply lint (two scripts)

def _reply_lint(args: dict, ctx: Ctx) -> dict:
    lint_argv = _py(ctx, "output_lint.py") + [args["reply_path"], "--type", args["type"], "--lang", args["lang"],
                                                "--audience", args["audience"]]
    for rule in args.get("allow") or []:
        lint_argv += ["--allow", rule]
    cite_argv = _py(ctx, "cite_check.py") + [args["reply_path"]]
    if args.get("repo") or ctx.repo is not None:
        cite_argv += ["--repo", _repo(args, ctx)]
    if args.get("online"):
        cite_argv += ["--online"]
    lint_spec = ToolSpec("output_lint", "", {}, argv=lambda a, c: lint_argv, ok_exit=frozenset({0, 1}))
    cite_spec = ToolSpec("cite_check", "", {}, argv=lambda a, c: cite_argv, ok_exit=frozenset({0, 1}))
    lint, lint_err = registry.run_passthrough(lint_spec, args, ctx)
    cite, cite_err = registry.run_passthrough(cite_spec, args, ctx)
    if lint_err or cite_err:
        raise registry.ToolError(f"output_lint: {lint.get('error') if lint_err else 'ok'}; cite_check: {cite.get('error') if cite_err else 'ok'}")
    return {"output_lint": lint, "cite_check": cite}


def _sanitize_range(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", value.replace("/", "_").replace(":", "_").replace(" ", "_"))


def _short(repo: str, ref: str) -> str:
    import subprocess
    out = subprocess.run(["git", "-C", repo, "rev-parse", "--short=7", f"{ref}^{{commit}}"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ref


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("change_card_validate", "Validate a change card (9 fields, epistemic tags) and return its review lane (opus|sonnet).",
             _obj({"card_path": S, "card_text": S, "repo": S}), argv=_card_argv(False), stdin=_card_stdin,
             ok_exit=frozenset({0, 1}), timeout_s=30, roles=("proposer", "judge")),
    ToolSpec("change_card_extract", "Read a change card best-effort (never fails); for commit bodies and drafts.",
             _obj({"card_path": S, "card_text": S, "repo": S}), argv=_card_argv(True), stdin=_card_stdin, timeout_s=30),
    ToolSpec("shape_metrics", "Kotlin shape metrics per module (files, functions, lengths); heuristic, labelled Inferido.",
             _obj({"repo": S, "modules": A}),
             argv=lambda a, c: _py(c, "shape_metrics.py") + [_repo(a, c)] + (["--modules", ",".join(a["modules"])] if a.get("modules") else []),
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "metrics.json"), timeout_s=120, roles=("cartographer",)),
    ToolSpec("duplication", "Copy-paste clusters via PMD CPD with the calibrated threshold in config/cpd.json.",
             _obj({"repo": S, "files": A}),
             argv=lambda a, c: _py(c, "duplication_cpd.py") + [_repo(a, c)] + (["--files", ",".join(a["files"])] if a.get("files") else []),
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "duplication.json"), timeout_s=120, roles=("cartographer",)),
    ToolSpec("dep_boundaries", "Module boundary graph from real imports: violations and cycle candidates.",
             _obj({"repo": S}), argv=lambda a, c: _py(c, "dep_boundaries.py") + [_repo(a, c)],
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "deps.json"), timeout_s=120,
             roles=("cartographer", "boundary-reviewer")),
    ToolSpec("domain_invariants", "Presence (not proof) of the mechanisms behind each declared invariant, with file:line evidence.",
             _obj({"repo": S}),
             argv=lambda a, c: _py(c, "domain_invariants.py") + [_repo(a, c), "--project-config", _project_config(c)],
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "domain-invariants.json"), timeout_s=120),
    ToolSpec("cartography", "Repo map: shape summary, boundaries, 90-day hotspots, merge-tree conflicts vs the integration branch.",
             _obj({"repo": S}), argv=lambda a, c: _sh(c, "cartography.sh") + [_repo(a, c)],
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "cartography.json"), timeout_s=300, roles=("cartographer",)),
    ToolSpec("clean_pass", "Union of flagged rows (long files, long functions, var/lateinit, duplication, boundaries); proposes nothing.",
             _obj({"repo": S}), argv=lambda a, c: _sh(c, "clean-pass.sh") + [_repo(a, c)],
             mode="outfile", outfile=lambda a, c, sha: _out(c, sha, "clean-pass.json"), timeout_s=300),
    ToolSpec("metrics_delta", "shape_metrics + duplication and the delta against baselines/latest (job; exit 2 = tool drift, VOID).",
             _obj({"repo": S}), argv=lambda a, c: _sh(c, "metrics.sh") + [_repo(a, c)], mode="job",
             summary=lambda a, c, rid: [_out(c, registry.repo_sha(registry.resolve_repo(a, c)), "delta.json"),
                                        _out(c, registry.repo_sha(registry.resolve_repo(a, c)), "metrics.json")]),
    ToolSpec("benchmark_release", "Static benchmark between two refs (job): what improved, what got worse, what was not measured.",
             _obj({"repo": S, "ref_a": S, "ref_b": S, "force_recompute": B}, ("ref_a", "ref_b")),
             argv=lambda a, c: _sh(c, "benchmark-release.sh") + [_repo(a, c), a["ref_a"], a["ref_b"]] + (["--force-recompute"] if a.get("force_recompute") else []),
             mode="job",
             summary=lambda a, c, rid: [c.out_dir / "benchmark" / f"{_short(_repo(a, c), a['ref_a'])}..{_short(_repo(a, c), a['ref_b'])}.json"]),
    ToolSpec("role_contract_validate", "Check a range or worktree against a role contract: forbidden paths and may_write/scope globs.",
             _obj({"repo": S, "role": ROLE_ENUM, "range": S, "worktree": S, "scope_globs": A}, ("role",)),
             argv=lambda a, c: _py(c, "role_contract_validator.py") + ["--contract", str(registry.contract_path(a["role"], c)),
                                                                        "--repo", _repo(a, c)] + _range_or_worktree(a) + _scope_globs(a) + ["--config", _project_config(c)],
             ok_exit=frozenset({0, 1}), roles=("proposer", "mechanic")),
    ToolSpec("output_validate", "Validate a JSON document against one of the kit schemas (PASS / INCOMPLETE / FAIL).",
             _obj({"document_path": S, "schema": SCHEMA_ENUM}, ("document_path", "schema")),
             argv=lambda a, c: _py(c, "findings_schema_validator.py") + [a["document_path"], "--schema", str(registry.round_files.schema_path(a["schema"]))],
             ok_exit=frozenset({0, 1}), timeout_s=30),
    ToolSpec("output_write", "Validate your output against your role's schema and write it as NNN-<role>-<schema>.json in the round dir. FAIL writes nothing.",
             _obj({"round_dir": S, "role": ROLE_ENUM, "schema": SCHEMA_ENUM, "document": {"type": "object"}, "repo": S}, ("round_dir", "role", "document")),
             argv=lambda a, c: _py(c, "round_output.py") + ["--round-dir", a["round_dir"], "--role", a["role"], "--document", "-",
                                                             "--config", _project_config(c)] + (["--schema", a["schema"]] if a.get("schema") else [])
                                                             + (["--repo", str(c.repo)] if c.repo else []),
             stdin=lambda a: registry.json.dumps(a["document"], ensure_ascii=False), ok_exit=frozenset({0, 1}), timeout_s=30,
             roles=tuple(ROLE_ENUM["enum"])),
    ToolSpec("handoff_write", "Write the numbered handoff to the next role; repo_sha and tools_sha are filled by the script.",
             _obj({"repo": S, "round_dir": S, "from_role": ROLE_ENUM, "to_role": ROLE_ENUM, "topic": S, "artifact_path": S,
                   "summary": S, "residual_risks": A, "truncated": B, "not_covered": A},
                  ("round_dir", "from_role", "to_role", "topic", "artifact_path", "summary", "residual_risks")),
             argv=lambda a, c: _py(c, "handoff.py") + ["--repo", _repo(a, c), "--round-dir", a["round_dir"], "--from-role", a["from_role"],
                                                       "--to-role", a["to_role"], "--topic", a["topic"], "--artifact", a["artifact_path"],
                                                       "--summary", a["summary"], "--config", _project_config(c)]
                               + [x for r in a["residual_risks"] for x in ("--residual-risk", r)]
                               + (["--truncated"] if a.get("truncated") else [])
                               + [x for n in (a.get("not_covered") or []) for x in ("--not-covered", n)],
             timeout_s=30, roles=("cartographer", "proposer", "challenger", "blind-spot-adversary", "judge", "verifier", "comment-gate", "mechanic")),
    ToolSpec("comment_gate_measure", "List and measure every comment a range or worktree adds (DOC-001 facts, no verdicts).",
             _obj({"repo": S, "range": S, "worktree": S, "scope_globs": A}),
             argv=lambda a, c: _py(c, "comment_gate.py") + ["--repo", _repo(a, c)] + _range_or_worktree(a) + _scope_globs(a),
             roles=("proposer",)),
    ToolSpec("comment_gate_verify", "Prove that a fix range changed only comments and left no NEEDS-COMMENT marker.",
             _obj({"repo": S, "verify_range": S, "range": S}, ("verify_range",)),
             argv=lambda a, c: _py(c, "comment_gate.py") + ["--repo", _repo(a, c), "--verify", a["verify_range"]] + (["--range", a["range"]] if a.get("range") else []),
             ok_exit=frozenset({0, 1}), roles=("mechanic",)),
    ToolSpec("docs_lint", "Check every kit document against its line cap (config/docs-caps.json).",
             _obj({}), argv=lambda a, c: _py(c, "docs_lint.py") + [str(c.tools_root / "config" / "docs-caps.json")],
             ok_exit=frozenset({0, 1}), timeout_s=30),
    ToolSpec("reply_lint", "Lint a human-facing reply: COM-01..18 form rules (output_lint) and COM-19 citations (cite_check).",
             _obj({"reply_path": S, "type": REPLY_TYPE_ENUM, "lang": LANG_ENUM, "audience": AUDIENCE_ENUM, "allow": A, "repo": S, "online": B},
                  ("reply_path", "type", "lang", "audience")),
             mode="internal", handler=_reply_lint),
    ToolSpec("pr_scope", "Separate the files a PR really changes from base-branch drift (three-dot vs two-dot diff).",
             _obj({"repo": S, "base": S, "head": S}, ("base",)),
             argv=lambda a, c: _py(c, "pr_scope.py") + ["--repo", _repo(a, c), "--base", a["base"], "--head", a.get("head") or "HEAD"]),
    ToolSpec("review_comment_lint", "Check a review comment against RC-01..RC-07 (four parts, caps, file:line, no filler).",
             _obj({"comment_path": S, "scope_path": S, "lang": {"type": "string", "enum": ["es", "en"]}}, ("comment_path",)),
             argv=lambda a, c: _py(c, "review_comment_lint.py") + [a["comment_path"]] + (["--scope", a["scope_path"]] if a.get("scope_path") else [])
                               + (["--lang", a["lang"]] if a.get("lang") else []),
             ok_exit=frozenset({0, 1}), timeout_s=30),
    ToolSpec("test_sectors", "Gradle tasks of the modules a change touches, or full_required when there is no shortcut.",
             _obj({"repo": S, "base": S, "committed_only": B}),
             argv=lambda a, c: _py(c, "test_sectors.py") + [_repo(a, c), "--config", _project_config(c)] + (["--base", a["base"]] if a.get("base") else [])
                               + (["--committed-only"] if a.get("committed_only") else []),
             timeout_s=30, roles=("proposer", "verifier")),
    ToolSpec("verify_sectors", "Run only the sector tasks under the Gradle lock (job); poll with job_status.",
             _obj({"repo": S, "base": S, "tasks": A, "committed_only": B}),
             argv=lambda a, c: _sh(c, "verify-sectors.sh") + [_repo(a, c), "--config", _project_config(c), "--run-id", a["_run_id"]]
                               + (["--base", a["base"]] if a.get("base") else []) + (["--tasks", ",".join(a["tasks"])] if a.get("tasks") else [])
                               + (["--committed-only"] if a.get("committed_only") else []),
             mode="job",
             summary=lambda a, c, rid: [c.out_dir / "verify-sectors" / registry.repo_sha(registry.resolve_repo(a, c)) / rid / "summary.json",
                                        c.out_dir / "verify-sectors" / (registry.repo_sha(registry.resolve_repo(a, c)) + "-dirty") / rid / "summary.json"],
             roles=("proposer", "verifier", "mechanic")),
    ToolSpec("verify_commit", "Run the repo battery commit by commit over a range, each in a disposable worktree (job).",
             _obj({"repo": S, "range": S, "full": B}, ("range",)),
             argv=lambda a, c: _sh(c, "verify-commit.sh") + [_repo(a, c), a["range"]] + (["--full"] if a.get("full") else []),
             mode="job", summary=lambda a, c, rid: [c.out_dir / "verify" / f"{_sanitize_range(a['range'])}.json"], roles=("verifier",)),
    ToolSpec("job_status", "Status of a background job: running|done, exit code, its summary JSON when done, log tail.",
             _obj({"run_id": S, "wait_seconds": I}, ("run_id",)), mode="internal", handler=registry.job_status,
             roles=("proposer", "verifier", "mechanic")),
    ToolSpec("receipt_start", "Open a review receipt bound to HEAD^{tree}: tier, lenses, budget and change card frozen.",
             _obj({"repo": S, "round_dir": S, "base": S, "change_card_path": S, "scope_globs": A, "supersedes": S, "inherit_from": S}, ("round_dir",)),
             argv=_receipt("start", ("--repo", "repo", "repo"), ("--base", "base", "str"), ("--round-dir", "round_dir", "str"),
                           ("--change-card", "change_card_path", "str"), ("--scope-glob", "scope_globs", "list"),
                           ("--supersedes", "supersedes", "str"), ("--inherit-from", "inherit_from", "str")),
             ok_exit=frozenset({0, 2, 3})),
    ToolSpec("receipt_status", "Receipt for the current tree, next step, open receipts; risk preview when base is given.",
             _obj({"repo": S, "base": S, "change_card_path": S}),
             argv=_receipt("status", ("--repo", "repo", "repo"), ("--base", "base", "str"), ("--change-card", "change_card_path", "str")),
             roles=("verifier",)),
    ToolSpec("receipt_capture", "Bind an artifact to the receipt (schema-validated, sha256); optional handoff to the next role.",
             _obj({"repo": S, "tree": S, "role": SCRIPT_ROLE_ENUM, "artifact_path": S, "handoff_to": ROLE_ENUM, "summary": S}, ("tree", "role", "artifact_path")),
             argv=_receipt("capture", ("--tree", "tree", "str"), ("--role", "role", "str"), ("--file", "artifact_path", "str"),
                           ("--repo", "repo", "repo"), ("--handoff-to", "handoff_to", "str"), ("--summary", "summary", "str")),
             ok_exit=frozenset({0, 1, 2, 3}), roles=("verifier",)),
    ToolSpec("receipt_finalize", "Close the receipt from its captures only: approved | rejected | escalated | inconclusive.",
             _obj({"tree": S}, ("tree",)), argv=_receipt("finalize", ("--tree", "tree", "str")), ok_exit=frozenset({0, 1, 2, 3})),
    ToolSpec("receipt_acknowledge", "Owner-only: consent for the high tier, or record a delivery decision on the receipt.",
             _obj({"repo": S, "tree": S, "decision": DECISION_ENUM, "reason": S, "round_dir": S}, ("tree", "decision", "reason")),
             argv=_receipt("acknowledge", ("--tree", "tree", "str"), ("--decision", "decision", "str"), ("--reason", "reason", "str"),
                           ("--repo", "repo", "repo"), ("--round-dir", "round_dir", "str")),
             ok_exit=frozenset({0, 2})),
    ToolSpec("receipt_validate", "Validate a receipt file: schema plus sha256 of every captured artifact.",
             _obj({"receipt_path": S}, ("receipt_path",)), argv=_receipt("validate", ("--receipt", "receipt_path", "str")),
             ok_exit=frozenset({0, 1})),
)

BY_NAME = {spec.name: spec for spec in TOOLS}
