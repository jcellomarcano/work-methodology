#!/usr/bin/env python3
"""Bench collector: measures every Claude Code session of a repo inside its instance.

Subcommands (bin/bench.sh is the wrapper):
  collect <repo>                      measure new or changed sessions, rewrite the aggregate
  report  <repo>                      collect, then git_metrics, kit_telemetry and phase1_report
  status  <repo>                      what is measured so far, without measuring anything
  adopt   <repo>                      record the install timestamp once (first install wins)
  ab <repo> <run|judge|report> [...]  forward to <instance>/bench/lib/bench_cli.py as ab, judge, report

The instance is --tools, else $METODO_TOOLS, else the parent of this lib/ dir
(the convention of hooks/_common.py). The measuring code is the instance's own
copy of 08-benchmark/lib (bench/lib, put there by bin/sync-instance.sh), so
one source of truth serves the kit and every instance.

Sources for collect: the queue out/bench/queue/<session_id>.json written by
the SessionEnd hook ({"session_id", "transcript_path"}) and a sweep of the
repo's transcript dir, named by transcript_metrics.transcript_dir (root
${CLAUDE_PROJECTS_DIR:-~/.claude/projects}). A queued path is measured only
when it resolves inside that root and is <session_id>.jsonl; any other item
is consumed and counted as failed, and its path is never opened. A session
is measured again only when its transcript is newer than its row, or when the
row's `schema_version` is not the analyzer's (a row without one included).
During report, a git_metrics or kit_telemetry that fails takes its extract of
an earlier run with it, so the report shows that input as failed, not as stale.

Everything lands under <instance>/out/bench/: sessions/<id>.json (one row per
session: the analyzer's record plus the `schema_version` that produced it),
data/sessions.json (the transcript_metrics payload shape), queue/,
adoption.json, report/, .lock. Deterministic: same transcripts, same bytes.
Private: rows carry counts and lengths only, never prompt or reply text, and
neither the files nor the printed summaries carry an absolute path (report
prints only the path of its own report). The rows do keep the payload's
`project_dir`: the transcript directory name, which encodes the repo path.

Exit: 0 ok (collect also when single sessions failed: they are counted, and
when another collect holds the lock), 1 the phase 1 report failed, 2 usage or
setup error. A file system error of collect, report, status or adopt is a
setup error: one line on stderr that names the subcommand, the error class
and the kind of path that failed (<instance>/out/bench only when the path is
in it, else the transcripts root, the instance config or another path), never
the path itself or a traceback. `ab` exits with the code of the forwarded
command.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The measuring modules are imported from <instance>/bench/lib: leave no bytecode next to them.
sys.dont_write_bytecode = True

SUBCOMMANDS = ("collect", "report", "status", "adopt", "ab")
# bench.sh ab <repo> <word>: the word and the bench_cli.py subcommand it becomes.
AB_WORDS = {"run": "ab", "judge": "judge", "report": "report"}
USAGE = ("usage: bench.sh collect|report|status|adopt <repo> [--tools <instance>]\n"
         "       bench.sh ab <repo> <run|judge|report> [args] [--tools <instance>]")
SYNC_HINT = "run 03-tools/bin/sync-instance.sh <instance> from the kit first"
# The subcommands that only read and write the instance: a file system error there is a setup error (exit 2).
FS_COMMANDS = ("collect", "report", "status", "adopt")
# What the one-line file system error says, by the kind of path that failed: never the path itself.
FS_HINTS = {
    "bench": "<instance>/out/bench must be a writable directory",
    "transcripts": "the transcripts root must be a readable directory",
    "config": "the instance config must be readable",
    "other": "another path failed, not <instance>/out/bench, the transcripts root or the instance config",
    "unnamed": "the error names no path",
}
# The report steps whose output is an extract under data/: a failed step must not leave an earlier one behind.
EXTRACTS = {"git_metrics": "git.json", "kit_telemetry": "kit.json"}


class BenchError(Exception):
    """A usage or setup problem: printed on stderr, exit 2."""


# ---- paths -----------------------------------------------------------------

def resolve_instance(tools: str | None) -> Path:
    raw = tools or os.environ.get("METODO_TOOLS") or Path(__file__).resolve().parent.parent
    instance = Path(raw).expanduser().resolve()
    if not instance.is_dir():
        raise BenchError("bench: the instance is not a directory (check --tools or METODO_TOOLS)")
    return instance


def bench_out(instance: Path) -> Path:
    return instance / "out" / "bench"


def config_path(instance: Path) -> Path:
    """The config file hooks/_common.load_config reads."""
    return Path(os.environ.get("METODO_PROJECT_CONFIG") or instance / "config" / "project.json")


def load_transcript_metrics(instance: Path):
    lib = instance / "bench" / "lib"
    if not (lib / "transcript_metrics.py").is_file():
        raise BenchError(f"bench: the instance has no bench/lib/transcript_metrics.py; {SYNC_HINT}")
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    import transcript_metrics  # noqa: E402 - the instance's own copy of 08-benchmark/lib
    return transcript_metrics


# ---- small helpers ---------------------------------------------------------

def _dump(payload) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _unlink_if_unchanged(path: Path, mtime_ns: int) -> None:
    """Remove a queue item unless the hook rewrote it while it was being measured."""
    try:
        if path.stat().st_mtime_ns == mtime_ns:
            path.unlink()
    except OSError:
        pass


def _iso_ms(when: dt.datetime) -> str:
    """Same shape as transcript_metrics timestamps, so the report can compare them as strings."""
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _queue_files(out: Path) -> list[Path]:
    queue = out / "queue"
    return sorted(queue.glob("*.json")) if queue.is_dir() else []


# ---- collect ---------------------------------------------------------------

def _queued_transcript(raw: str, sid: str, root: str) -> tuple[Path | None, str | None]:
    """The transcript a queue item may name, or why it is refused. The queue is a
    folder anyone who can write the instance can fill, so a queued path is used
    only when it resolves inside the transcripts root and is <session_id>.jsonl.
    It is resolved first and never opened or looked at before it passes."""
    try:
        resolved = os.path.realpath(raw)
        inside = resolved != root and os.path.commonpath([root, resolved]) == root
    except (OSError, ValueError):  # a path no file system call accepts, for example with a null byte
        inside = False
    if not inside:
        return None, "queued path outside the transcripts root"
    path = Path(resolved)
    if path.suffix != ".jsonl" or path.stem != sid:
        return None, "queued path is not <session_id>.jsonl"
    return path, None


def _candidates(tdir: Path, out: Path, failures: list) -> tuple[dict, list]:
    """session_id -> transcript path, plus the queue items to drop once measured."""
    root = os.path.realpath(tdir.parent)  # the transcripts root, resolved: /var is a symlink on macOS
    found = {}
    if tdir.is_dir():
        for f in sorted(tdir.glob("*.jsonl")):
            found[f.stem] = f
    consumed = []
    for q in _queue_files(out):
        try:
            mtime_ns = q.stat().st_mtime_ns
            item = json.loads(q.read_text(encoding="utf-8"))
            sid, raw = str(item["session_id"]), item["transcript_path"]
            if not isinstance(raw, str):
                raise TypeError("transcript_path must be a string")
        except (OSError, ValueError, KeyError, TypeError):
            failures.append({"reason": "bad queue item", "session_id": q.stem})
            q.unlink(missing_ok=True)
            continue
        path, refused = _queued_transcript(raw, sid, root) if raw else (None, None)
        if refused:  # named after the queue file: the item is untrusted, its session_id may be anything
            failures.append({"reason": refused, "session_id": q.stem})
            q.unlink(missing_ok=True)
            continue
        if path is not None and path.is_file():
            found.setdefault(sid, path)
        elif sid not in found:  # a session the sweep found needs no path from the queue
            failures.append({"reason": "transcript missing", "session_id": sid})
            q.unlink(missing_ok=True)
            continue
        consumed.append((q, mtime_ns))
    return found, consumed


def _row_version(row: Path):
    """The analyzer version that wrote a stored row; None for an unreadable row or one from before rows carried it."""
    record = _read_json(row)
    return record.get("schema_version") if isinstance(record, dict) else None


def _measure(tm, out: Path, candidates: dict, failures: list) -> tuple[int, int]:
    measured = skipped = 0
    for sid in sorted(candidates):
        path = candidates[sid]
        row = out / "sessions" / f"{sid}.json"
        try:
            seen_ns = path.stat().st_mtime_ns
            # a row is current when the transcript is not newer and this analyzer version wrote it
            if row.exists() and seen_ns <= row.stat().st_mtime_ns and _row_version(row) == tm.SCHEMA_VERSION:
                skipped += 1
                continue
            record = dict(tm.analyze_session(path), schema_version=tm.SCHEMA_VERSION)
            _write_atomic(row, _dump(record))
            # the row carries the transcript mtime it saw: a write during analysis triggers a remeasure
            os.utime(row, ns=(seen_ns, seen_ns))
            measured += 1
        except Exception as exc:  # noqa: BLE001 - counted and recorded, never hidden
            failures.append({"error": type(exc).__name__, "reason": "analysis failed", "session_id": sid})
    return measured, skipped


def _aggregate(tm, out: Path, root_name: str, failures: list) -> dict:
    sessions = []
    rows_dir = out / "sessions"
    for row in sorted(rows_dir.glob("*.json")) if rows_dir.is_dir() else []:
        record = _read_json(row)
        if isinstance(record, dict) and "session_id" in record:
            sessions.append(record)
        else:
            failures.append({"reason": "unreadable row", "session_id": row.stem})
    sessions.sort(key=lambda s: (s.get("project") or "", s.get("first_ts") or "", s["session_id"]))
    return {
        "schema_version": tm.SCHEMA_VERSION,
        "tool_sha256": hashlib.sha256(Path(tm.__file__).read_bytes()).hexdigest(),
        "root": root_name,
        "sessions": sessions,
        "failures": sorted(failures, key=lambda f: (f["session_id"], f["reason"])),
    }


def collect(instance: Path, repo: Path, wait: bool = False) -> dict:
    tm = load_transcript_metrics(instance)
    tdir = tm.transcript_dir(repo)
    out = bench_out(instance)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"locked": True}
        failures: list = []
        candidates, consumed = _candidates(tdir, out, failures)
        measured, skipped = _measure(tm, out, candidates, failures)
        for q, mtime_ns in consumed:
            _unlink_if_unchanged(q, mtime_ns)
        aggregate = _aggregate(tm, out, tdir.parent.name, failures)
        _write_atomic(out / "data" / "sessions.json", _dump(aggregate))
        return {"failed": len(failures), "measured": measured, "queue_left": len(_queue_files(out)),
                "skipped": skipped}


# ---- report, status, adopt, ab ---------------------------------------------

def report(instance: Path, repo: Path) -> int:
    summary = collect(instance, repo, wait=True)
    print(json.dumps(summary, sort_keys=True), file=sys.stderr)
    out = bench_out(instance)
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    if (out / "adoption.json").is_file():
        shutil.copyfile(out / "adoption.json", data / "adoption.json")
    else:
        (data / "adoption.json").unlink(missing_ok=True)
    lib = instance / "bench" / "lib"
    steps = (
        ("git_metrics", ["--repo", str(repo), "--out", str(data / "git.json")]),
        ("kit_telemetry", ["--instance", str(instance), "--out", str(data / "kit.json")]),
        ("phase1_report", ["--data", str(data), "--out-dir", str(out / "report")]),
    )
    for name, args in steps:
        proc = subprocess.run([sys.executable, "-I", str(lib / f"{name}.py"), *args],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"bench: {name} failed (exit {proc.returncode})", file=sys.stderr)
            if name == "phase1_report":
                return 1
            # the extract of an earlier run is not this run's: the report must show the input as failed
            (data / EXTRACTS[name]).unlink(missing_ok=True)
    print(out / "report" / "phase1-baseline.md")
    return 0


def bench_enabled(instance: Path) -> bool:
    """config key bench.enabled; absent means on. Same file as hooks/_common.load_config."""
    config = _read_json(config_path(instance))
    bench = config.get("bench") if isinstance(config, dict) else None
    if isinstance(bench, dict) and "enabled" in bench:
        return bool(bench["enabled"])
    return True


def status(instance: Path) -> dict:
    out = bench_out(instance)
    rows_dir = out / "sessions"
    rows = [_read_json(r) for r in sorted(rows_dir.glob("*.json"))] if rows_dir.is_dir() else []
    aggregate = out / "data" / "sessions.json"
    last = None
    if aggregate.is_file():
        last = dt.datetime.fromtimestamp(aggregate.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "enabled": bench_enabled(instance),
        "adoption": _read_json(out / "adoption.json"),
        "sessions_measured": sum(1 for r in rows if isinstance(r, dict)),
        "kit_sessions": sum(1 for r in rows if isinstance(r, dict) and (r.get("kit") or {}).get("uses_kit")),
        "queue_left": len(_queue_files(out)),
        "last_collect": last,
    }


def adopt(instance: Path, repo: Path) -> str:
    out = bench_out(instance)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "adoption.json"
    if target.exists():
        return "kept"
    record = {"installed_at": _iso_ms(dt.datetime.now(dt.timezone.utc)), "label": "Measured",
              "repo": Path(os.path.realpath(repo)).name}
    tmp = out / f".adoption.{os.getpid()}.tmp"
    tmp.write_text(_dump(record), encoding="utf-8")
    try:
        os.link(tmp, target)  # atomic and never overwrites: the first install wins
    except FileExistsError:
        return "kept"
    finally:
        tmp.unlink(missing_ok=True)
    return "recorded"


def ab(instance: Path, word: str, args: list[str]) -> None:
    """Replace this process with the instance's A/B runner; the repo under test comes from its config."""
    cli = instance / "bench" / "lib" / "bench_cli.py"
    if not cli.is_file():
        raise BenchError(f"bench: the instance has no bench/lib/bench_cli.py; {SYNC_HINT}")
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, "-I", str(cli), AB_WORDS[word], *args])


