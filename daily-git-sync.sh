#!/usr/bin/env bash
set -euo pipefail

# Optional: allow passing a repo dir, default to ~/agenttrader
REPO_DIR="${1:-$HOME/agenttrader}"

echo "[git-sync] Repo: $REPO_DIR"
cd "$REPO_DIR"

# Show status before doing anything
echo "[git-sync] ==== git status (before) ===="
git status

# Detect current branch
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "[git-sync] Current branch: $BRANCH"

echo "[git-sync] Local autosave commit (if needed)..."
git add -A

# If nothing staged, skip commit
if git diff --cached --quiet; then
  echo "[git-sync] Nothing to autosave (no staged changes)."
else
  git commit -m "wip: autosave before daily-git-sync"
  echo "[git-sync] Created autosave commit."
fi

echo "[git-sync] Fetching from origin..."
git fetch origin

echo "[git-sync] Rebasing onto origin/$BRANCH..."
git pull --rebase origin "$BRANCH" || {
  echo "[git-sync] ERROR: git pull --rebase failed. Please resolve conflicts manually."
  exit 1
}

echo "[git-sync] Staging any changes after rebase..."
git add -A

if git diff --cached --quiet; then
  echo "[git-sync] No new changes to commit after rebase."
else
  git commit -m "chore: sync via daily-git-sync"
  echo "[git-sync] Committed changes after rebase."
fi

echo "[git-sync] Pushing to origin/$BRANCH..."
git push origin "$BRANCH"

echo "[git-sync] ==== git status (after) ===="
git status

echo "[git-sync] Completed successfully."
