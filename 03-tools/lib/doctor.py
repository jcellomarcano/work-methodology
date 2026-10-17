#!/usr/bin/env python3
"""Wiring doctor: proves the kit is installed in a target repo and responds,
for Claude Code and pi, and names the exact fix for every missing piece.

Usage:
    lib/doctor.py <repo> [--tools <tools-root>] [--runtime claude|pi|all] [--out <file>] [--table]
    lib/doctor.py <repo> --absent [--runtime claude|pi|all] [--out <file>] [--table]

--tools    tools root the repo was installed against (default: this kit's 03-tools).
--runtime  default all. claude.* checks run for claude/all, pi.* for pi/all, the rest always.
--out      also writes the JSON report to that file.
--table    prints a short human table on stdout instead of the JSON.
--absent   inverts the wiring checks into an absence report (after
           bin/install.sh <repo> --uninstall): PASS when no kit agent, skill,
           hook, MCP entry, pi extension or override remains in the repo, FAIL
           per remaining item with its fix. Envelope {schema_version, mode:
           "absent", repo_sha, runtime, verdict, kit_absent, summary,
           placeholders, checks}; exit 0 when kit_absent, 1 otherwise. The
           shared .mcp.json entry is PASS while the other runtime still uses it
           (single-runtime check only). The normal mode is unchanged.

Exit: 0 no FAIL (WARNs allowed), 1 at least one FAIL, 2 usage (missing path, bad flag).
A directory that is not a git repo is not a usage error: it is reported as
repo.git FAIL (exit 1), so the caller still gets the evidence.

Output (deterministic: sorted keys, no timestamps, no absolute paths):
    {schema_version, tool_sha, repo_sha, repo_dirty, runtime, verdict, kit_installed,
     required, summary, placeholders, checks: [{id, status, detail, fix}]}
status is PASS|WARN|FAIL|SKIP; fix is null on PASS, otherwise the exact
command or file to edit. Paths are repo-relative, or written with the
placeholders <repo> and <tools>; `bin/...` commands run from the kit's 03-tools.
kit_installed is true only when every check in `required` is PASS or WARN,
which is what 08-benchmark reads to accept a kit arm or mark it invalid-arm.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The doctor's own tools dir: where the installers (and the kit's 01-roles/) live.
KIT_TOOLS = Path(__file__).resolve().parent.parent
# Same header version as lib/baseline.py's SCHEMA_VERSION.
SCHEMA_VERSION = "1.0.0"
RUNTIMES = ("claude", "pi", "all")
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")
HOOK_MARKER = ": metodo-hook;"
TOOLS_TOKEN = "__TOOLS_DEFAULT__"
REPO_TOKEN = "__REPO_DEFAULT__"
REQUIRED_CONFIG_KEYS = ("shared_build_files", "property_order", "rdd", "test_sectors")
TOOLS_LAYOUT = ("lib", "mcp/server.py", "hooks", "schemas", "config/project.json")
PLACEHOLDERS = {
    "<repo>": "the repo argument",
    "<tools>": "the tools root (--tools)",
    "bin/": "commands run from the kit's 03-tools",
}
REQUIRED_ALWAYS = ("repo.git", "tools.layout", "config.project", "hooks.fire", "git.exclude", "personal.absent")
REQUIRED_BY_RUNTIME = {
    "claude": ("claude.agents", "claude.skills", "claude.mcp", "claude.hooks"),
    "pi": ("pi.agents", "pi.skills", "pi.mcp", "pi.extension"),
}

# The same awk install-pi.sh runs over install-claude.sh's SKILLS=( ... ) array.
_SKILLS_AWK = r'/^SKILLS=\(/{f=1;next} f&&/^\)/{exit} f{gsub(/[ \t]/,"");if($0!="")print}'


def installer_skills(installer: Path) -> list[str]:
    """The skills the installer ships. The ONE place that knows the format
    of install-claude.sh's SKILLS array: a format change touches only this."""
    try:
        proc = subprocess.run(["awk", _SKILLS_AWK, str(installer)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _real(path: os.PathLike | str) -> str:
    return os.path.realpath(str(path))


def _is_dirty(repo: Path) -> bool:
    """Same rule as lib/baseline.is_repo_dirty: anything reported by
    `git status --porcelain` outside .claude/ (agent worktrees) counts."""
    out = _git(repo, "status", "--porcelain")
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:] if len(line) > 3 else line.strip()
        path = path.split(" -> ")[-1].strip().strip('"')
        if path == ".claude" or path.startswith(".claude/") or "/.claude/" in path:
            continue
        return True
    return False


def _expand(expr: str) -> str:
    """Expands $VAR, ${VAR} and ${VAR:-default} (nested) the way the runtime would."""
    text = expr
    for _ in range(6):
        before = text
        text = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), text)
        text = re.sub(r"\$(\w+)", lambda m: os.environ.get(m.group(1), ""), text)
        text = re.sub(r"\$\{(\w+):-([^${}]*)\}", lambda m: os.environ.get(m.group(1)) or m.group(2), text)
        if text == before:
            break
    return os.path.expanduser(text)


