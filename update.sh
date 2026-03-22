#!/usr/bin/env bash
set -euo pipefail
INTERVAL="${1:-60}"
while true; do
  git fetch origin
  git pull --rebase --abort 2>/dev/null || true
  git reset --hard origin/main
  git clean -fd
  python3 fetch_varulvsspel.py --limit-threads 5
  python3 build_archive.py
  if ! git diff --quiet -- archive.json || \
     ! grep -q '"slugs": \[\]' data/_changed_threads.json
  then
    git add data archive.json
    git commit -m "uppdaterar röster"
    git push
  else
    echo "Inga ändrade trådar och archive.json oförändrad. Skippar commit/push"
  fi
  sleep "$INTERVAL"
done
