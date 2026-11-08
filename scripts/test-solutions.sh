#!/usr/bin/env bash
# Run the tests of every solution (or only the days you name), each against its own code.
#
#   scripts/test-solutions.sh          # all days
#   scripts/test-solutions.sh 02 03    # just Day 2 and Day 3
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [[ $# -gt 0 ]]; then
  DAYS=("$@")
else
  DAYS=()
  for dir in solutions/day-*/; do
    [[ -d "$dir" ]] && DAYS+=("$(basename "$dir" | sed 's/^day-//')")
  done
fi

failed=()
for day in "${DAYS[@]}"; do
  echo "=== day $day ==="
  if PYTHONPATH="solutions/day-$day" LAB_MODE=mock uv run pytest -c pyproject.toml "solutions/day-$day/tests" -q; then
    :
  else
    failed+=("$day")
  fi
done

echo
echo "solutions tested: ${DAYS[*]:-none}"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "FAILED: ${failed[*]}"
  exit 1
fi
echo "all passed"
