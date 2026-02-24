#!/usr/bin/env bash
set -e
INTERVAL="${1:-60}"
while true; do
  python3 fetch_varulvsspel.py --limit-threads 5
  python3 build_archive.py
  if ! git diff --quiet -- archive.json; then
    git add data archive.json
    git commit -m "auto update"
    git push
  else
    echo "archive.json oförändrad. Skippar commit/push"
  fi
  sleep "$INTERVAL"
done
