#!/usr/bin/env python3
"""SessionEnd: queues the finished session for the benchmark and starts the
collector in the background (benchmark-port S7). It writes
<tools>/out/bench/queue/<session_id>.json = {"session_id", "transcript_path"}
and spawns a detached `<tools>/bin/bench.sh collect <repo>` (its own session,
stdio on /dev/null, never awaited), where <repo> is CLAUDE_PROJECT_DIR, else
the input cwd. It never reads the transcript and never waits: the end of a
session is not delayed, so the measuring happens in the collector. A session
with no transcript_path is still queued (as ""); the collector counts it as
failed only when its sweep does not find that session either. Without
bin/bench.sh the item stays for the next `bench.sh collect`.

Gated by the config key `bench.enabled` (absent means on). Claude Code only:
the measurement reads Claude Code transcripts. Writes only inside the tools
instance; a bad session id, bad stdin or a failed write exits 0 with nothing
printed.

Environment variables a test can set: METODO_TOOLS (the instance),
METODO_PROJECT_CONFIG (alternate project.json), METODO_BENCH_NO_SPAWN=1
(queue without starting the collector).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

# The id names the queue file: one path segment, never hidden, never a traversal.
SESSION_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}")


def bench_enabled(config: dict) -> bool:
    bench = config.get("bench") if isinstance(config, dict) else None
    if isinstance(bench, dict) and "enabled" in bench:
        return bool(bench["enabled"])
    return True


def enqueue(session_id: str, transcript_path: str) -> None:
    queue = c.TOOLS_ROOT / "out" / "bench" / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"session_id": session_id, "transcript_path": transcript_path}, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=queue, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, queue / f"{session_id}.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def spawn_collect(repo: str) -> None:
    bench = c.TOOLS_ROOT / "bin" / "bench.sh"
    if not bench.is_file():
        return
    subprocess.Popen(["bash", str(bench), "collect", repo], start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    inp = c.read_input()
    if not isinstance(inp, dict) or not bench_enabled(c.load_config()):
        return 0
    session_id = inp.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return 0
    transcript = inp.get("transcript_path")
    try:
        enqueue(session_id, transcript if isinstance(transcript, str) else "")
    except OSError:
        pass  # nothing queued; the collector still sweeps the repo's transcript dir
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or inp.get("cwd")
    if os.environ.get("METODO_BENCH_NO_SPAWN") != "1" and isinstance(repo, str) and repo:
        try:
            spawn_collect(repo)
        except OSError:
            pass  # the item stays queued for the next `bench.sh collect`
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
