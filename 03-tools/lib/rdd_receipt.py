#!/usr/bin/env python3
"""Review receipt (RDD, Receipt-Driven Development): freezes a candidate
by its TREE (git rev-parse HEAD^{tree}, never the commit), derives the
review tier with rdd_risk.py, binds each round artifact to the receipt by
sha256, and closes with a verdict that reads only the captures.

States: started -> captured -> finalized/{approved, rejected, escalated,
inconclusive}. A rejection allows ONE correction (start --supersedes) and no
more; a rebase that leaves the candidate files byte-identical inherits an
approved receipt (start --inherit-from), except at the high tier.

Usage:
    lib/rdd_receipt.py status --repo R [--base REF] [--change-card F]
    lib/rdd_receipt.py start --repo R --base REF --round-dir D [--change-card F]
        [--scope-glob G]* [--supersedes T] [--inherit-from T]
    lib/rdd_receipt.py capture --tree T --role ROLE --file ART [--repo R] [--handoff-to ROLE2] [--summary S]
    lib/rdd_receipt.py finalize --tree T
    lib/rdd_receipt.py acknowledge --tree T --decision D --reason "..." [--repo R]
    lib/rdd_receipt.py validate --receipt PATH

Receipts live at out/rdd/<tree_sha>.receipt.json (or $METODO_RDD_DIR).
Exit: 0 ok; 1 verdict other than approved or artifact FAIL; 2 usage, dirty
tree, or missing change card; 3 lineage or state violation.
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

from lib import baseline, engram_bridge, findings_schema_validator, handoff, rdd_risk, round_files, toolenv  # noqa: E402

KIT_ROOT = TOOLS_ROOT.parent
DEFAULT_AGENTS_DIR = KIT_ROOT / "01-roles" / "agents"
SCRIPT_ROLE_RE = re.compile(r"^script:[a-z0-9_-]+$")
ADVERSARY_ROLES = ("generic-challenger", "generic-blind-spot-adversary", "generic-judge")
REQUIRED_ROLES = {
    "exempt": [],
    "low": ["script:role_contract", "script:comment_gate", "script:docs_lint"],
    "medium": ["script:role_contract", "script:comment_gate", "script:docs_lint", "generic-challenger", "generic-verifier"],
    "high": ["script:role_contract", "script:comment_gate", "script:docs_lint", "generic-challenger",
             "generic-verifier", "generic-blind-spot-adversary", "generic-judge"],
}
DECISIONS = ("consent", "push-without-receipt", "accept-escalation", "unreviewed")


class ReceiptError(Exception):
    def __init__(self, message: str, exit_code: int, next_step: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.next_step = next_step


def receipts_dir() -> Path:
    return Path(os.environ.get("METODO_RDD_DIR") or (TOOLS_ROOT / "out" / "rdd"))


def receipt_path(tree: str) -> Path:
    return receipts_dir() / f"{tree}.receipt.json"


def load_receipt(tree: str) -> dict | None:
    path = receipt_path(tree)
    return baseline.load_json(path) if path.exists() else None


def save_receipt(receipt: dict) -> Path:
    path = receipt_path(receipt["tree_sha"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    baseline.write_json(tmp, receipt)
    os.replace(tmp, path)
    return path


def void_receipt(tree: str) -> Path | None:
    path = receipt_path(tree)
    if not path.exists():
        return None
    n = 1
    while (target := receipts_dir() / f"{tree}.void-{n}.json").exists():
        n += 1
    os.replace(path, target)
    return target


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def tree_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD^{tree}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def budgets_from_contracts(agents_dir: Path) -> dict:
    roles = {}
    for contract_path in sorted(Path(agents_dir).glob("generic-*.contract.json")):
        contract = baseline.load_json(contract_path)
        roles[contract.get("agent", contract_path.stem)] = {
            "max_context_tokens": contract.get("max_context_tokens"),
            "max_tool_calls": contract.get("max_tool_calls"),
            "max_turns": contract.get("max_turns"),
        }
    return roles


def load_config(config_path: Path | None) -> dict:
    path = config_path or (TOOLS_ROOT / "config" / "project.json")
    return baseline.load_json(path) if path.exists() else {}


def _resolve_artifact(receipt: dict, artifact: str) -> Path:
    if artifact.startswith("~/"):
        return Path(artifact).expanduser()
    if artifact.startswith("/"):
        return Path(artifact)
    return Path(receipt["round_dir"]).expanduser() / artifact


# ----------------------------------------------------------------------------- status

def status(repo: Path, base: str | None = None, card_path: Path | None = None, config: dict | None = None) -> dict:
    config = config or {}
    dirty = baseline.is_repo_dirty(repo)
    tree = tree_sha(repo)
    receipt = load_receipt(tree)
    result = {"tree_sha": tree, "repo_dirty": dirty, "receipt": None, "next": "COMMIT_FIRST" if dirty else "START"}
    if receipt is not None:
        result["receipt"] = {k: receipt[k] for k in ("state", "verdict", "correction_index", "round_dir")}
        result["receipt"]["tier"] = receipt["risk"]["tier"]
        result["receipt"]["consent"] = receipt["risk"]["consent"]
        if not dirty:
            result["next"] = _next_step(receipt)
    elif base and not dirty:
        result["risk_preview"] = rdd_risk.derive(rdd_risk.gather(repo, base, card_path, config), config)
    open_receipts = []
    for path in sorted(receipts_dir().glob("*.receipt.json")):
        other = baseline.load_json(path)
        if other["state"] != "finalized":
            open_receipts.append({"tree_sha": other["tree_sha"], "state": other["state"], "round_dir": other["round_dir"]})
    result["open_receipts"] = open_receipts
    return result


def _next_step(receipt: dict) -> str:
    if receipt["state"] != "finalized":
        return "CAPTURE_OR_FINALIZE"
    return {
        "approved": "PUSH_THEN_ACKNOWLEDGE",
        "rejected": "START_SUPERSEDES" if receipt["correction_index"] == 0 else "ESCALATE",
        "escalated": "ACKNOWLEDGE_ACCEPT_ESCALATION",
        "inconclusive": "START_AGAIN_SAME_TREE",
    }[receipt["verdict"]]


# ----------------------------------------------------------------------------- start

def start(repo: Path, base: str, round_dir: Path, card_path: Path | None = None, scope_globs: list[str] | None = None,
          supersedes: str | None = None, inherit_from: str | None = None, config: dict | None = None,
          agents_dir: Path | None = None) -> dict:
    config = config or {}
    repo = Path(repo).resolve()
    if baseline.is_repo_dirty(repo):
        raise ReceiptError("the tree has uncommitted changes: a receipt binds to a committed tree", 2, "COMMIT_FIRST")
    tree = tree_sha(repo)
    round_files.assert_write_allowed(Path(round_dir) / "x", repo, config)

    existing = load_receipt(tree)
    if existing is not None:
        if existing["state"] != "finalized" or existing["verdict"] == "approved":
            return existing
        if existing["verdict"] == "inconclusive":
            void_receipt(tree)
        else:
            raise ReceiptError(f"this tree already has a {existing['verdict']} receipt", 3, _next_step(existing))

    inputs = rdd_risk.gather(repo, base, card_path, config)
    risk = rdd_risk.derive(inputs, config)
    if risk["tier"] in ("medium", "high"):
        if card_path is None:
            raise ReceiptError(f"{risk['tier']} tier: a change card is required (--change-card)", 2, "WRITE_CHANGE_CARD")
        if inputs.get("card_verdict") != "PASS":
            raise ReceiptError("the change card does not validate (change_card_validator FAIL): no valid card, no receipt", 2, "FIX_CHANGE_CARD")

    card = None
    if card_path is not None:
        card = {
            "path": round_files.portable_path(Path(card_path), Path(round_dir), repo),
            "sha256": sha256_file(card_path),
            "verdict": inputs["card_verdict"],
            "routing": inputs["routing"],
        }

    base_sha = _git(repo, "rev-parse", f"{base}^{{commit}}")
    versions = toolenv.tool_versions(TOOLS_ROOT)
    receipt = baseline.base_envelope(TOOLS_ROOT, _git(repo, "rev-parse", "HEAD"), versions, False)
    receipt.update({
        "tree_sha": tree,
        "base_ref": base,
        "base_sha": base_sha,
        "merge_base": _git(repo, "merge-base", base, "HEAD"),
        "change_card": card,
        "risk": risk,
        "touched_paths": inputs["touched_paths"],
        "diff_stats": {"files": len(inputs["touched_paths"]), "added": inputs["added"], "removed": inputs["removed"]},
        "scope_globs": sorted(scope_globs or []),
        "budget": {"roles": budgets_from_contracts(agents_dir or (DEFAULT_AGENTS_DIR if DEFAULT_AGENTS_DIR.is_dir() else repo / ".claude" / "agents"))},
        "round_dir": round_files.portable_path(Path(round_dir), repo),
        "state": "started",
        "captures": [],
        "correction_index": 0,
        "supersedes": None,
        "superseded_by": None,
        "inherited_from": None,
        "verdict": None,
        "verdict_reasons": [],
        "owner_ack": None,
    })

    if supersedes:
        _apply_supersedes(receipt, supersedes)
    if inherit_from:
        _apply_inherit(receipt, inherit_from, repo)
    if risk["tier"] == "exempt" and receipt["verdict"] is None:
        receipt["state"] = "finalized"
        receipt["verdict"] = "approved"
        receipt["verdict_reasons"] = ["exempt tier: " + "; ".join(risk["reasons"])]

    save_receipt(receipt)
    return receipt


def _apply_supersedes(receipt: dict, old_tree: str) -> None:
    old = load_receipt(old_tree)
    if old is None:
        raise ReceiptError(f"--supersedes: no receipt exists for {old_tree}", 3)
    if old["verdict"] != "rejected":
        raise ReceiptError("--supersedes only applies over a rejected receipt", 3, _next_step(old))
    if old["correction_index"] != 0:
        raise ReceiptError("the only correction was already used: a second rejection escalates to the owner", 3, "ESCALATE")
    if (old.get("change_card") or {}).get("sha256") != (receipt.get("change_card") or {}).get("sha256"):
        raise ReceiptError("--supersedes requires the same change card (sha256 differs): a scope change is a new lineage", 3)
    receipt["correction_index"] = 1
    receipt["supersedes"] = old_tree
    old["superseded_by"] = receipt["tree_sha"]
    save_receipt(old)


def _apply_inherit(receipt: dict, old_tree: str, repo: Path) -> None:
    old = load_receipt(old_tree)
    if old is None or old["verdict"] != "approved":
        raise ReceiptError("--inherit-from only works from an approved receipt", 3)
    if receipt["risk"]["tier"] == "high" or old["risk"]["tier"] == "high":
        raise ReceiptError("the high tier never inherits: the round repeats", 3, "START")
    if old["touched_paths"]:
        diff = _git(repo, "diff", "--name-only", old_tree, receipt["tree_sha"], "--", *old["touched_paths"])
        if diff.strip():
            raise ReceiptError("--inherit-from: the candidate files changed: " + diff.replace("\n", ", "), 3, "START")
    receipt["inherited_from"] = old_tree
    receipt["state"] = "finalized"
    receipt["verdict"] = "approved"
    receipt["verdict_reasons"] = [f"inherited: candidate files byte-identical to {old_tree}"]


# ----------------------------------------------------------------------------- capture

def _summarize(schema_name: str | None, document) -> dict:
    if not isinstance(document, dict):
        return {}
    if schema_name == "findings":
        counts: dict[str, int] = {}
        for f in document.get("findings", []):
            counts[f.get("verdict", "?")] = counts.get(f.get("verdict", "?"), 0) + 1
        return {"findings": counts}
    if schema_name == "blindspots":
        counts = {}
        for b in document.get("blind_spots", []):
            counts[b.get("state", "?")] = counts.get(b.get("state", "?"), 0) + 1
        return {"blind_spots": counts}
    if schema_name == "verdict":
        counts = {}
        for r in document.get("rulings", []):
            counts[r.get("ruling", "?")] = counts.get(r.get("ruling", "?"), 0) + 1
        return {"rulings": counts}
    if schema_name == "claims":
        return {"claims": len(document.get("claims", []))}
    summary = {}
    for key in ("verdict", "pass", "applied", "escalated"):
        if key in document:
            summary[key] = document[key]
    return summary


def capture(tree: str, role: str, artifact_path: Path, repo: Path | None = None, handoff_to: str | None = None,
            summary_text: str | None = None, config: dict | None = None) -> tuple[dict, dict]:
    receipt = load_receipt(tree)
    if receipt is None:
        raise ReceiptError(f"no receipt exists for tree {tree}", 2, "START")
    if receipt["state"] == "finalized":
        raise ReceiptError("the receipt is already closed", 3, _next_step(receipt))
    if repo is not None and tree_sha(Path(repo)) != tree:
        raise ReceiptError("the repo tree no longer matches the receipt: open a new receipt", 3, "START")
    if receipt["change_card"] is not None:
        card_file = _resolve_artifact(receipt, receipt["change_card"]["path"])
        if not card_file.exists() or sha256_file(card_file) != receipt["change_card"]["sha256"]:
            raise ReceiptError("the change card changed under the open receipt: finalize will mark it inconclusive", 3, "FINALIZE")

    if SCRIPT_ROLE_RE.match(role):
        role_name, schema_name = role, None
    else:
        role_name = round_files.normalize_role(role)
        schema_name = round_files.ROLE_SCHEMA[role_name]
    if receipt["risk"]["tier"] == "high" and role_name in ADVERSARY_ROLES and receipt["risk"]["consent"] != "granted":
        raise ReceiptError("high tier without owner consent: acknowledge --decision consent first", 3, "ACKNOWLEDGE_CONSENT")

    artifact_path = Path(artifact_path)
    document = json.loads(artifact_path.read_text(encoding="utf-8"))
    if schema_name is not None:
        validation = findings_schema_validator.validate(document, round_files.load_schema(schema_name))
        if validation["verdict"] == "FAIL":
            raise ReceiptError("invalid artifact for " + schema_name + ": " + "; ".join(validation["errors"]), 1)
        validation_verdict = validation["verdict"]
    else:
        validation_verdict = "INCOMPLETE" if isinstance(document, dict) and document.get("truncated") is True else "PASS"

    round_dir = Path(receipt["round_dir"]).expanduser()
    handoff_ref = None
    if handoff_to:
        to_role = round_files.normalize_role(handoff_to)
        topic = f"to-{round_files.short_role(to_role)}"
        path, _ = handoff.write_handoff(
            Path(repo) if repo else round_dir, round_dir, role_name if not SCRIPT_ROLE_RE.match(role_name) else "generic-verifier",
            to_role, topic, artifact_path, summary_text or f"{role_name} output captured", [], project_config=config)
        handoff_ref = round_files.portable_path(path, round_dir)

    entry = {
        "seq": len(receipt["captures"]) + 1,
        "role": role_name,
        "artifact": round_files.portable_path(artifact_path, round_dir, Path(repo) if repo else round_dir),
        "sha256": sha256_file(artifact_path),
        "schema": schema_name,
        "validation": validation_verdict,
        "summary": _summarize(schema_name, document),
        "handoff": handoff_ref,
    }
    receipt["captures"].append(entry)
    receipt["state"] = "captured"
    save_receipt(receipt)
    return receipt, entry


# ----------------------------------------------------------------------------- finalize

def _last_by_role(receipt: dict) -> dict:
    last = {}
    for entry in receipt["captures"]:
        last[entry["role"]] = entry
    return last


def _load_capture_doc(receipt: dict, entry: dict):
    path = _resolve_artifact(receipt, entry["artifact"])
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def finalize(tree: str) -> dict:
    receipt = load_receipt(tree)
    if receipt is None:
        raise ReceiptError(f"no receipt exists for tree {tree}", 2, "START")
    if receipt["state"] == "finalized":
        raise ReceiptError("the receipt is already closed", 3, _next_step(receipt))

    reasons: list[str] = []
    verdict = None
    last = _last_by_role(receipt)

    if receipt["change_card"] is not None:
        card_file = _resolve_artifact(receipt, receipt["change_card"]["path"])
        if not card_file.exists() or sha256_file(card_file) != receipt["change_card"]["sha256"]:
            verdict, reasons = "inconclusive", ["change card changed under the receipt"]

    incomplete = [e["role"] for e in last.values() if e["validation"] == "INCOMPLETE"]
    if verdict is None and incomplete:
        verdict, reasons = "inconclusive", ["truncated captures: " + ", ".join(sorted(incomplete))]

    missing = [r for r in REQUIRED_ROLES[receipt["risk"]["tier"]] if r not in last]
    if verdict is None and missing:
        verdict, reasons = "inconclusive", ["required roles missing: " + ", ".join(missing)]

    if verdict is None:
        verifier = last.get("generic-verifier")
        if verifier is not None:
            v = verifier["summary"].get("verdict")
            if v == "FAIL":
                verdict, reasons = "rejected", ["verifier FAIL"]
            elif v == "INCONCLUSIVE":
                verdict, reasons = "inconclusive", ["verifier INCONCLUSIVE"]

    if verdict is None:
        rulings = {}
        judge_entry = last.get("generic-judge")
        if judge_entry is not None:
            judge_doc = _load_capture_doc(receipt, judge_entry) or {}
            rulings = {r["finding_id"]: r["ruling"] for r in judge_doc.get("rulings", [])}
        challenger = last.get("generic-challenger")
        if challenger is not None:
            doc = _load_capture_doc(receipt, challenger) or {}
            broken = [f["id"] for f in doc.get("findings", []) if f.get("verdict") == "ROTO" and rulings.get(f["id"]) != "REFUTED"]
            if broken:
                verdict, reasons = "rejected", ["ROTO not refuted: " + ", ".join(broken)]
        if verdict is None:
            unresolved = sorted(fid for fid, r in rulings.items() if r in ("UNRESOLVED", "NEEDS_BENCH"))
            if unresolved:
                verdict, reasons = "escalated", ["judge left unresolved: " + ", ".join(unresolved)]
        if verdict is None:
            blind = last.get("generic-blind-spot-adversary")
            if blind is not None:
                doc = _load_capture_doc(receipt, blind) or {}
                open_spots = [b["id"] for b in doc.get("blind_spots", [])
                              if b.get("state") == "ABIERTO CON DUEÑO" and rulings.get(b["id"]) not in ("CONFIRMED", "REFUTED")]
                if open_spots:
                    verdict, reasons = "escalated", ["ABIERTO CON DUEÑO without a ruling: " + ", ".join(open_spots)]
        if verdict is None and receipt["risk"]["owner_gate"]:
            verdict, reasons = "escalated", ["owner gate: shared build files touched"]

    if verdict is None:
        verdict, reasons = "approved", ["all required captures present and clean"]

    receipt["state"] = "finalized"
    receipt["verdict"] = verdict
    receipt["verdict_reasons"] = reasons
    save_receipt(receipt)
    _remember(receipt)
    return receipt


def _remember(receipt: dict) -> bool:
    """Indexes the closed receipt in engram. The receipt file stays the audit
    trail; this is only so a later session can find it without knowing the
    tree by heart."""
    tree = receipt["tree_sha"]
    body = "verdict: {}\nreasons: {}\nround: {}\ntier: {}\nreceipt: {}".format(
        receipt["verdict"], "; ".join(receipt["verdict_reasons"]), receipt.get("round_dir"),
        (receipt.get("risk") or {}).get("tier"), receipts_dir() / f"{tree}.receipt.json")
    return engram_bridge.save(f"receipt {tree[:12]} {receipt['verdict']}", body,
                              kind="decision", topic_key=f"metodo/receipt/{tree}")


# ----------------------------------------------------------------------------- acknowledge / validate

def acknowledge(tree: str, decision: str, reason: str, repo: Path | None = None, round_dir: Path | None = None) -> dict:
    if decision not in DECISIONS:
        raise ReceiptError(f"unknown decision: {decision}", 2)
    receipt = load_receipt(tree)
    if receipt is None:
        if decision != "unreviewed" or repo is None:
            raise ReceiptError(f"no receipt exists for tree {tree}", 2, "START")
        receipt = _unreviewed_receipt(Path(repo), tree, round_dir)
    if decision == "consent":
        if receipt["risk"]["tier"] != "high":
            raise ReceiptError("consent only applies to the high tier", 2)
        receipt["risk"]["consent"] = "granted"
    else:
        receipt["owner_ack"] = {"decision": decision, "reason": reason}
    save_receipt(receipt)
    return receipt


def _unreviewed_receipt(repo: Path, tree: str, round_dir: Path | None) -> dict:
    versions = toolenv.tool_versions(TOOLS_ROOT)
    receipt = baseline.base_envelope(TOOLS_ROOT, _git(repo, "rev-parse", "HEAD"), versions, baseline.is_repo_dirty(repo))
    receipt.update({
        "tree_sha": tree, "base_ref": "HEAD", "base_sha": receipt["repo_sha"], "merge_base": receipt["repo_sha"],
        "change_card": None,
        "risk": {"tier": "exempt", "reasons": ["owner declared the candidate unreviewed"], "lenses": [], "lens_focus": None,
                 "owner_gate": False, "consent": "n/a", "inputs": {}},
        "touched_paths": [], "diff_stats": {"files": 0, "added": 0, "removed": 0}, "scope_globs": [],
        "budget": {"roles": {}}, "round_dir": round_files.portable_path(round_dir, repo) if round_dir else "",
        "state": "finalized", "captures": [], "correction_index": 0, "supersedes": None, "superseded_by": None,
        "inherited_from": None, "verdict": "approved", "verdict_reasons": ["owner declared the candidate unreviewed"],
        "owner_ack": None,
    })
    return receipt


def validate_receipt(path: Path) -> dict:
    receipt = baseline.load_json(path)
    result = findings_schema_validator.validate(receipt, round_files.load_schema("receipt"))
    errors = list(result["errors"])
    for entry in receipt.get("captures", []):
        artifact = _resolve_artifact(receipt, entry["artifact"])
        if not artifact.exists():
            errors.append(f"capture {entry['seq']}: artifact missing {entry['artifact']}")
        elif sha256_file(artifact) != entry["sha256"]:
            errors.append(f"capture {entry['seq']}: sha256 mismatch for {entry['artifact']}")
    return {"verdict": "FAIL" if errors else "PASS", "errors": sorted(errors)}


# ----------------------------------------------------------------------------- CLI

def _print(obj) -> None:
    print(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="config/project.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status"); p.add_argument("--repo", required=True); p.add_argument("--base"); p.add_argument("--change-card")
    p = sub.add_parser("start"); p.add_argument("--repo", required=True); p.add_argument("--base", required=True)
    p.add_argument("--round-dir", required=True); p.add_argument("--change-card"); p.add_argument("--scope-glob", action="append", default=[])
    p.add_argument("--supersedes"); p.add_argument("--inherit-from"); p.add_argument("--agents-dir")
    p = sub.add_parser("capture"); p.add_argument("--tree", required=True); p.add_argument("--role", required=True)
    p.add_argument("--file", required=True); p.add_argument("--repo"); p.add_argument("--handoff-to"); p.add_argument("--summary")
    p = sub.add_parser("finalize"); p.add_argument("--tree", required=True)
    p = sub.add_parser("acknowledge"); p.add_argument("--tree", required=True); p.add_argument("--decision", required=True, choices=DECISIONS)
    p.add_argument("--reason", required=True); p.add_argument("--repo"); p.add_argument("--round-dir")
    p = sub.add_parser("validate"); p.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)

    try:
        if args.command == "status":
            _print(status(Path(args.repo).resolve(), args.base, Path(args.change_card) if args.change_card else None, config))
            return 0
        if args.command == "start":
            receipt = start(Path(args.repo), args.base, Path(args.round_dir), Path(args.change_card) if args.change_card else None,
                            args.scope_glob, args.supersedes, args.inherit_from, config,
                            Path(args.agents_dir) if args.agents_dir else None)
            _print(receipt)
            return 0
        if args.command == "capture":
            receipt, entry = capture(args.tree, args.role, Path(args.file), Path(args.repo).resolve() if args.repo else None,
                                     args.handoff_to, args.summary, config)
            _print({"capture": entry, "state": receipt["state"], "tree_sha": receipt["tree_sha"]})
            return 0
        if args.command == "finalize":
            receipt = finalize(args.tree)
            _print({"tree_sha": receipt["tree_sha"], "verdict": receipt["verdict"], "verdict_reasons": receipt["verdict_reasons"],
                    "next": _next_step(receipt)})
            return 0 if receipt["verdict"] == "approved" else 1
        if args.command == "acknowledge":
            receipt = acknowledge(args.tree, args.decision, args.reason, Path(args.repo).resolve() if args.repo else None,
                                  Path(args.round_dir) if args.round_dir else None)
            _print({"tree_sha": receipt["tree_sha"], "owner_ack": receipt["owner_ack"], "consent": receipt["risk"]["consent"]})
            return 0
        if args.command == "validate":
            result = validate_receipt(Path(args.receipt))
            _print(result)
            return 0 if result["verdict"] == "PASS" else 1
    except ReceiptError as exc:
        _print({"error": str(exc), "next": exc.next_step})
        return exc.exit_code
    except (PermissionError, ValueError) as exc:
        _print({"error": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
