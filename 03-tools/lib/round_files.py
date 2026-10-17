"""What a round's files share: NNN numbering, the role's short name,
role -> output schema map, schema loading, and the write guard (never
inside the analyzed repo nor over a shared build file). Used by
handoff.py, round_output.py, rdd_receipt.py, and the MCP server; it lives
on its own so none of them reimplements it.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib import baseline
from lib import role_contract_validator as rcv

TOOLS_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = TOOLS_ROOT / "schemas"

ROLES = (
    "generic-cartographer", "generic-proposer", "generic-challenger",
    "generic-blind-spot-adversary", "generic-judge", "generic-verifier",
    "generic-boundary-reviewer", "generic-style-reviewer", "generic-comment-gate",
    "generic-mechanic", "generic-human-reviewer",
)

# A role with no schema of its own cannot write with output_write: it is left
# out on purpose, so the absence is noticed instead of accepting plain prose.
ROLE_SCHEMA = {
    "generic-cartographer": "claims",
    "generic-proposer": "proposer-output",
    "generic-challenger": "findings",
    "generic-blind-spot-adversary": "blindspots",
    "generic-judge": "verdict",
    "generic-verifier": "verification",
    "generic-boundary-reviewer": "boundary-reviewer-output",
    "generic-style-reviewer": "style-reviewer-output",
    "generic-comment-gate": "comment-gate-output",
    "generic-mechanic": "mechanic-output",
    "generic-human-reviewer": "human-reviewer-output",
}

SCHEMA_NAMES = (
    "findings", "blindspots", "claims", "verdict", "handoff", "brief", "receipt", "verification",
    "proposer-output", "boundary-reviewer-output", "style-reviewer-output",
    "comment-gate-output", "mechanic-output", "human-reviewer-output",
)

SEQ_RE = re.compile(r"^(\d{3})-")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def short_role(role: str) -> str:
    return role[len("generic-"):] if role.startswith("generic-") else role


def normalize_role(role: str) -> str:
    """Accepts 'judge' and 'generic-judge' as the same role; returns the
    long name or raises ValueError if it is not a kit role."""
    candidate = role if role.startswith("generic-") else f"generic-{role}"
    if candidate not in ROLES:
        raise ValueError(f"unknown role: {role}")
    return candidate


def schema_path(name: str) -> Path:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema: {name}")
    return SCHEMAS_DIR / f"{name}.schema.json"


def load_schema(name: str) -> dict:
    return baseline.load_json(schema_path(name))


def next_seq(round_dir: Path) -> int:
    """Next free NNN in the round directory: the highest existing numeric
    prefix plus one. An empty directory starts at 1 (000 is reserved for
    the context pack)."""
    highest = 0
    if round_dir.is_dir():
        for child in round_dir.iterdir():
            match = SEQ_RE.match(child.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def numbered_name(seq: int, role: str, topic: str, suffix: str = "json") -> str:
    return f"{seq:03d}-{short_role(role)}-{topic}.{suffix}"


def portable_path(path: Path, *anchors: Path) -> str:
    """Path with no absolute home inside a payload: relative to the first
    anchor that contains it, and if none contains it, with ~ instead of home."""
    resolved = Path(path).resolve()
    for anchor in anchors:
        try:
            return resolved.relative_to(Path(anchor).resolve()).as_posix()
        except ValueError:
            continue
    home = Path.home().resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return resolved.as_posix()


def assert_write_allowed(target: Path, repo: Path | None, project_config: dict | None = None) -> None:
    """03-tools rule: never write inside the analyzed repo, and never over a
    shared build file. Raises PermissionError."""
    resolved = Path(target).resolve()
    if repo is not None:
        repo_resolved = Path(repo).resolve()
        try:
            rel = resolved.relative_to(repo_resolved).as_posix()
        except ValueError:
            rel = None
        if rel is not None:
            raise PermissionError(f"write inside the analyzed repo rejected: {rel}")
    for pattern in rcv.always_forbidden_patterns(project_config):
        if rcv._match_any(resolved.name, [pattern]) or rcv._match_any(resolved.as_posix(), [pattern]):
            raise PermissionError(f"write over an always-forbidden path rejected: {resolved.name} ({pattern})")
