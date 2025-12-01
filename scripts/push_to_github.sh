#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/push_to_github.sh "commit message" [tag]
# Adds all changes, commits, pushes, and optionally tags/pushes the tag.

msg="${1:-}"
tag="${2:-}"

if [[ -z "$msg" ]]; then
  echo "Usage: $0 \"commit message\" [tag]"
  exit 1
fi

echo "Current changes:"
git status --short || exit 1
read -r -p "Proceed with commit and push? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

git add -A
git commit -m "$msg"
git push

if [[ -n "$tag" ]]; then
  git tag -a "$tag" -m "$msg"
  git push origin "$tag"
fi

echo "Done."
