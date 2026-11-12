#!/usr/bin/env bash
# Installs the kit into a repo for agy (Google Antigravity CLI). Same source
# of truth as Claude Code and pi: 01-roles/agents/, 02-skills/, 03-tools/.
# What changes is the shape: agy loads a workspace plugin from
# <repo>/.agents/plugins/<name>/, so the whole kit lands in one folder:
#
#   .agents/plugins/metodo/plugin.json       manifest
#   .agents/plugins/metodo/agents/           generic-* roles as agy subagents
#   .agents/plugins/metodo/contracts/        each role's *.contract.json, byte for byte:
#                                            what the guards read when the repo has no
#                                            .claude/agents and the tools root is an
#                                            instance (no 01-roles/ beside it)
#   .agents/plugins/metodo/skills/           the kit's skills
#   .agents/plugins/metodo/hooks.json        the guards, through hooks/agy/bridge.py
#   .agents/plugins/metodo/mcp_config.json   the metodo MCP server, started per repo
#   .agents/plugins/metodo/rules/AGENTS.md   how the kit's tool names read on agy
#
#   bin/install-agy.sh <repo> [--tools <dir>] [--uninstall]
#
# --tools <dir>  tools root the hooks and the server will use in that repo
#                (an instance synced with bin/sync-instance.sh); defaults to
#                this kit.
# --uninstall    removes only what this script installed, and only when it is
#                byte-identical to what it renders for the repo (for --tools,
#                or for the tools root mcp_config.json records), then the
#                exclude line once the plugin folder is gone, and empty dirs.
#                An agent an older kit installed also counts when this kit is
#                a git checkout (render_agents.py --candidates-dir). A
#                modified kit file is kept as `kept: modified`.
#
# Writes only inside <repo>: .agents/plugins/metodo/ and .git/info/exclude.
# It never writes to ~/.gemini/, so nothing agy or gentle-ai manages there can
# be touched.
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
fi

AGENTS_SRC="$KIT_ROOT/01-roles/agents"
SKILLS_SRC="$KIT_ROOT/02-skills"
TEMPLATES="$TOOLS_ROOT/hooks/agy"
PLUGIN_REL=".agents/plugins/metodo"
PLUGIN="$REPO/$PLUGIN_REL"
EXCLUDE="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$REPO/.git")/info/exclude"

# One skill list, kept in install-claude.sh so the runtimes cannot drift.
SKILLS=()
while IFS= read -r line; do
  SKILLS+=("$line")
done < <(awk '/^SKILLS=\(/{f=1;next} f&&/^\)/{exit} f{gsub(/[ \t]/,"");if($0!="")print}' "$SCRIPT_DIR/install-claude.sh")
if [ "${#SKILLS[@]}" -eq 0 ]; then
  echo "could not read the skill list from install-claude.sh" >&2
  exit 1
fi

