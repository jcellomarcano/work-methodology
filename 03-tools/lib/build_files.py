"""Shared build files: the files every lineage shares and only the owner
edits (00-principles/methodology.md paragraph 4). One default set and one
matcher, so an entry of `shared_build_files` means the same thing in every
consumer: hooks/guard_paths.py (Claude Code, and pi through the same hook),
lib/role_contract_validator.py, lib/rdd_risk.py and lib/test_sectors.py.

Every entry is a glob; an exact path is a glob without wildcards and keeps
matching only itself. Matching is fnmatch over the repo-relative POSIX path
(`*` also crosses `/`), plus `**/X` matching an X at the repo root. Two
hardenings, both only ever widening a match: the path is normalized first
(`./gradlew`, `app/../gradlew`, a Windows `\\`), and the comparison ignores
case, because on a case-insensitive filesystem `GRADLEW` is `gradlew`.
"""
from __future__ import annotations

import fnmatch
import posixpath

# Used when config/project.json is absent or its shared_build_files is
# empty, and emitted by lib/detect_repo.py for a detected Gradle repo: every
# file that configures or bootstraps a Gradle build, at any depth (included
# builds and nested modules too).
GRADLE_BUILD_GLOBS = (
    "**/*.gradle",                              # settings.gradle, build.gradle, script plugins, any module
    "**/*.gradle.kts",                          # the Kotlin DSL variants
    "**/gradle.properties",                     # root and subproject properties
    "**/gradlew",                               # Wrapper scripts
    "**/gradlew.bat",
    "**/gradle/wrapper/**",                     # gradle-wrapper.jar, gradle-wrapper.properties
    "**/gradle/*.versions.toml",                # version catalogs
    "**/gradle/verification-metadata.xml",      # dependency verification
    "**/gradle/verification-keyring.*",
    "**/gradle/gradle-daemon-jvm.properties",   # daemon JVM criteria
    "**/gradle.lockfile",                       # dependency locking
    "**/settings-gradle.lockfile",
    "**/gradle/dependency-locks/**",
    "**/buildSrc/**",                           # build logic
    "**/build-logic/**",
)
DEFAULT_SHARED_BUILD_FILES = GRADLE_BUILD_GLOBS


def normalize(path: str) -> str:
    """Repo-relative POSIX form: separators unified, `.` and `..` folded."""
    text = str(path).replace("\\", "/")
    if not text:
        return text
    text = posixpath.normpath(text)
    return "" if text == "." else text


def glob_match(path: str, pattern: str) -> bool:
    candidate = normalize(path).casefold()
    pattern = str(pattern).casefold()
    if fnmatch.fnmatchcase(candidate, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(candidate, pattern[3:])


def first_match(path: str, patterns) -> str | None:
    """The first pattern that matches `path`, or None."""
    for pattern in patterns:
        if glob_match(path, pattern):
            return pattern
    return None


def shared_build_files(config: dict | None) -> list[str]:
    """config's shared_build_files, or the Gradle default when there is no
    config or the field is empty."""
    configured = (config or {}).get("shared_build_files") if isinstance(config, dict) else None
    return list(configured or DEFAULT_SHARED_BUILD_FILES)
