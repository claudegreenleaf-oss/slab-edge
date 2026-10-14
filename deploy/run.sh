#!/usr/bin/env bash
# One scan, then publish the new data to GitHub Pages if anything changed.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull -q --rebase --autostash || true
.venv/bin/python -u -m cardarb.scan
git add docs/data
if ! git diff --cached --quiet; then
  git commit -q -m "scan $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -q
fi