def _check(check_id: str, status: str, detail: str, fix: str | None = None) -> dict:
    return {"id": check_id, "status": status, "detail": detail, "fix": None if status == "PASS" else fix}


class Ctx:
    def __init__(self, repo: Path, tools: Path, runtime: str):
        self.repo = repo
        self.tools = tools
        self.runtime = runtime
        self.repo_real = _real(repo)
        self.tools_real = _real(tools)
        self.is_kit_tools = self.tools_real == _real(KIT_TOOLS)
        self.repo_sha: str | None = None
        self.is_git = False
        self.config: dict | None = None
        self.config_error: str | None = None
        self._selftest: tuple[bool, str] | None = None
        path = tools / "config" / "project.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.config = data
            else:
                self.config_error = "is not a JSON object"
        except FileNotFoundError:
            self.config_error = "is missing"
        except (OSError, json.JSONDecodeError) as exc:
            self.config_error = f"does not parse ({type(exc).__name__})"

    def show(self, path: os.PathLike | str) -> str:
        """A path without its absolute prefix: <tools>/..., repo-relative, ~/..., or <external>/name."""
        real = _real(path)
        bases = sorted(((self.tools_real, "<tools>"), (self.repo_real, "")), key=lambda b: len(b[0]), reverse=True)
        for base, label in bases:
            if real == base:
                return label or "."
            if real.startswith(base.rstrip(os.sep) + os.sep):
                rel = os.path.relpath(real, base)
                return f"{label}/{rel}" if label else rel
        home = _real(Path.home())
        if real.startswith(home + os.sep):
            return "~/" + os.path.relpath(real, home)
        return "<external>/" + os.path.basename(real)

    def install_fix(self, runtime: str) -> str:
        cmd = f"bin/install.sh <repo> --runtime {runtime}"
        return cmd if self.is_kit_tools else cmd + " --tools <tools>"

    def restore_tools_fix(self, rel: str) -> str:
        return f"<tools>/{rel}" if self.is_kit_tools else "bin/sync-instance.sh <tools>"

    def selftest(self) -> tuple[bool, str]:
        if self._selftest is None:
            server = self.tools / "mcp" / "server.py"
            if not server.is_file():
                self._selftest = (False, "<tools>/mcp/server.py is missing")
            else:
                env = dict(os.environ, METODO_REPO=str(self.repo))
                try:
                    proc = subprocess.run([sys.executable, str(server), "--selftest", "--tools-root", str(self.tools)],
                                          capture_output=True, text=True, env=env, timeout=120)
                    if proc.returncode == 0:
                        try:
                            count = json.loads(proc.stdout).get("tools")
                        except (json.JSONDecodeError, AttributeError):
                            count = None
                        self._selftest = (True, f"selftest ok ({count} tools)" if count is not None else "selftest ok")
                    else:
                        self._selftest = (False, f"selftest failed (exit {proc.returncode})")
                except (OSError, subprocess.SubprocessError) as exc:
                    self._selftest = (False, f"selftest did not run ({type(exc).__name__})")
        return self._selftest


# ---------------------------------------------------------------- checks

def check_repo_git(ctx: Ctx) -> dict:
    if _git(ctx.repo, "rev-parse", "--show-toplevel").returncode != 0:
        return _check("repo.git", "FAIL", "not a git repository",
                      "git -C <repo> init && git -C <repo> commit --allow-empty -m 'initial commit'")
    head = _git(ctx.repo, "rev-parse", "--verify", "--quiet", "HEAD")
    if head.returncode != 0:
        return _check("repo.git", "FAIL", "git repository without commits",
                      "git -C <repo> commit --allow-empty -m 'initial commit'")
    ctx.is_git = True
    ctx.repo_sha = head.stdout.strip()
    return _check("repo.git", "PASS", f"git repository at {ctx.repo_sha[:12]}")


def check_tools_git(ctx: Ctx, tool_sha: str | None) -> dict:
    if tool_sha is None:
        return _check("tools.git", "WARN", "tools root is not a git repository: tool_sha is null",
                      "git -C <tools> init && git -C <tools> add -A && git -C <tools> commit -m 'tools instance'")
    return _check("tools.git", "PASS", f"tools root at {tool_sha[:12]}")


def check_tools_layout(ctx: Ctx) -> dict:
    missing = [rel for rel in TOOLS_LAYOUT if not (ctx.tools / rel).exists()]
    if missing:
        return _check("tools.layout", "FAIL", "missing under <tools>: " + ", ".join(missing), "bin/sync-instance.sh <tools>")
    return _check("tools.layout", "PASS", "lib/, mcp/server.py, hooks/, schemas/, config/project.json present")


def check_tools_is_kit(ctx: Ctx) -> dict:
    parent = ctx.tools.parent
    if (parent / "01-roles").is_dir() and (parent / "02-skills").is_dir():
        return _check("tools.is_kit", "WARN",
                      "tools root is the kit's own 03-tools: config/ is the shared template, not a project instance",
                      "bin/sync-instance.sh <instance>")
    return _check("tools.is_kit", "PASS", "tools root is a project instance")