# Renders every plugin file for one tools root into <out>, so install and
# uninstall compare against the same bytes. hooks.json is hooks/agy/hooks.json
# with its two tokens replaced, nothing else.
render_plugin() {
  local root="$1" out="$2" f skill
  mkdir -p "$out/agents" "$out/contracts" "$out/skills" "$out/rules"
  cp "$TEMPLATES/plugin.json" "$out/plugin.json"
  cp "$TEMPLATES/AGENTS.md" "$out/rules/AGENTS.md"
  sed -e "s|__TOOLS_DEFAULT__|$root|g" -e "s|__REPO_DEFAULT__|$REPO|g" "$TEMPLATES/hooks.json" > "$out/hooks.json"
  sed -e "s|__TOOLS_DEFAULT__|$root|g" -e "s|__REPO_DEFAULT__|$REPO|g" "$TEMPLATES/mcp_config.json" > "$out/mcp_config.json"
  shopt -s nullglob
  # render_agents.py appends the subagent core of the kit's CONTEXT-PACK.md to
  # every agent, before the contract section and the role marker (last line).
  for f in "$AGENTS_SRC"/generic-*.md; do
    python3 "$TOOLS_ROOT/lib/render_agents.py" "$f" --target agy --tools-default "$root" \
      --core-source "$KIT_ROOT/CONTEXT-PACK.md" --out "$out/agents/$(basename "$f")" >/dev/null
  done
  # The contracts sit in a folder of their own: agy reads agents/ as subagents.
  # hooks/_common.py and hooks/guard_spawn.py look here after .claude/agents
  # and the kit's 01-roles/agents.
  for f in "$AGENTS_SRC"/generic-*.contract.json; do
    cp "$f" "$out/contracts/$(basename "$f")"
  done
  for skill in "${SKILLS[@]}"; do
    [ -d "$SKILLS_SRC/$skill" ] || continue
    mkdir -p "$out/skills/$skill"
    for f in "$SKILLS_SRC/$skill"/*; do
      # A skill file that calls a kit script carries __TOOLS_DEFAULT__, rendered
      # to the tools root like the agents; the rest are copied byte for byte.
      if grep -q "__TOOLS_DEFAULT__" "$f" 2>/dev/null; then
        sed "s|__TOOLS_DEFAULT__|$root|g" "$f" > "$out/skills/$skill/$(basename "$f")"
      else
        cp "$f" "$out/skills/$skill/$(basename "$f")"
      fi
    done
  done
  shopt -u nullglob
}

RENDER_TMP="$(mktemp -d)"
trap 'rm -rf "$RENDER_TMP"' EXIT

if [ "$UNINSTALL" = "1" ]; then
  echo "== removing the kit's additions from $REPO (agy) =="
  n_removed=0; n_kept=0; n_missing=0
  item() {
    echo "  $1 $2 ($3)"
    case "$1" in -) n_removed=$((n_removed + 1));; !) n_kept=$((n_kept + 1));; .) n_missing=$((n_missing + 1));; esac
  }
  rel() { local p="$1"; echo "${p#"$REPO"/}"; }
  rmdir_if_empty() {
    if [ -d "$1" ] && [ ! -L "$1" ] && rmdir "$1" 2>/dev/null; then item - "$(rel "$1")/" "removed"; fi
    return 0
  }

  if [ ! -d "$PLUGIN" ] || [ -L "$PLUGIN" ]; then
    if [ -e "$PLUGIN" ] || [ -L "$PLUGIN" ]; then item ! "$PLUGIN_REL" "kept: modified"; else item . "$PLUGIN_REL/" "not found"; fi
  else
    # What install renders depends on the tools root: the one given (or the
    # default) and the one mcp_config.json recorded at install time both count.
    ROOTS=("$TOOLS_DIR")
    recorded="$(python3 - "$PLUGIN/mcp_config.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(((data.get("mcpServers") or {}).get("metodo") or {}).get("env", {}).get("METODO_TOOLS") or "")
except Exception:
    print("")
PY
)"
    if [ -n "$recorded" ] && [ "$recorded" != "$TOOLS_DIR" ]; then ROOTS+=("$recorded"); fi

    # An agent counts as the kit's when it matches anything an install of this
    # kit may have written: today's render, today's render without the subagent
    # core, and, in a git checkout, each committed version rendered by the
    # renderer, contract and core committed with it (render_agents.py
    # --candidates-dir). Without git history only the first two.
    if ! git -C "$KIT_ROOT" rev-parse --show-prefix >/dev/null 2>&1; then
      echo "  note: $KIT_ROOT is not a git checkout: agents an older kit installed may be kept as modified"
    fi
    shopt -s nullglob
    agents=("$AGENTS_SRC"/generic-*.md)
    shopt -u nullglob
    i=0
    for root in "${ROOTS[@]}"; do
      render_plugin "$root" "$RENDER_TMP/c$i"
      if [ "${#agents[@]}" -gt 0 ]; then
        python3 "$TOOLS_ROOT/lib/render_agents.py" "${agents[@]}" --target agy --tools-default "$root" \
          --core-source "$KIT_ROOT/CONTEXT-PACK.md" --kit-root "$KIT_ROOT" --candidates-dir "$RENDER_TMP/a$i" >/dev/null
      fi
      i=$((i + 1))
    done

    shopt -s nullglob  # a candidates folder that holds nothing adds no candidate
    while IFS= read -r relpath; do
      dst="$PLUGIN/$relpath"
      removed=0
      if [ -f "$dst" ] && [ ! -L "$dst" ]; then
        cands=()
        for ((j = 0; j < i; j++)); do
          cands+=("$RENDER_TMP/c$j/$relpath")
          case "$relpath" in agents/*) cands+=("$RENDER_TMP/a$j/$(basename "$relpath")"/*);; esac
        done
        for c in ${cands[@]+"${cands[@]}"}; do
          if cmp -s "$c" "$dst"; then rm -f "$dst"; item - "$(rel "$dst")" "removed"; removed=1; break; fi
        done
      fi
      if [ "$removed" = "0" ]; then
        if [ -e "$dst" ] || [ -L "$dst" ]; then item ! "$(rel "$dst")" "kept: modified"; else item . "$(rel "$dst")" "not found"; fi
      fi
    done < <(cd "$RENDER_TMP/c0" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)
    shopt -u nullglob
    # Deepest first, so a folder empties before its parent is tried.
    while IFS= read -r dir; do rmdir_if_empty "$dir"; done < <(find "$PLUGIN" -depth -type d 2>/dev/null)
  fi
  rmdir_if_empty "$REPO/.agents/plugins"
  rmdir_if_empty "$REPO/.agents"

  # The exclude line goes only once the folder it names is gone.
  if [ -f "$EXCLUDE" ] && grep -qxF "$PLUGIN_REL" "$EXCLUDE"; then
    if [ -e "$PLUGIN" ] || [ -L "$PLUGIN" ]; then
      item = "info/exclude#$PLUGIN_REL" "kept: $PLUGIN_REL still exists"
    else
      python3 - "$EXCLUDE" "$PLUGIN_REL" <<'PY'
import sys
path, entry = sys.argv[1], sys.argv[2].encode()
lines = open(path, "rb").read().splitlines(keepends=True)
open(path, "wb").write(b"".join(l for l in lines if l.rstrip(b"\r\n") != entry))
PY
      item - "info/exclude#$PLUGIN_REL" "removed"
    fi
  fi

  echo
  echo "summary: $n_removed removed, $n_kept kept (modified), $n_missing not found"
  echo "untouched: every file the kit did not install, other plugins in .agents/, ~/.gemini/"
  exit 0
fi

copied=0
skipped=0
copy_one() {
  local src="$1" dst="$2"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    echo "  = $dst"
    skipped=$((skipped + 1))
  else
    if [ -f "$dst" ]; then echo "  ~ $dst (updated)"; else echo "  + $dst (new)"; fi
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    copied=$((copied + 1))
  fi
}

echo "== metodo plugin -> $PLUGIN =="
render_plugin "$TOOLS_DIR" "$RENDER_TMP/plugin"
for skill in "${SKILLS[@]}"; do
  [ -d "$SKILLS_SRC/$skill" ] || echo "  ! $SKILLS_SRC/$skill missing in the kit, skipping" >&2
done
while IFS= read -r relpath; do
  copy_one "$RENDER_TMP/plugin/$relpath" "$PLUGIN/$relpath"
done < <(cd "$RENDER_TMP/plugin" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)

echo "== excluded from commits ($EXCLUDE) =="
if [ -d "$(dirname "$(dirname "$EXCLUDE")")" ]; then
  mkdir -p "$(dirname "$EXCLUDE")"
  if grep -qxF "$PLUGIN_REL" "$EXCLUDE" 2>/dev/null; then
    echo "  = $PLUGIN_REL"
  else
    echo "$PLUGIN_REL" >> "$EXCLUDE"
    echo "  + $PLUGIN_REL"
  fi
fi

echo "== server smoke test =="
if [ -f "$TOOLS_DIR/mcp/server.py" ]; then
  METODO_REPO="$REPO" python3 "$TOOLS_DIR/mcp/server.py" --selftest --tools-root "$TOOLS_DIR"
else
  echo "  ! $TOOLS_DIR has no mcp/server.py: run bin/sync-instance.sh $TOOLS_DIR first" >&2
fi

echo
echo "summary: $copied copied/updated, $skipped unchanged; tools root: $TOOLS_DIR"
echo "untouched: ~/.gemini/ and every other plugin in .agents/"
echo "note: agy loads a new plugin folder on its next start; check it with: agy plugin validate --strict $PLUGIN_REL"