# ---- CLI -------------------------------------------------------------------

def parse(argv: list[str]) -> tuple[str, str | None, list[str]]:
    if not argv or argv[0] not in SUBCOMMANDS:
        raise BenchError(USAGE)
    tools, rest, i = None, [], 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--tools":
            if i + 1 >= len(argv):
                raise BenchError(USAGE)
            tools, i = argv[i + 1], i + 2
            continue
        if arg.startswith("--tools="):
            tools = arg.split("=", 1)[1]
        else:
            rest.append(arg)
        i += 1
    if not rest or rest[0].startswith("-"):
        raise BenchError(USAGE)
    if argv[0] == "ab":
        if len(rest) < 2 or rest[1] not in AB_WORDS:
            raise BenchError(USAGE)
    elif len(rest) != 1:
        raise BenchError(USAGE)
    return argv[0], tools, rest


def _within(path: str, base) -> bool:
    """True when the resolved `path` is `base` or sits under it; `base` is resolved here (/var is a symlink on macOS)."""
    try:
        base = os.path.realpath(base)
        return os.path.commonpath([base, path]) == base
    except (OSError, ValueError):
        return False


def _fs_error_place(exc: OSError, instance: Path | None, repo: Path | None) -> str:
    """The FS_HINTS key for the path a file system error names. The bench home
    counts with <instance>/out, the one parent collect and adopt create for it."""
    names = [n for n in (exc.filename, exc.filename2) if isinstance(n, (str, bytes, os.PathLike))]
    if not names:
        return "unnamed"
    if instance is None:
        return "other"
    try:
        paths = [os.path.realpath(os.fsdecode(n)) for n in names]
    except (OSError, ValueError):
        return "other"
    home = bench_out(instance)
    if any(_within(p, home) or p == os.path.realpath(home.parent) for p in paths):
        return "bench"
    try:
        root = load_transcript_metrics(instance).transcript_dir(repo).parent
    except Exception:  # noqa: BLE001 - the analyzer may be the very thing that failed: then the root is not known
        root = None
    if root is not None and any(_within(p, root) for p in paths):
        return "transcripts"
    if any(_within(p, config_path(instance)) or _within(p, instance / "config") for p in paths):
        return "config"
    return "other"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd, instance, repo = "", None, None
    try:
        cmd, tools, rest = parse(argv)
        instance = resolve_instance(tools)
        repo = Path(rest[0])
        if not repo.is_dir():
            raise BenchError("bench: <repo> is not a directory")
        if cmd == "collect":
            print(json.dumps(collect(instance, repo), sort_keys=True))
        elif cmd == "report":
            return report(instance, repo)
        elif cmd == "status":
            print(json.dumps(status(instance), sort_keys=True))
        elif cmd == "adopt":
            print(adopt(instance, repo))
        elif cmd == "ab":
            ab(instance, rest[1], rest[2:])
    except BenchError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        if cmd not in FS_COMMANDS:
            raise
        # the class and the kind of path only: the message of the error names an absolute path and,
        # for a temp file, a process id
        print(f"bench: {cmd} stopped on a file system error ({type(exc).__name__}); "
              f"{FS_HINTS[_fs_error_place(exc, instance, repo)]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