def check_config_project(ctx: Ctx) -> dict:
    if ctx.config is None:
        return _check("config.project", "FAIL", f"<tools>/config/project.json {ctx.config_error}", "<tools>/config/project.json")
    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in ctx.config]
    if missing:
        return _check("config.project", "FAIL", "missing required keys: " + ", ".join(missing), "<tools>/config/project.json")
    if "critical_properties" not in ctx.config:
        return _check("config.project", "WARN", "critical_properties is absent", "<tools>/config/project.json")
    return _check("config.project", "PASS", "required keys present")


def check_config_base_ref(ctx: Ctx) -> dict:
    if ctx.config is None:
        return _check("config.base_ref", "SKIP", "config/project.json unreadable (see config.project)", "<tools>/config/project.json")
    if not ctx.is_git:
        return _check("config.base_ref", "SKIP", "no git repository (see repo.git)", "git -C <repo> init")
    ref = (ctx.config.get("test_sectors") or {}).get("base_ref")
    fix = "<tools>/config/project.json (test_sectors.base_ref)"
    if not ref:
        return _check("config.base_ref", "WARN", "test_sectors.base_ref is not set", fix)
    if _git(ctx.repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        return _check("config.base_ref", "WARN", f"base_ref {ref} does not resolve in the repo", fix)
    return _check("config.base_ref", "PASS", f"base_ref {ref} resolves")


def _roles_dir(ctx: Ctx) -> Path | None:
    for candidate in (KIT_TOOLS.parent / "01-roles" / "agents", ctx.tools.parent / "01-roles" / "agents"):
        if candidate.is_dir():
            return candidate
    return None


def _check_agents(ctx: Ctx, check_id: str, dst_rel: str, with_contracts: bool, runtime: str) -> dict:
    roles = _roles_dir(ctx)
    if roles is None:
        return _check(check_id, "SKIP", "the kit's 01-roles/agents/ is not reachable: run the doctor from the kit",
                      "bin/doctor.sh <repo> --tools <tools>")
    patterns = ["generic-*.md"] + (["generic-*.contract.json"] if with_contracts else [])
    expected = sorted({p.name for pattern in patterns for p in roles.glob(pattern)})
    dst = ctx.repo / dst_rel
    missing = [name for name in expected if not (dst / name).is_file()]
    unrendered = sorted(p.name for p in dst.glob("generic-*.md") if p.is_file() and TOOLS_TOKEN in p.read_text(encoding="utf-8", errors="replace"))
    problems = []
    if missing:
        problems.append(f"missing under {dst_rel}/: " + ", ".join(missing))
    if unrendered:
        problems.append(f"{TOOLS_TOKEN} not rendered in: " + ", ".join(unrendered))
    if problems:
        return _check(check_id, "FAIL", "; ".join(problems), ctx.install_fix(runtime))
    return _check(check_id, "PASS", f"{len(expected)} agent files under {dst_rel}/")


def _check_skills(ctx: Ctx, check_id: str, dst_rel: str, runtime: str) -> dict:
    installer = KIT_TOOLS / "bin" / "install-claude.sh"
    skills = installer_skills(installer)
    if not skills:
        return _check(check_id, "FAIL", "could not read the skill list from bin/install-claude.sh", "bin/install-claude.sh (SKILLS array)")
    missing = [s for s in skills if not (ctx.repo / dst_rel / s / "SKILL.md").is_file()]
    if missing:
        return _check(check_id, "FAIL", f"missing {dst_rel}/<name>/SKILL.md for: " + ", ".join(missing), ctx.install_fix(runtime))
    return _check(check_id, "PASS", f"{len(skills)} skills under {dst_rel}/")


def _mcp_problems(ctx: Ctx) -> tuple[list[str], str]:
    """Problems with .mcp.json's metodo entry and the server it starts; and a PASS detail."""
    path = ctx.repo / ".mcp.json"
    if not path.is_file():
        return [".mcp.json is missing"], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [".mcp.json does not parse"], ""
    entry = ((data or {}).get("mcpServers") or {}).get("metodo") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return [".mcp.json has no mcpServers.metodo"], ""
    args = entry.get("args") or []
    if not args:
        return ["mcpServers.metodo has no server path in args"], ""
    server = _expand(str(args[0]))
    if not os.path.isfile(server):
        return [f"mcpServers.metodo server {ctx.show(server)} does not exist"], ""
    problems = []
    if _real(server) != _real(ctx.tools / "mcp" / "server.py"):
        problems.append(f"mcpServers.metodo runs {ctx.show(server)}, not <tools>/mcp/server.py")
    repo_expr = _expand(str((entry.get("env") or {}).get("METODO_REPO") or ""))
    if repo_expr and _real(repo_expr) != ctx.repo_real:
        problems.append(f"mcpServers.metodo METODO_REPO names {ctx.show(repo_expr)}, not this repo")
    ok, detail = ctx.selftest()
    if not ok:
        problems.append(detail)
    return problems, f"metodo server <tools>/mcp/server.py, {detail}"


def check_claude_mcp(ctx: Ctx) -> dict:
    problems, detail = _mcp_problems(ctx)
    if problems:
        return _check("claude.mcp", "FAIL", "; ".join(problems), ctx.install_fix("claude"))
    return _check("claude.mcp", "PASS", detail)


def check_pi_mcp(ctx: Ctx) -> dict:
    problems, detail = _mcp_problems(ctx)
    path = ctx.repo / ".pi" / "mcp.json"
    try:
        prefix = ((json.loads(path.read_text(encoding="utf-8")).get("mcpServers") or {}).get("metodo") or {}).get("toolPrefix")
    except (OSError, json.JSONDecodeError, AttributeError):
        prefix = None
    if prefix != "mcp":
        problems.append('.pi/mcp.json lacks toolPrefix "mcp" for metodo')
    if problems:
        return _check("pi.mcp", "FAIL", "; ".join(problems), ctx.install_fix("pi"))
    return _check("pi.mcp", "PASS", detail + ', toolPrefix "mcp"')


def check_claude_hooks(ctx: Ctx) -> dict:
    kit_path = ctx.tools / "hooks" / "hooks.settings.json"
    try:
        kit_hooks = json.loads(kit_path.read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return _check("claude.hooks", "FAIL", "<tools>/hooks/hooks.settings.json is missing or does not parse",
                      ctx.restore_tools_fix("hooks/hooks.settings.json"))
    settings_path = ctx.repo / ".claude" / "settings.local.json"
    try:
        installed = json.loads(settings_path.read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return _check("claude.hooks", "FAIL", ".claude/settings.local.json is missing or does not parse", ctx.install_fix("claude"))
    missing, total = [], 0
    for event in sorted(kit_hooks):
        for kit_entry in kit_hooks[event]:
            total += 1
            matcher = kit_entry.get("matcher", "")
            scripts = {m for h in kit_entry.get("hooks", []) for m in re.findall(r"[\w-]+\.py", str(h.get("command", "")))}
            found = False
            for entry in (installed.get(event) or []):
                if not isinstance(entry, dict) or entry.get("matcher", "") != matcher:
                    continue
                commands = [str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict)]
                if any(HOOK_MARKER in c and all(s in c for s in scripts) for c in commands):
                    found = True
                    break
            if not found:
                missing.append(f"{event}[{matcher or '*'}]")
    if missing:
        return _check("claude.hooks", "FAIL", "no kit-marked hook for: " + ", ".join(missing), ctx.install_fix("claude"))
    return _check("claude.hooks", "PASS", f"{total} kit-marked hooks in .claude/settings.local.json")


def check_hooks_fire(ctx: Ctx) -> dict:
    script = ctx.tools / "hooks" / "guard_gates.py"
    fix = ctx.restore_tools_fix("hooks/guard_gates.py")
    if not script.is_file():
        return _check("hooks.fire", "FAIL", "<tools>/hooks/guard_gates.py is missing", fix)
    payload = {"session_id": "doctor", "cwd": str(ctx.repo), "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": {"command": "git push --force origin x"}}
    with tempfile.TemporaryDirectory(prefix="metodo-doctor-") as tmp:
        env = dict(os.environ, METODO_TOOLS=str(ctx.tools), METODO_HOOKS_DIR=str(Path(tmp) / "hooks"),
                   METODO_RDD_DIR=str(Path(tmp) / "rdd"))
        try:
            proc = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), capture_output=True,
                                  text=True, env=env, cwd=tmp, timeout=60)
            out = json.loads(proc.stdout) if proc.stdout.strip() else {}
            decision = ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AttributeError):
            decision = None
    if decision != "deny":
        return _check("hooks.fire", "FAIL", f"guard_gates.py did not deny a synthetic git push --force (decision: {decision})", fix)
    return _check("hooks.fire", "PASS", "guard_gates.py denied a synthetic git push --force")


