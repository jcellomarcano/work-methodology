"""Deterministic facts about a target repo, for bin/adopt.sh (and bin/init.sh).

Reads only `git` metadata and the tracked file list of <repo>; never writes.
Prints JSON with sorted keys on stdout. No timestamps and no absolute paths:
every path is repo-relative, `repo_name` is a bare name.

  python3 lib/detect_repo.py <repo>

Fields:
  languages           [{"name", "files"}], tracked-file count, desc, then name
  primary_language    first of languages, or null
  build_systems       every build system with a marker file, in a fixed order
  build_system        the one matching primary_language, else the first, or null
  shared_build_files  the build files that exist (collide between branches);
                      for a Gradle repo, lib/build_files.py's Gradle glob set
                      instead of its exact files, so every build file is covered
  base_ref            origin/HEAD, else the first of origin/main, origin/master,
                      origin/develop, main, master, develop; or null
  ticket_keys         KEY of KEY-123 in the last 500 commit subjects, kept at
                      >= 3 subjects, sorted by count desc then name
  tests_globs         {language: [globs]} for the detected languages
  has_remote          any git remote configured
  repo_name           origin URL's last segment (no .git), else the folder name
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import build_files as build_globs  # noqa: E402

EXTENSIONS = {
    ".kt": "kotlin",
    ".java": "java",
    ".swift": "swift",
    ".m": "objective-c", ".mm": "objective-c",
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go",
    ".sql": "sql",
    ".hs": "haskell",
    ".rs": "rust",
    ".rb": "ruby",
    ".cs": "csharp",
    ".scala": "scala",
    ".dart": "dart",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".sh": "shell",
}

# Build system -> (exact repo-relative files, regexes over repo-relative paths).
BUILD_SYSTEMS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("gradle", (
        "settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts",
        "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle", "app/build.gradle.kts",
        "gradlew", "gradlew.bat",
    ), (r"(^|/)(build|settings)\.gradle(\.kts)?$",)),
    ("maven", ("pom.xml",), ()),
    ("swiftpm", ("Package.swift", "Package.resolved"), ()),
    ("xcode", (), (r"(^|/)[^/]+\.xcodeproj/project\.pbxproj$",)),
    ("python", (
        "pyproject.toml", "setup.cfg", "setup.py", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock",
    ), (r"^requirements[^/]*\.txt$",)),
    ("node", (
        "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
        "pnpm-workspace.yaml", "bun.lockb",
    ), ()),
    ("go", ("go.mod", "go.sum", "go.work"), ()),
    ("cargo", ("Cargo.toml", "Cargo.lock"), ()),
]

LANGUAGE_BUILD = {
    "kotlin": ("gradle", "maven"),
    "java": ("gradle", "maven"),
    "swift": ("swiftpm", "xcode"),
    "objective-c": ("xcode",),
    "python": ("python",),
    "typescript": ("node",),
    "javascript": ("node",),
    "go": ("go",),
    "rust": ("cargo",),
}

TESTS_GLOBS = {
    "kotlin": ["**/src/androidTest/**", "**/src/test/**"],
    "java": ["**/src/androidTest/**", "**/src/test/**"],
    "swift": ["**/*Tests/**"],
    "python": ["**/*_test.py", "**/test_*.py", "tests/**"],
    "typescript": ["**/*.spec.ts", "**/*.spec.tsx", "**/*.test.ts", "**/*.test.tsx", "**/__tests__/**"],
    "javascript": ["**/*.spec.js", "**/*.test.js", "**/__tests__/**"],
    "go": ["**/*_test.go"],
    "rust": ["tests/**"],
    "haskell": ["test/**"],
    "ruby": ["spec/**", "test/**"],
    "scala": ["**/src/test/**"],
    "dart": ["test/**"],
}

BASE_REF_CANDIDATES = (
    ("origin/main", "refs/remotes/origin/main"),
    ("origin/master", "refs/remotes/origin/master"),
    ("origin/develop", "refs/remotes/origin/develop"),
    ("main", "refs/heads/main"),
    ("master", "refs/heads/master"),
    ("develop", "refs/heads/develop"),
)

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+)-\d+\b")
# Standard names shaped like a ticket key (UTF-8, ISO-8601, SHA-256...).
NOT_TICKET_KEYS = frozenset({"AES", "CVE", "ISO", "RFC", "RSA", "SHA", "UTF"})
TICKET_SUBJECTS = 500
TICKET_MIN_SIGHTINGS = 3


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout


def tracked_files(repo: Path) -> list[str]:
    code, out = _git(repo, "ls-files", "-z")
    if code != 0:
        return []
    return sorted(p for p in out.split("\0") if p)


def languages(files: list[str]) -> list[dict]:
    counts = Counter()
    for path in files:
        lang = EXTENSIONS.get(PurePosixPath(path).suffix.lower())
        if lang:
            counts[lang] += 1
    return [{"files": n, "name": name} for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def build_files(files: list[str]) -> dict[str, list[str]]:
    present = set(files)
    found: dict[str, list[str]] = {}
    for name, exact, patterns in BUILD_SYSTEMS:
        hits = {f for f in exact if f in present}
        for pattern in patterns:
            rx = re.compile(pattern)
            hits.update(f for f in files if rx.search(f))
        if hits:
            found[name] = sorted(hits)
    return found


def shared_build_files(found: dict[str, list[str]]) -> list[str]:
    """Exact detected files, except Gradle's, which are replaced by the full
    Gradle glob set (wrapper, verification, build-logic, every module)."""
    files = {f for name, hits in found.items() if name != "gradle" for f in hits}
    if "gradle" in found:
        files.update(build_globs.GRADLE_BUILD_GLOBS)
    return sorted(files)


def pick_build_system(found: dict[str, list[str]], primary: str | None) -> str | None:
    for name in LANGUAGE_BUILD.get(primary or "", ()):
        if name in found:
            return name
    for name, _, _ in BUILD_SYSTEMS:
        if name in found:
            return name
    return None


def base_ref(repo: Path) -> str | None:
    code, out = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip():
        return out.strip()
    for short, full in BASE_REF_CANDIDATES:
        code, _ = _git(repo, "rev-parse", "--verify", "--quiet", full + "^{commit}")
        if code == 0:
            return short
    return None


def ticket_keys(repo: Path) -> list[str]:
    code, out = _git(repo, "log", f"-n{TICKET_SUBJECTS}", "--format=%s")
    if code != 0:
        return []
    counts = Counter()
    for subject in out.splitlines():
        counts.update({key for key in TICKET_RE.findall(subject) if key not in NOT_TICKET_KEYS})
    kept = [(key, n) for key, n in counts.items() if n >= TICKET_MIN_SIGHTINGS]
    return [key for key, _ in sorted(kept, key=lambda kv: (-kv[1], kv[0]))]


def remotes(repo: Path) -> list[str]:
    code, out = _git(repo, "remote")
    return sorted(out.split()) if code == 0 else []


def repo_name(repo: Path, remote_names: list[str]) -> str:
    if "origin" in remote_names:
        code, out = _git(repo, "remote", "get-url", "origin")
        url = out.strip().rstrip("/")
        if code == 0 and url:
            name = re.split(r"[/:]", url)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name
    code, out = _git(repo, "rev-parse", "--show-toplevel")
    root = Path(out.strip()) if code == 0 and out.strip() else repo
    return root.resolve().name


def detect(repo: Path) -> dict:
    files = tracked_files(repo)
    langs = languages(files)
    primary = langs[0]["name"] if langs else None
    found = build_files(files)
    remote_names = remotes(repo)
    detected = {entry["name"] for entry in langs}
    return {
        "base_ref": base_ref(repo),
        "build_system": pick_build_system(found, primary),
        "build_systems": [name for name, _, _ in BUILD_SYSTEMS if name in found],
        "has_remote": bool(remote_names),
        "languages": langs,
        "primary_language": primary,
        "repo_name": repo_name(repo, remote_names),
        "shared_build_files": shared_build_files(found),
        "tests_globs": {lang: list(globs) for lang, globs in sorted(TESTS_GLOBS.items()) if lang in detected},
        "ticket_keys": ticket_keys(repo),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: detect_repo.py <repo>", file=sys.stderr)
        return 2
    repo = Path(argv[0])
    if not repo.is_dir():
        print(f"detect_repo: not a directory: {argv[0]}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(detect(repo.resolve()), sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
