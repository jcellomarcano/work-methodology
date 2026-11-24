"""Write the mock files of the three cases from the answers the scratch kit's server gave.

`--raw` writes each answer as it came. Without it, the identities of the scratch run are replaced by the
scenario's, by text and in this order: the scratch tools root becomes the workspace root (paths turn
relative), each scratch commit sha becomes the sha of the commit in the same position of the staged files
(whole, then its 9 and 7 character forms), and the sha of the scratch kit becomes the `tool_sha` of the
staged files. Nothing else is touched; the unified diff of every body against its answer is printed.
"""
import difflib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
T = pathlib.Path((HERE / "root.txt").read_text().strip())
ANSWERS = T / "answers"
EVALS = pathlib.Path("KIT_ROOT/08-benchmark/evals")
BENCH = EVALS / "benchmark-release" / "smoke-base-is-the-tag"
VERIFY = EVALS / "verify-per-commit" / "smoke-keep-the-fail"
MINUTES = EVALS / "real-environment-minutes" / "smoke-median-and-mock"


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", str(T / repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha_pairs(pairs):
    out = []
    for size in (40, 9, 7):
        out += [(scratch[:size], scenario[:size]) for scratch, scenario in pairs]
    return out


tools_root = str((T / "kit" / "03-tools").resolve())
roots = [(tools_root + "/", ""), (tools_root.replace("/private/var/", "/var/") + "/", "")]
staged = json.loads((BENCH / "setup/out/benchmark/7607119..bd18de0.json").read_text())
kit_sha = [(git("kit", "rev-parse", "HEAD"), staged["tool_sha"])]
bench = roots + sha_pairs([(git("bench-repo", "rev-parse", "v2.3.0"), staged["sha_a"]),
                           (git("bench-repo", "rev-parse", "release-2.4"), staged["sha_b"])]) + kit_sha
key = json.loads((VERIFY / "testdata/answer-key.json").read_text())
verify = roots + sha_pairs(list(zip(git("verify-repo", "log", "--reverse", "--format=%H", "v2.3.0..HEAD").split(),
                                    [c["sha"] for c in key["commits"]]))) + kit_sha

PLAN = [(BENCH, "benchmark_release", "bench-start-tag", bench), (BENCH, "job_status", "bench-status-tag", bench),
        (VERIFY, "verify_commit", "verify-start", verify), (VERIFY, "job_status", "verify-status", verify),
        (MINUTES, "benchmark_release", "bench-start-tag", bench), (MINUTES, "job_status", "bench-status-tag", bench),
        (MINUTES, "domain_invariants", "domain-invariants-head", bench), (MINUTES, "change_card_extract", "card-extract", bench)]
raw = "--raw" in sys.argv
for case, tool, answer, pairs in PLAN:
    real = (ANSWERS / f"{answer}.json").read_text(encoding="utf-8")
    body = real
    for old, new in ([] if raw else pairs):
        body = body.replace(old, new)
    json.loads(body)
    target = case / "mocks" / "metodo" / f"{tool}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    diff = list(difflib.unified_diff(real.splitlines(), body.splitlines(), "server answer", f"{case.parent.name}/{tool}.md", lineterm="", n=0))
    print(f"## {case.parent.name}/{tool}.md  <- answers/{answer}.json  ({len([d for d in diff if d.startswith('+') and not d.startswith('+++')])} lines differ of {len(body.splitlines())})")
    if "--diff" in sys.argv:
        print("\n".join(d[:170] for d in diff if not d.startswith("@@")))
