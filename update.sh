#!/usr/bin/env bash
set -e
INTERVAL="${1:-60}"
while true; do
  git fetch origin
  git pull --rebase --abort 2>/dev/null || true
  git reset --hard
  git clean -fd
  python3 fetch_varulvsspel.py --limit-threads 5
  python3 build_archive.py
  if ! git diff --quiet -- archive.json; then
    git add data archive.json
    git commit -m "uppdaterar röster"
    git push
  else
    echo "archive.json oförändrad. Skippar commit/push"
  fi
  sleep "$INTERVAL"
done
