"""The MCP server's machinery: a tool's shape (ToolSpec), the execution
context (Ctx), and how a call turns into an argv for an existing script
whose JSON is returned untouched. The data (which tools exist) lives in
catalog.py; none of it is listed here.

Modes:
  passthrough  the script prints JSON; exits in ok_exit are data, not error.
  outfile      the script writes out/<repo_sha>/<x>.json; it is read back and
               returned; above MAX_INLINE_BYTES the path is returned instead
               and truncated_inline is declared.
  job          Gradle or several worktrees: starts in the background and
               returns a run_id; job_status reads out/jobs/<run_id>/.
  internal     a Python handler, no subprocess (job_status).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TOOLS_ROOT = Path(__file__).resolve().parent.parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, findings_schema_validator, round_files  # noqa: E402

MAX_INLINE_BYTES = 65536
ENV_PASSTHROUGH = ("PATH", "HOME", "JAVA_HOME", "TMPDIR", "LANG", "LC_ALL", "ANDROID_HOME", "ANDROID_SDK_ROOT",
                   "GRADLE_USER_HOME", "GRADLE_OPTS", "SHELL")


class ToolError(Exception):
    """Tool failure: returned with isError=true, never as a JSON-RPC exception."""


class InvalidParams(Exception):
    """Arguments that fail the inputSchema: JSON-RPC error -32602."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    argv: Callable[[dict, "Ctx"], list[str]] | None = None
    mode: str = "passthrough"
    stdin: Callable[[dict], str | None] | None = None
    outfile: Callable[[dict, "Ctx", str], Path] | None = None
    summary: Callable[[dict, "Ctx", str], list[Path]] | None = None
    handler: Callable[[dict, "Ctx"], dict] | None = None
    ok_exit: frozenset = frozenset({0})
    timeout_s: int = 60
    roles: tuple = ()


@dataclass
class Ctx:
    tools_root: Path
    repo: Path | None
    project_config: dict = field(default_factory=dict)

    @property
    def out_dir(self) -> Path:
        return self.tools_root / "out"

    @property
    def kit_root(self) -> Path:
        return self.tools_root.parent


def _looks_unset(value: str | None) -> bool:
    return not value or value.startswith("${")


def default_ctx(tools_root: Path | None = None) -> Ctx:
    tools_root = Path(tools_root or os.environ.get("METODO_TOOLS") or TOOLS_ROOT).resolve()
    repo_env = os.environ.get("METODO_REPO")
    repo = None if _looks_unset(repo_env) else Path(repo_env).resolve()
    if repo is None:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if probe.returncode == 0:
            repo = Path(probe.stdout.strip())
    config_path = tools_root / "config" / "project.json"
    config = baseline.load_json(config_path) if config_path.exists() else {}
    return Ctx(tools_root=tools_root, repo=repo, project_config=config)


def resolve_repo(args: dict, ctx: Ctx) -> Path:
    candidate = args.get("repo")
    repo = Path(candidate).expanduser().resolve() if candidate else ctx.repo
    if repo is None:
        raise ToolError("no repo: pass `repo`, export METODO_REPO, or start the server inside a git repo")
    probe = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if probe.returncode != 0:
        raise ToolError(f"{repo} is not a git repo")
    return Path(probe.stdout.strip())


def repo_sha(repo: Path) -> str:
    return baseline.git_head_sha(repo)


def contract_path(role: str, ctx: Ctx) -> Path:
    """The live contract for this repo is the copy installed in .claude/agents;
    if it does not exist, the kit's source copy."""
    role = round_files.normalize_role(role)
    if ctx.repo is not None:
        installed = ctx.repo / ".claude" / "agents" / f"{role}.contract.json"
        if installed.exists():
            return installed
    return ctx.kit_root / "01-roles" / "agents" / f"{role}.contract.json"


def child_env(ctx: Ctx) -> dict:
    env = {k: v for k, v in os.environ.items() if k in ENV_PASSTHROUGH or k.startswith("METODO_")}
    gate = (ctx.project_config.get("test_sectors") or {}).get("credential_gate") or {}
    gate_var = gate.get("env_var")
    if gate_var and gate_var in os.environ:
        env[gate_var] = os.environ[gate_var]
    env["METODO_TOOLS"] = str(ctx.tools_root)
    if ctx.repo is not None:
        env["METODO_REPO"] = str(ctx.repo)
    return env


def validate_args(spec: ToolSpec, args: dict) -> None:
    result = findings_schema_validator.validate(args, spec.input_schema)
    if result["verdict"] == "FAIL":
        raise InvalidParams("; ".join(result["errors"]))


def _error_payload(message: str, exit_code: int | None, stderr: str) -> dict:
    tail = stderr.splitlines()[-40:]
    return {"error": message, "exit_code": exit_code, "stderr_tail": tail}


