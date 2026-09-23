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
# --uninstall    removes only the kit's own additions: marked hooks and
#                mcpServers.metodo. Agents and skills are listed for manual
#                deletion.
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
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) TOOLS_DIR="$(cd "$2" && pwd)"; TOOLS_DEFAULT_EXPR="$TOOLS_DIR"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
case "$TOOLS_DEFAULT_EXPR" in "$HOME"/*) TOOLS_DEFAULT_EXPR='$HOME'"${TOOLS_DEFAULT_EXPR#"$HOME"}";; esac

AGENTS_SRC="$KIT_ROOT/01-roles/agents"
SKILLS_SRC="$KIT_ROOT/02-skills"
AGENTS_DST="$REPO/.claude/agents"
SKILLS_DST="$REPO/.claude/skills"
SETTINGS="$REPO/.claude/settings.local.json"
MCP_JSON="$REPO/.mcp.json"
EXCLUDE="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$REPO/.git")/info/exclude"

if [ "$UNINSTALL" = "1" ]; then
  echo "== removing the kit's additions from $REPO =="
  python3 "$TOOLS_ROOT/lib/settings_merge.py" "$SETTINGS" --remove
  python3 "$TOOLS_ROOT/lib/mcp_config.py" "$MCP_JSON" --remove
  echo "kit agents and skills (delete by hand if appropriate):"
  ls "$AGENTS_DST"/generic-* 2>/dev/null || true
  for d in "$SKILLS_DST"/*/; do [ -f "$d/SKILL.md" ] && grep -q "mcp__metodo__" "$d/SKILL.md" && echo "  $d"; done
  exit 0
fi

mkdir -p "$AGENTS_DST" "$SKILLS_DST"

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
)

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
# it's rendered to this repo's default tools path.
RENDER_TMP="$(mktemp -d)"
trap 'rm -rf "$RENDER_TMP"' EXIT
render_agent() {
  local src="$1" out="$RENDER_TMP/$(basename "$1")"
  sed "s|__TOOLS_DEFAULT__|$TOOLS_DEFAULT_EXPR|g" "$src" > "$out"
  echo "$out"
}

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
    copy_one "$f" "$dst_dir/$(basename "$f")"
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