def check_git_exclude(ctx: Ctx) -> dict:
    fix = 'echo .mcp.json >> "$(git -C <repo> rev-parse --path-format=absolute --git-common-dir)/info/exclude"'
    if not ctx.is_git:
        return _check("git.exclude", "SKIP", "no git repository (see repo.git)", fix)
    common = _git(ctx.repo, "rev-parse", "--git-common-dir").stdout.strip()
    common_path = Path(common) if os.path.isabs(common) else ctx.repo / common
    try:
        lines = {l.strip() for l in (common_path / "info" / "exclude").read_text(encoding="utf-8").splitlines()}
    except OSError:
        lines = set()
    if not lines & {".mcp.json", "/.mcp.json"}:
        return _check("git.exclude", "FAIL", ".mcp.json (absolute local paths) is not in info/exclude", fix)
    return _check("git.exclude", "PASS", ".mcp.json is in info/exclude")


def check_pi_extension(ctx: Ctx) -> dict:
    dst = ctx.repo / ".pi" / "extensions" / "metodo-hooks.ts"
    template = ctx.tools / "hooks" / "pi" / "metodo-hooks.ts"
    if not template.is_file():
        return _check("pi.extension", "FAIL", "<tools>/hooks/pi/metodo-hooks.ts is missing", ctx.restore_tools_fix("hooks/pi/metodo-hooks.ts"))
    if not dst.is_file():
        return _check("pi.extension", "FAIL", ".pi/extensions/metodo-hooks.ts is missing", ctx.install_fix("pi"))
    text = template.read_text(encoding="utf-8")
    installed = dst.read_text(encoding="utf-8", errors="replace")
    tools_forms = sorted({os.path.abspath(ctx.tools), ctx.tools_real})
    repo_forms = sorted({os.path.abspath(ctx.repo), ctx.repo_real})
    if any(installed == text.replace(TOOLS_TOKEN, t).replace(REPO_TOKEN, r) for t in tools_forms for r in repo_forms):
        return _check("pi.extension", "PASS", ".pi/extensions/metodo-hooks.ts matches <tools>/hooks/pi/metodo-hooks.ts")
    return _check("pi.extension", "FAIL",
                  ".pi/extensions/metodo-hooks.ts differs from <tools>/hooks/pi/metodo-hooks.ts rendered for this repo",
                  ctx.install_fix("pi"))


