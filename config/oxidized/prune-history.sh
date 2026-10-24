#!/bin/sh
# Keeps only the last OXIDIZED_RETENTION_DAYS of history in the bare Oxidized
# git repo (default 90 days ~ 3 months), then gc's. Usage: prune-history.sh [--loop]
# Safe against a concurrent Oxidized commit: the rewrite updates the branch
# only if it still points where it started, otherwise it fails and retries on
# the next cycle.
set -eu
REPO_PATH="${REPO_PATH:-/data/oxidized.git}"
DAYS="${OXIDIZED_RETENTION_DAYS:-90}"
EVERY="${PRUNE_EVERY_SECONDS:-86400}"

prune_once() {
  [ -d "$REPO_PATH" ] || { echo "no repo yet at $REPO_PATH"; return 0; }
  export GIT_DIR="$REPO_PATH"
  git config --global --add safe.directory "$REPO_PATH" 2>/dev/null || true
  cutoff=$(( $(date +%s) - DAYS * 86400 ))
  first=$(git rev-list --reverse --since="$cutoff" HEAD 2>/dev/null | head -n 1 || true)
  [ -n "$first" ] || { echo "nothing newer than ${DAYS}d"; return 0; }
  if [ -z "$(git rev-parse --verify -q "${first}^" || true)" ]; then
    echo "history already starts inside the retention window"; return 0
  fi
  echo "dropping history older than ${DAYS}d (new root: $(echo "$first" | cut -c1-8))"
  git replace --graft "$first"
  FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f -- --branches >/dev/null 2>&1 || { echo "rewrite failed (concurrent commit?); will retry later"; git replace -d "$first" 2>/dev/null || true; return 0; }
  git replace -d "$first" 2>/dev/null || true
  rm -rf "$REPO_PATH"/refs/original
  git reflog expire --expire=now --all
  git gc --prune=now --quiet
}

if [ "${1:-}" = "--loop" ]; then
  while true; do prune_once || true; sleep "$EVERY"; done
else
  prune_once
fi
