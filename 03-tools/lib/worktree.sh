#!/usr/bin/env bash
# Worktree helpers for bin/verify-commit.sh and bin/benchmark-release.sh:
# a mkdir-based lock (atomic on POSIX) so two runs never launch Gradle over
# the same repo checkout at once, plus add/remove of disposable worktrees.
# It gets `source`d, not executed: it carries no `set -e` of its own
# because that is the importing script's responsibility.

WORKTREE_LOCK_WAIT_SECONDS="${WORKTREE_LOCK_WAIT_SECONDS:-600}"

# worktree_lock_acquire <lock_dir>
# `mkdir` fails if the directory already exists: that IS the lock, with no
# dependency on flock (not available everywhere) or an external library.
worktree_lock_acquire() {
  local lock_dir="$1"
  local waited=0
  mkdir -p "$(dirname "$lock_dir")"
  while ! mkdir "$lock_dir" 2>/dev/null; do
    if [ "$waited" -ge "$WORKTREE_LOCK_WAIT_SECONDS" ]; then
      echo "ERROR: could not acquire lock $lock_dir after ${WORKTREE_LOCK_WAIT_SECONDS}s (a stuck run?)" >&2
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
}

# worktree_lock_release <lock_dir>
worktree_lock_release() {
  local lock_dir="$1"
  rmdir "$lock_dir" 2>/dev/null || true
}

# worktree_add <repo> <sha> <dest>
# A freshly created worktree is not a usable checkout: `local.properties`
# is gitignored and submodules are born empty, so the battery dies on
# preconditions before measuring anything. Both are seeded from the source
# repo, on the same machine: `local.properties` never enters git and never
# leaves here, and the worktree is deleted when done.
worktree_add() {
  local repo="$1" sha="$2" dest="$3"
  rm -rf "$dest"
  git -C "$repo" worktree add --detach "$dest" "$sha" >/dev/null
  [ -f "$repo/local.properties" ] && cp "$repo/local.properties" "$dest/local.properties"
  # protocol.file.allow: git 2.38+ rejects submodules with a file url over
  # CVE-2022-39253, and oc-protos is cloned from the parent repo's .git.
  if [ -f "$dest/.gitmodules" ]; then
    git -C "$dest" -c protocol.file.allow=always submodule update --init --recursive >/dev/null 2>&1 || true
  fi
  return 0
}

# worktree_remove <repo> <dest>
# If `git worktree remove` fails (working tree already deleted by hand,
# etc.) it falls back to `rm -rf` + `worktree prune`: a disposable worktree
# must never leave the repo in a state that blocks the next `worktree add`.
worktree_remove() {
  local repo="$1" dest="$2"
  git -C "$repo" worktree remove --force "$dest" 2>/dev/null || {
    rm -rf "$dest"
    git -C "$repo" worktree prune >/dev/null 2>&1 || true
  }
}