def check_memory_engram(ctx: Ctx) -> dict:
    if os.environ.get("METODO_MEMORY", "").lower() == "off":
        return _check("memory.engram", "SKIP", "memory disabled (METODO_MEMORY=off)")
    if not ((ctx.config or {}).get("memory") or {}).get("enabled"):
        return _check("memory.engram", "SKIP", "memory.enabled is false")
    if shutil.which("engram") is None:
        return _check("memory.engram", "WARN", "memory.enabled is true but engram is not on PATH",
                      "brew install gentleman-programming/tap/engram (or set memory.enabled false in <tools>/config/project.json)")
    return _check("memory.engram", "PASS", "engram on PATH")


def check_vendor_tools(ctx: Ctx) -> dict:
    lock_path = ctx.tools / "config" / "tools.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _check("vendor.tools", "WARN", "<tools>/config/tools.lock.json is missing or does not parse", "bin/fetch-tools.sh")
    problems = []
    for name in sorted(lock if isinstance(lock, dict) else {}):
        entry = lock[name] if isinstance(lock[name], dict) else {}
        if entry.get("status") == "unavailable":
            problems.append(f"{name} unavailable")
        elif not entry.get("path") or not (ctx.tools / str(entry["path"])).exists():
            problems.append(f"{name} file missing")
    if problems:
        return _check("vendor.tools", "WARN", "; ".join(problems), "bin/fetch-tools.sh")
    return _check("vendor.tools", "PASS", f"{len(lock)} pinned tools present")


# Canonical B5 review (routing-method.md §3): a medium review with findings.
ROUTER_PROBE = {"task_kind": "review", "tier": "medium", "lane": "sonnet", "modules": 1, "map_age_days": 1,
                "offline": False, "prior": {"findings": 1}}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _unpriced(catalog: dict, as_of: str) -> list[str]:
    """Admitted entries without a price row valid on as_of (from null or <= as_of)."""
    missing = []
    for tier_name, tier in sorted((catalog.get("tiers") or {}).items()):
        for entry in (tier or {}).get("candidates") or []:
            if entry.get("status") != "admitted":
                continue
            rows = [r for r in entry.get("price_schedule") or [] if isinstance(r, dict)
                    and (r.get("from") is None or str(r["from"]) <= as_of)
                    and isinstance(r.get("usd_in"), (int, float)) and isinstance(r.get("usd_out"), (int, float))]
            if not rows:
                missing.append(f"{tier_name}/{entry.get('id')}")
    return missing


