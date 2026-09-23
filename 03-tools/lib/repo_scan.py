"""Discovery of the analyzed repo's modules and Kotlin sources.

Reads `settings.gradle` to know which modules exist (instead of assuming a
fixed layout) and enumerates their .kt files under src/main and src/test,
excluding agent worktrees (`.claude/`) and build outputs (`build/`).
"""
from __future__ import annotations

import re
from pathlib import Path

_INCLUDE_RE = re.compile(r"include\s+'([^']+)'")
_EXCLUDED_PARTS = {".claude", "build"}


def list_modules(repo_root: Path) -> list[str]:
    """Filesystem paths of the modules declared in settings.gradle
    (':payment:gateway' -> 'payment/gateway'), in declaration order."""
    settings = Path(repo_root) / "settings.gradle"
    text = settings.read_text(encoding="utf-8")
    modules = []
    for match in _INCLUDE_RE.finditer(text):
        gradle_path = match.group(1)
        fs_path = gradle_path.lstrip(":").replace(":", "/")
        if fs_path not in modules:
            modules.append(fs_path)
    return modules


def filter_modules(modules: list[str], requested: list[str] | None) -> list[str]:
    """Applies the --modules filter (accepts 'app' or ':app' either way)."""
    if not requested:
        return modules
    wanted = {m.lstrip(":").replace(":", "/") for m in requested}
    return [m for m in modules if m in wanted]


def _is_excluded(rel_parts: tuple[str, ...]) -> bool:
    return any(part in _EXCLUDED_PARTS for part in rel_parts)


def kotlin_files(repo_root: Path, modules: list[str], subdir: str) -> list[tuple[str, str]]:
    """List of (module, path_relative_to_repo) for .kt files under
    <module>/src/<subdir>/**, sorted by path so the traversal is
    deterministic without depending on filesystem order."""
    repo_root = Path(repo_root)
    results: list[tuple[str, str]] = []
    for module in modules:
        base = repo_root / module / "src" / subdir
        if not base.is_dir():
            continue
        for path in base.rglob("*.kt"):
            rel = path.relative_to(repo_root)
            if _is_excluded(rel.parts):
                continue
            results.append((module, rel.as_posix()))
    return sorted(results, key=lambda pair: pair[1])
