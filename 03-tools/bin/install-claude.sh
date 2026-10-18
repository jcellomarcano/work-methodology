#!/usr/bin/env bash
# Installs into <repo>/.claude/ the generic-* agents and the kit's skills, the
# `metodo` MCP server (.mcp.json, excluded from commits), and the Claude
# Code hooks (merged into .claude/settings.local.json without touching
# anything else). The source of truth lives in this kit's 01-roles/agents/,
# 02-skills/ and 03-tools/.
#
#   bin/install-claude.sh <repo> [--tools <dir>] [--uninstall]
#
# --tools <dir>  tools root the hooks and the server will use in that repo
#                (an instance synced with bin/sync-instance.sh); defaults to
#                this kit. Written as the default value of
#                ${METODO_TOOLS:-...} in the commands.
# --uninstall    removes only the kit's own additions: the generic-* agents
#                and listed skill files that are byte-identical to what this
#                kit renders for the repo (for --tools, or for the tools root
#                .mcp.json records), the marked hooks, mcpServers.metodo (kept
#                while pi still uses it), the .mcp.json exclude line (only once
#                .mcp.json is gone) and the agents/skills dirs once empty. A
#                modified kit file is kept and printed as `kept: modified`.
#                One line per item: `  - <path> (removed)`, `  ! <path> (kept:
#                modified)`, `  = <path> (kept: <why>)`, `  . <path> (not found)`.
#
# Copies EXCLUSIVELY the generic-*.md / generic-*.contract.json files and the
# listed skill directories; any other agent or skill in the target repo is
# left as is. Idempotent: the second pass comes out all "=".
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--tools <dir>] [--uninstall]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KIT_ROOT="$(cd "$TOOLS_ROOT/.." && pwd)"
TOOLS_DIR="$TOOLS_ROOT"
TOOLS_DEFAULT_EXPR='$HOME/metodologia-de-trabajo/03-tools'
TOOLS_ARG=""
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) [ $# -ge 2 ] || { echo "--tools needs a value" >&2; exit 2; }
             TOOLS_ARG="$2"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
if [ -n "$TOOLS_ARG" ]; then
  if [ -d "$TOOLS_ARG" ]; then
    TOOLS_DIR="$(cd "$TOOLS_ARG" && pwd)"
  elif [ "$UNINSTALL" = "1" ]; then
    # uninstalling after the instance is gone: the path is only used to render
    case "$TOOLS_ARG" in /*) TOOLS_DIR="$TOOLS_ARG";; *) TOOLS_DIR="$PWD/$TOOLS_ARG";; esac
  else
    echo "tools root is not a directory: $TOOLS_ARG" >&2; exit 2
  fi
  TOOLS_DEFAULT_EXPR="$TOOLS_DIR"
fi
case "$TOOLS_DEFAULT_EXPR" in "$HOME"/*) TOOLS_DEFAULT_EXPR='$HOME'"${TOOLS_DEFAULT_EXPR#"$HOME"}";; esac

AGENTS_SRC="$KIT_ROOT/01-roles/agents"
SKILLS_SRC="$KIT_ROOT/02-skills"
AGENTS_DST="$REPO/.claude/agents"
SKILLS_DST="$REPO/.claude/skills"
SETTINGS="$REPO/.claude/settings.local.json"
MCP_JSON="$REPO/.mcp.json"
EXCLUDE="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$REPO/.git")/info/exclude"

# Every 02-skills/<dir> with a SKILL.md goes in SKILLS (installed; install-pi.sh
# reads this same list) or in SKILLS_EXCLUDED (shipped but not installed, on
# purpose). tests/test_install_claude.py fails when a skill is in neither.
SKILLS=(
  cartography
  adversarial-round
  verify-per-commit
  change-card
  repo-metrics
  real-environment-minutes
  pr-message
  clean-pass
  benchmark-release
  necessary-comment
  human-reply
  human-review
  review-comment
  receipt-review
  post-review-comment
  init-kit
)
SKILLS_EXCLUDED=()

copied=0
skipped=0

copy_one() {
  local src="$1" dst="$2"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    echo "  = $dst"
    skipped=$((skipped + 1))
  else
    if [ -f "$dst" ]; then echo "  ~ $dst (updated)"; else echo "  + $dst (new)"; fi
    cp "$src" "$dst"
    copied=$((copied + 1))
  fi
}

# Agent bodies carry the output hook with the __TOOLS_DEFAULT__ token; here
# it's rendered to this repo's default tools path (or to [expr], into [dir]),
# and lib/render_agents.py appends the subagent core of the kit's
# CONTEXT-PACK.md, byte for byte, so no body copies it by hand.
RENDER_TMP="$(mktemp -d)"
trap 'rm -rf "$RENDER_TMP"' EXIT
render_agent() {
  local src="$1" expr="${2:-$TOOLS_DEFAULT_EXPR}" dir="${3:-$RENDER_TMP}"
  mkdir -p "$dir"
  local out="$dir/$(basename "$src")"
  python3 "$TOOLS_ROOT/lib/render_agents.py" "$src" --target claude --tools-default "$expr" \
    --core-source "$KIT_ROOT/CONTEXT-PACK.md" --out "$out" >/dev/null
  echo "$out"
}
# Skill files that call a kit script carry the same token; the rest are
# copied byte for byte.
render_skill_file() {
  local src="$1" skill="$2" expr="${3:-$TOOLS_DEFAULT_EXPR}" dir="${4:-$RENDER_TMP}"
  if grep -q "__TOOLS_DEFAULT__" "$src" 2>/dev/null; then
    mkdir -p "$dir/skills/$skill"
    local out="$dir/skills/$skill/$(basename "$src")"
    sed "s|__TOOLS_DEFAULT__|$expr|g" "$src" > "$out"
    echo "$out"
  else
    echo "$src"
  fi
}

if [ "$UNINSTALL" = "1" ]; then
  echo "== removing the kit's additions from $REPO (claude code) =="
  n_removed=0; n_kept=0; n_missing=0
  item() {
    echo "  $1 $2 ($3)"
    case "$1" in -) n_removed=$((n_removed + 1));; !) n_kept=$((n_kept + 1));; .) n_missing=$((n_missing + 1));; esac
  }
  rel() { local p="$1"; echo "${p#"$REPO"/}"; }
  # Deletes <dst> only when it is byte-identical to one of the rendered candidates.
  remove_if_rendered() {
    local dst="$1" c; shift
    if [ ! -e "$dst" ] && [ ! -L "$dst" ]; then item . "$(rel "$dst")" "not found"; return 0; fi
    if [ -f "$dst" ] && [ ! -L "$dst" ]; then
      for c in "$@"; do
        if cmp -s "$c" "$dst"; then rm -f "$dst"; item - "$(rel "$dst")" "removed"; return 0; fi
      done
    fi
    item ! "$(rel "$dst")" "kept: modified"
  }
  rmdir_if_empty() {
    if [ -d "$1" ] && [ ! -L "$1" ] && rmdir "$1" 2>/dev/null; then item - "$(rel "$1")/" "removed"; fi
    return 0
  }

  # What install renders depends on the tools root: the one given (or the
  # default) and the one .mcp.json recorded at install time both count.
  EXPRS=("$TOOLS_DEFAULT_EXPR")
  recorded_tools() {
    python3 - "$MCP_JSON" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(((data.get("mcpServers") or {}).get("metodo") or {}).get("env", {}).get("METODO_TOOLS") or "")
except Exception:
    print("")
PY
  }
  recorded="$(recorded_tools)"
  if [ -n "$recorded" ]; then
    case "$recorded" in "$HOME"/*) recorded='$HOME'"${recorded#"$HOME"}";; esac
    [ "$recorded" != "$TOOLS_DEFAULT_EXPR" ] && EXPRS+=("$recorded")
  fi

  shopt -s nullglob
  for f in "$AGENTS_SRC"/generic-*.md; do
    cands=(); i=0
    for e in "${EXPRS[@]}"; do cands+=("$(render_agent "$f" "$e" "$RENDER_TMP/c$i")"); i=$((i + 1)); done
    remove_if_rendered "$AGENTS_DST/$(basename "$f")" "${cands[@]}"
  done
  for f in "$AGENTS_SRC"/generic-*.contract.json; do
    remove_if_rendered "$AGENTS_DST/$(basename "$f")" "$f"
  done
  for skill in "${SKILLS[@]}"; do
    src_dir="$SKILLS_SRC/$skill"; dst_dir="$SKILLS_DST/$skill"
    [ -d "$src_dir" ] || continue
    if [ ! -d "$dst_dir" ]; then item . "$(rel "$dst_dir")/" "not found"; continue; fi
    for f in "$src_dir"/*; do
      dst="$dst_dir/$(basename "$f")"
      { [ -e "$dst" ] || [ -L "$dst" ]; } || continue
      cands=(); i=0
      for e in "${EXPRS[@]}"; do cands+=("$(render_skill_file "$f" "$skill" "$e" "$RENDER_TMP/c$i")"); i=$((i + 1)); done
      remove_if_rendered "$dst" "${cands[@]}"
    done
    rmdir_if_empty "$dst_dir"
  done
  shopt -u nullglob
  rmdir_if_empty "$AGENTS_DST"
  rmdir_if_empty "$SKILLS_DST"

  out="$(python3 "$TOOLS_ROOT/lib/settings_merge.py" "$SETTINGS" --remove)"
  if grep -q '"removed": [1-9]' <<<"$out"; then
    item - ".claude/settings.local.json#hooks.metodo-hook" "removed"
  else
    item . ".claude/settings.local.json#hooks.metodo-hook" "not found"
  fi
  rmdir_if_empty "$REPO/.claude"

  # .mcp.json's metodo entry is shared with pi: kept while pi still uses it.
  pi_wired=0
  if [ -f "$REPO/.pi/extensions/metodo-hooks.ts" ]; then pi_wired=1; fi
  if python3 - "$REPO/.pi/mcp.json" <<'PY' 2>/dev/null; then pi_wired=1; fi
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if isinstance((data.get("mcpServers") or {}).get("metodo"), dict) else 1)
PY
  if [ "$pi_wired" = "1" ] && grep -q '"metodo"' "$MCP_JSON" 2>/dev/null; then
    item = ".mcp.json#mcpServers.metodo" "kept: shared with pi"
  else
    out="$(python3 "$TOOLS_ROOT/lib/mcp_config.py" "$MCP_JSON" --remove)"
    if grep -q '"changed": true' <<<"$out"; then
      item - ".mcp.json#mcpServers.metodo" "removed"
    else
      item . ".mcp.json#mcpServers.metodo" "not found"
    fi
  fi

  # The exclude line goes only once .mcp.json is gone (no server left in it).
  if [ -f "$EXCLUDE" ] && grep -qxF ".mcp.json" "$EXCLUDE"; then
    if [ -e "$MCP_JSON" ]; then
      item = "info/exclude#.mcp.json" "kept: .mcp.json still has servers"
    else
      python3 - "$EXCLUDE" ".mcp.json" <<'PY'
import sys
path, entry = sys.argv[1], sys.argv[2].encode()
lines = open(path, "rb").read().splitlines(keepends=True)
open(path, "wb").write(b"".join(l for l in lines if l.rstrip(b"\r\n") != entry))
PY
      item - "info/exclude#.mcp.json" "removed"
    fi
  fi

  echo
  echo "summary: $n_removed removed, $n_kept kept (modified), $n_missing not found"
  echo "untouched: every file the kit did not install, $SETTINGS's other keys, other MCP servers"
  exit 0
fi

mkdir -p "$AGENTS_DST" "$SKILLS_DST"

echo "== generic-* agents -> $AGENTS_DST =="
shopt -s nullglob
for f in "$AGENTS_SRC"/generic-*.md; do
  copy_one "$(render_agent "$f")" "$AGENTS_DST/$(basename "$f")"
done
for f in "$AGENTS_SRC"/generic-*.contract.json; do
  copy_one "$f" "$AGENTS_DST/$(basename "$f")"
done
shopt -u nullglob

echo "== skills -> $SKILLS_DST =="
for skill in "${SKILLS[@]}"; do
  src_dir="$SKILLS_SRC/$skill"
  if [ ! -d "$src_dir" ]; then
    echo "  ! $src_dir missing in the kit, skipping" >&2
    continue
  fi
  dst_dir="$SKILLS_DST/$skill"
  mkdir -p "$dst_dir"
  for f in "$src_dir"/*; do
    copy_one "$(render_skill_file "$f" "$skill")" "$dst_dir/$(basename "$f")"
  done
done

echo "== metodo MCP server -> $MCP_JSON =="
# METODO_REPO goes in as an absolute path: .mcp.json is local (excluded from
# commits) and CLAUDE_PROJECT_DIR is not set when Claude Code reads this file.
# The tools path is also absolute: Claude Code doesn't expand the nested $HOME
# in the default of ${METODO_TOOLS:-$HOME/...} and the server fails to start
# (CONNECTION_CLOSED, measured 15-sep-2026).
MCP_TOOLS_ABS="${TOOLS_DEFAULT_EXPR/#\$HOME/$HOME}"
python3 "$TOOLS_ROOT/lib/mcp_config.py" "$MCP_JSON" --tools-root-expr "$MCP_TOOLS_ABS" --repo-expr "$REPO"
if [ -d "$(dirname "$(dirname "$EXCLUDE")")" ]; then
  mkdir -p "$(dirname "$EXCLUDE")"
  if grep -qxF ".mcp.json" "$EXCLUDE" 2>/dev/null; then
    echo "  = .mcp.json already excluded from commits ($EXCLUDE)"
  else
    echo ".mcp.json" >> "$EXCLUDE"
    echo "  + .mcp.json excluded from commits ($EXCLUDE)"
  fi
fi

echo "== hooks -> $SETTINGS =="
python3 "$TOOLS_ROOT/lib/settings_merge.py" "$SETTINGS" --hooks "$TOOLS_ROOT/hooks/hooks.settings.json" --tools-default "$TOOLS_DEFAULT_EXPR"

echo "== sector-map drift check =="
if [ -f "$REPO/tools/verify/verify.sh" ]; then
  if ! python3 "$TOOLS_ROOT/lib/test_sectors.py" "$REPO" --check-verify "$REPO/tools/verify/verify.sh" --config "$TOOLS_DIR/config/project.json"; then
    echo "ERROR: some tasks in the test_sectors map don't exist in tools/verify/verify.sh (see unknown_tasks above)" >&2
    exit 1
  fi
else
  echo "  no tools/verify/verify.sh in the repo: skipping drift check"
fi

echo "== server smoke test =="
if [ -f "$TOOLS_DIR/mcp/server.py" ]; then
  METODO_REPO="$REPO" python3 "$TOOLS_DIR/mcp/server.py" --selftest --tools-root "$TOOLS_DIR"
else
  echo "  ! $TOOLS_DIR has no mcp/server.py: run bin/sync-instance.sh $TOOLS_DIR first" >&2
fi

echo
echo "summary: $copied copied/updated, $skipped unchanged; default tools: $TOOLS_DEFAULT_EXPR"
echo "untouched: any other file already under $AGENTS_DST or $SKILLS_DST, and $SETTINGS's permissions"