def check_router_catalog(ctx: Ctx) -> dict:
    """The routing catalog parses, has a version, every admitted model has a
    price on the catalog's own date (`updated`, never the clock), and the
    router answers ok for a canonical B5 review."""
    fix = ("<tools>/config/model-tiers.json" if ctx.is_kit_tools
           else "<tools>/config/model-tiers.json (compare with the kit's 03-tools/config/model-tiers.json)")
    try:
        catalog = json.loads((ctx.tools / "config" / "model-tiers.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _check("router.catalog", "FAIL", "<tools>/config/model-tiers.json is missing", fix)
    except (OSError, json.JSONDecodeError) as exc:
        return _check("router.catalog", "FAIL", f"<tools>/config/model-tiers.json does not parse ({type(exc).__name__})", fix)
    if not isinstance(catalog, dict) or not catalog.get("version"):
        return _check("router.catalog", "FAIL", "model-tiers.json has no version", fix)
    as_of = str(catalog.get("updated") or catalog.get("read") or "")
    if not DATE_RE.match(as_of):
        return _check("router.catalog", "FAIL", f"model-tiers.json has no updated date (got {as_of!r})", fix)
    unpriced = _unpriced(catalog, as_of)
    if unpriced:
        return _check("router.catalog", "FAIL", f"admitted models without a price on {as_of}: " + ", ".join(unpriced), fix)
    if str(KIT_TOOLS) not in sys.path:
        sys.path.insert(0, str(KIT_TOOLS))
    from lib import router  # noqa: E402  (the kit's router judges any tools root's catalog)
    try:
        result = router.route(ROUTER_PROBE, catalog, as_of)
    except Exception as exc:  # noqa: BLE001 - a malformed catalog must surface as FAIL, not a crash
        return _check("router.catalog", "FAIL", f"router crashed on the B5 probe ({type(exc).__name__})", fix)
    if result.get("status") != "ok" or result.get("rule") != "B5" or not result.get("roster"):
        return _check("router.catalog", "FAIL", f"router B5 probe returned rule {result.get('rule')} status "
                      f"{result.get('status')}: " + "; ".join(result.get("reasons") or []), fix)
    return _check("router.catalog", "PASS", f"catalog {catalog['version']} as of {as_of}: B5 probe ok "
                  f"({len(result['roster'])} roles)")


def check_baseline_latest(ctx: Ctx) -> dict:
    if not (ctx.tools / "baselines" / "latest").exists():
        return _check("baseline.latest", "WARN", "<tools>/baselines/latest is missing", "bin/metrics.sh <repo> --save")
    return _check("baseline.latest", "PASS", "<tools>/baselines/latest present")


# Personal assets, by convention: any path component named `personal`, or
# matching `*.personal.*` (both git-ignored in the kit), plus the owner's
# local bench scratch folder. They are never installed, synced or read.
PERSONAL_DIR = "personal"
PERSONAL_GLOB = "*.personal.*"


def is_personal_path(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    parts = [p for p in rel.split("/") if p]
    return (any(p == PERSONAL_DIR or fnmatch.fnmatch(p, PERSONAL_GLOB) for p in parts)
            or "bench/tmp" in rel)


def _is_personal(rel: str, name: str) -> bool:
    return is_personal_path(rel)


def check_personal_absent(ctx: Ctx) -> dict:
    found = []
    for top in (".claude", ".pi"):
        root = ctx.repo / top
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # nested checkouts (agent worktrees) are another repo, not an installed asset
            dirnames[:] = [d for d in dirnames if d != "worktrees" and not (Path(dirpath) / d / ".git").exists()]
            for name in dirnames + filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), ctx.repo).replace(os.sep, "/")
                if _is_personal(rel, name):
                    found.append(rel)
    found = sorted(set(found))
    # report only the outermost match (a personal dir already covers its contents)
    found = [p for p in found if not any(p != q and p.startswith(q + "/") for q in found)]
    if found:
        return _check("personal.absent", "FAIL", "personal assets installed: " + ", ".join(found),
                      "rm -r -- " + " ".join(f"<repo>/{p}" for p in found))
    return _check("personal.absent", "PASS", "no personal asset under .claude/ or .pi/")


# ---------------------------------------------------------------- report

def build_report(repo: Path, tools: Path, runtime: str) -> dict:
    ctx = Ctx(repo, tools, runtime)
    tool_head = _git(tools, "rev-parse", "--verify", "--quiet", "HEAD")
    tool_sha = tool_head.stdout.strip() if tool_head.returncode == 0 and tool_head.stdout.strip() else None
    checks = [check_repo_git(ctx), check_tools_git(ctx, tool_sha), check_tools_layout(ctx), check_tools_is_kit(ctx),
              check_config_project(ctx), check_config_base_ref(ctx), check_hooks_fire(ctx), check_git_exclude(ctx),
              check_memory_engram(ctx), check_vendor_tools(ctx), check_baseline_latest(ctx), check_personal_absent(ctx),
              check_router_catalog(ctx)]
    runtimes = ("claude", "pi") if runtime == "all" else (runtime,)
    if "claude" in runtimes:
        checks += [_check_agents(ctx, "claude.agents", ".claude/agents", True, "claude"),
                   _check_skills(ctx, "claude.skills", ".claude/skills", "claude"),
                   check_claude_mcp(ctx), check_claude_hooks(ctx)]
    if "pi" in runtimes:
        checks += [_check_agents(ctx, "pi.agents", ".pi/agents", False, "pi"),
                   _check_skills(ctx, "pi.skills", ".pi/skills", "pi"),
                   check_pi_mcp(ctx), check_pi_extension(ctx)]
    checks.sort(key=lambda c: c["id"])
    required = sorted(set(REQUIRED_ALWAYS).union(*(REQUIRED_BY_RUNTIME[r] for r in runtimes)))
    by_id = {c["id"]: c for c in checks}
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in STATUSES}
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_sha": tool_sha,
        "repo_sha": ctx.repo_sha,
        "repo_dirty": _is_dirty(repo) if ctx.is_git else None,
        "runtime": runtime,
        "checks": checks,
        "required": required,
        "summary": summary,
        "placeholders": PLACEHOLDERS,
        "verdict": "FAIL" if summary["FAIL"] else "PASS",
        "kit_installed": all(by_id[i]["status"] in ("PASS", "WARN") for i in required),
    }