def run_passthrough(spec: ToolSpec, args: dict, ctx: Ctx) -> tuple[dict, bool]:
    argv = spec.argv(args, ctx)
    stdin = spec.stdin(args) if spec.stdin else None
    try:
        proc = subprocess.run(argv, cwd=str(ctx.tools_root), input=stdin, capture_output=True, text=True,
                              timeout=spec.timeout_s, env=child_env(ctx))
    except subprocess.TimeoutExpired:
        return _error_payload(f"timeout after {spec.timeout_s}s", None, ""), True
    if proc.returncode not in spec.ok_exit:
        return _error_payload("the script exited with an error", proc.returncode, proc.stderr), True
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _error_payload("the script did not print JSON", proc.returncode, proc.stderr + "\n" + proc.stdout[-2000:]), True
    return payload, False


def run_outfile(spec: ToolSpec, args: dict, ctx: Ctx) -> tuple[dict, bool]:
    argv = spec.argv(args, ctx)
    try:
        proc = subprocess.run(argv, cwd=str(ctx.tools_root), capture_output=True, text=True,
                              timeout=spec.timeout_s, env=child_env(ctx))
    except subprocess.TimeoutExpired:
        return _error_payload(f"timeout after {spec.timeout_s}s", None, ""), True
    if proc.returncode not in spec.ok_exit:
        return _error_payload("the script exited with an error", proc.returncode, proc.stderr), True
    repo = resolve_repo(args, ctx)
    path = spec.outfile(args, ctx, repo_sha(repo))
    if not path.exists():
        return _error_payload(f"the script did not leave {path.name}", proc.returncode, proc.stderr), True
    text = path.read_text(encoding="utf-8")
    if len(text.encode("utf-8")) > MAX_INLINE_BYTES:
        md = path.with_suffix(".md")
        return {"truncated_inline": True, "bytes": len(text.encode("utf-8")), "out_json": str(path),
                "out_md": str(md) if md.exists() else None, "repo_sha": repo_sha(repo)}, False
    return json.loads(text), False


def start_job(spec: ToolSpec, args: dict, ctx: Ctx) -> tuple[dict, bool]:
    run_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    args = dict(args, _run_id=run_id)
    argv = spec.argv(args, ctx)
    run_dir = ctx.out_dir / "jobs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    repo = resolve_repo(args, ctx)
    summaries = [str(p) for p in (spec.summary(args, ctx, run_id) if spec.summary else [])]
    (run_dir / "cmd.json").write_text(json.dumps({"tool": spec.name, "argv": argv, "summary_candidates": summaries,
                                                  "repo": str(repo)}, indent=2), encoding="utf-8")
    wrapper = "\"$@\" > \"$RUN_DIR/stdout.log\" 2>&1; echo $? > \"$RUN_DIR/exit_code\""
    env = dict(child_env(ctx), RUN_DIR=str(run_dir))
    subprocess.Popen(["bash", "-c", wrapper, "_", *argv], cwd=str(ctx.tools_root), env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"run_id": run_id, "status": "running", "log_path": str(run_dir / "stdout.log"),
            "summary_candidates": summaries}, False


def job_status(args: dict, ctx: Ctx) -> dict:
    run_id = args["run_id"]
    if not run_id.replace("-", "").isalnum():
        raise ToolError("invalid run_id")
    run_dir = ctx.out_dir / "jobs" / run_id
    if not run_dir.exists():
        raise ToolError(f"job {run_id} does not exist")
    deadline = time.time() + int(args.get("wait_seconds") or 0)
    while not (run_dir / "exit_code").exists() and time.time() < deadline:
        time.sleep(1)
    cmd = json.loads((run_dir / "cmd.json").read_text(encoding="utf-8"))
    result = {"run_id": run_id, "tool": cmd.get("tool"), "log_path": str(run_dir / "stdout.log"),
              "status": "running", "exit_code": None, "summary": None, "summary_path": None}
    log = run_dir / "stdout.log"
    result["log_mtime_age_s"] = int(time.time() - log.stat().st_mtime) if log.exists() else None
    if (run_dir / "exit_code").exists():
        result["status"] = "done"
        result["exit_code"] = int((run_dir / "exit_code").read_text(encoding="utf-8").strip() or -1)
        for candidate in cmd.get("summary_candidates", []):
            if Path(candidate).exists():
                result["summary_path"] = candidate
                try:
                    result["summary"] = json.loads(Path(candidate).read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result["summary"] = None
                break
        result["log_tail"] = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:] if log.exists() else []
    return result


def run(spec: ToolSpec, args: dict, ctx: Ctx) -> dict:
    validate_args(spec, args)
    try:
        if spec.mode == "passthrough":
            payload, is_error = run_passthrough(spec, args, ctx)
        elif spec.mode == "outfile":
            payload, is_error = run_outfile(spec, args, ctx)
        elif spec.mode == "job":
            payload, is_error = start_job(spec, args, ctx)
        elif spec.mode == "internal":
            payload, is_error = spec.handler(args, ctx), False
        else:
            raise ToolError(f"unknown mode {spec.mode}")
    except ToolError as exc:
        payload, is_error = _error_payload(str(exc), None, ""), True
    except PermissionError as exc:
        payload, is_error = _error_payload(str(exc), None, ""), True
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "structuredContent": payload, "isError": is_error}