# ---------------------------------------------------------------- absence mode (after --uninstall)

def _kit_agent_names(with_contracts: bool) -> list[str] | None:
    roles = KIT_TOOLS.parent / "01-roles" / "agents"
    if not roles.is_dir():
        return None
    patterns = ["generic-*.md"] + (["generic-*.contract.json"] if with_contracts else [])
    return sorted({p.name for pattern in patterns for p in roles.glob(pattern)})


def _uninstall_fix(runtime: str) -> str:
    return (f"bin/install.sh <repo> --uninstall --runtime {runtime}; a file it keeps as modified is yours: "
            "delete it by hand if you no longer want it")


def _absent_agents(repo: Path, check_id: str, dst_rel: str, with_contracts: bool, runtime: str) -> dict:
    names = _kit_agent_names(with_contracts)
    if names is None:
        return _check(check_id, "SKIP", "the kit's 01-roles/agents/ is not reachable: run the doctor from the kit",
                      "bin/doctor.sh <repo> --absent")
    left = [f"{dst_rel}/{n}" for n in names if os.path.lexists(repo / dst_rel / n)]
    if left:
        return _check(check_id, "FAIL", "kit agent files remain: " + ", ".join(left), _uninstall_fix(runtime))
    return _check(check_id, "PASS", f"no kit agent under {dst_rel}/")


def _absent_skills(repo: Path, check_id: str, dst_rel: str, runtime: str) -> dict:
    skills = installer_skills(KIT_TOOLS / "bin" / "install-claude.sh")
    src = KIT_TOOLS.parent / "02-skills"
    if not skills or not src.is_dir():
        return _check(check_id, "SKIP", "the kit's skill list or 02-skills/ is not reachable: run the doctor from the kit",
                      "bin/doctor.sh <repo> --absent")
    left = []
    for skill in skills:
        names = sorted(p.name for p in (src / skill).glob("*")) if (src / skill).is_dir() else []
        left += [f"{dst_rel}/{skill}/{n}" for n in names if os.path.lexists(repo / dst_rel / skill / n)]
    if left:
        return _check(check_id, "FAIL", "kit skill files remain: " + ", ".join(left), _uninstall_fix(runtime))
    return _check(check_id, "PASS", f"no kit skill file under {dst_rel}/")


def _load_json(path: Path):
    """(data, error): data is None with error 'missing' or 'does not parse'."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, json.JSONDecodeError):
        return None, "does not parse"


def _has_metodo_server(path: Path) -> tuple[bool | None, str | None]:
    data, error = _load_json(path)
    if error == "missing":
        return False, None
    if error:
        return None, error
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return isinstance(servers, dict) and "metodo" in servers, None


def _claude_hooks_left(repo: Path) -> tuple[int | None, str | None]:
    data, error = _load_json(repo / ".claude" / "settings.local.json")
    if error == "missing":
        return 0, None
    if error:
        return None, error
    count = 0
    for entries in ((data.get("hooks") if isinstance(data, dict) else None) or {}).values():
        for entry in entries if isinstance(entries, list) else []:
            hooks = entry.get("hooks", []) if isinstance(entry, dict) else []
            if any(isinstance(h, dict) and "metodo-hook" in str(h.get("command", "")) for h in hooks):
                count += 1
    return count, None


def _pi_wired(repo: Path) -> bool:
    override, _ = _has_metodo_server(repo / ".pi" / "mcp.json")
    return bool(override) or os.path.lexists(repo / ".pi" / "extensions" / "metodo-hooks.ts")


def _absent_shared_mcp(repo: Path, check_id: str, runtime: str) -> dict:
    present, error = _has_metodo_server(repo / ".mcp.json")
    if error:
        return _check(check_id, "FAIL", f".mcp.json {error}: cannot prove the metodo server is gone",
                      "<repo>/.mcp.json (fix or remove mcpServers.metodo by hand)")
    if not present:
        return _check(check_id, "PASS", ".mcp.json has no mcpServers.metodo")
    other = {"claude": "pi", "pi": "claude"}.get(runtime)
    if other == "pi" and _pi_wired(repo):
        return _check(check_id, "PASS", ".mcp.json keeps mcpServers.metodo: shared with pi, which is still installed")
    if other == "claude" and (_claude_hooks_left(repo)[0] or 0) > 0:
        return _check(check_id, "PASS", ".mcp.json keeps mcpServers.metodo: shared with claude, which is still installed")
    return _check(check_id, "FAIL", ".mcp.json still declares mcpServers.metodo", _uninstall_fix(runtime))


def _absent_claude_hooks(repo: Path) -> dict:
    count, error = _claude_hooks_left(repo)
    if error:
        return _check("claude.hooks", "FAIL", f".claude/settings.local.json {error}: cannot prove the kit hooks are gone",
                      "<repo>/.claude/settings.local.json")
    if count:
        return _check("claude.hooks", "FAIL", f"{count} kit-marked hook entries remain in .claude/settings.local.json",
                      _uninstall_fix("claude"))
    return _check("claude.hooks", "PASS", "no kit-marked hook in .claude/settings.local.json")


def _absent_pi_extension(repo: Path) -> dict:
    if os.path.lexists(repo / ".pi" / "extensions" / "metodo-hooks.ts"):
        return _check("pi.extension", "FAIL", ".pi/extensions/metodo-hooks.ts remains", _uninstall_fix("pi"))
    return _check("pi.extension", "PASS", "no .pi/extensions/metodo-hooks.ts")


def _absent_pi_mcp(repo: Path, runtime: str) -> dict:
    override, error = _has_metodo_server(repo / ".pi" / "mcp.json")
    if error:
        return _check("pi.mcp", "FAIL", f".pi/mcp.json {error}: cannot prove the metodo override is gone",
                      "<repo>/.pi/mcp.json")
    shared = _absent_shared_mcp(repo, "pi.mcp", runtime)
    problems = ([".pi/mcp.json still declares mcpServers.metodo"] if override else []) + \
               ([shared["detail"]] if shared["status"] == "FAIL" else [])
    if problems:
        return _check("pi.mcp", "FAIL", "; ".join(problems), _uninstall_fix("pi"))
    return _check("pi.mcp", "PASS", "no metodo override in .pi/mcp.json; " + shared["detail"])


def build_absent_report(repo: Path, runtime: str) -> dict:
    head = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD")
    repo_sha = head.stdout.strip() if head.returncode == 0 and head.stdout.strip() else None
    runtimes = ("claude", "pi") if runtime == "all" else (runtime,)
    checks = []
    if "claude" in runtimes:
        checks += [_absent_agents(repo, "claude.agents", ".claude/agents", True, "claude"),
                   _absent_skills(repo, "claude.skills", ".claude/skills", "claude"),
                   _absent_claude_hooks(repo),
                   _absent_shared_mcp(repo, "claude.mcp", "all" if runtime == "all" else "claude")]
    if "pi" in runtimes:
        checks += [_absent_agents(repo, "pi.agents", ".pi/agents", False, "pi"),
                   _absent_skills(repo, "pi.skills", ".pi/skills", "pi"),
                   _absent_pi_extension(repo), _absent_pi_mcp(repo, "all" if runtime == "all" else "pi")]
    checks.sort(key=lambda c: c["id"])
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in STATUSES}
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "absent",
        "repo_sha": repo_sha,
        "runtime": runtime,
        "checks": checks,
        "summary": summary,
        "placeholders": {k: v for k, v in PLACEHOLDERS.items() if k != "<tools>"},
        "verdict": "FAIL" if summary["FAIL"] else "PASS",
        "kit_absent": all(c["status"] == "PASS" for c in checks),
    }


def dumps(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def render_table(report: dict) -> str:
    width = max(len(c["id"]) for c in report["checks"])
    lines = [f"{'STATUS':<6}  {'CHECK':<{width}}  DETAIL"]
    for c in report["checks"]:
        lines.append(f"{c['status']:<6}  {c['id']:<{width}}  {c['detail']}")
        if c["status"] in ("FAIL", "WARN") and c["fix"]:
            lines.append(f"{'':<6}  {'':<{width}}  fix: {c['fix']}")
    s = report["summary"]
    flag = ("kit_absent", report["kit_absent"]) if report.get("mode") == "absent" else ("kit_installed", report["kit_installed"])
    lines.append(f"verdict: {report['verdict']}  {flag[0]}: {str(flag[1]).lower()}  "
                 f"(PASS {s['PASS']}, WARN {s['WARN']}, FAIL {s['FAIL']}, SKIP {s['SKIP']}; runtime {report['runtime']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wiring doctor: is the kit installed in <repo> and does it respond?")
    parser.add_argument("repo")
    parser.add_argument("--tools", default=str(KIT_TOOLS))
    parser.add_argument("--runtime", choices=RUNTIMES, default="all")
    parser.add_argument("--out", default=None)
    parser.add_argument("--table", action="store_true", help="print a human table instead of the JSON")
    parser.add_argument("--absent", action="store_true",
                        help="absence report after --uninstall: PASS when nothing the kit installs remains")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.repo):
        print(f"doctor: not a directory: {args.repo}", file=sys.stderr)
        return 2
    if args.absent:
        report = build_absent_report(Path(os.path.abspath(args.repo)), args.runtime)
        text = dumps(report)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        sys.stdout.write(render_table(report) if args.table else text)
        return 0 if report["kit_absent"] else 1
    if not os.path.isdir(args.tools):
        print(f"doctor: tools root is not a directory: {args.tools}", file=sys.stderr)
        return 2
    report = build_report(Path(os.path.abspath(args.repo)), Path(os.path.abspath(args.tools)), args.runtime)
    text = dumps(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    sys.stdout.write(render_table(report) if args.table else text)
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
