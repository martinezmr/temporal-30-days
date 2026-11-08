#!/usr/bin/env bash
# Run a command against solutions/day-NN instead of your own src/ code.
# The solution folder goes first on PYTHONPATH, so `import netops_temporal` loads it.
#
#   scripts/solution.sh 02 python -m netops_temporal.workers.main
#   scripts/solution.sh 02 python -m netops_temporal.starters.facts bos-rtr-01
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DAY="${1:-}"
if [[ ! "$DAY" =~ ^[0-9]{2}$ ]]; then
  echo "usage: scripts/solution.sh NN <command...>   (NN is the day as two digits, e.g. 02)" >&2
  exit 2
fi
shift
SOLUTION="$REPO/solutions/day-$DAY"
if [[ ! -d "$SOLUTION/netops_temporal" ]]; then
  echo "no solution at $SOLUTION" >&2
  exit 2
fi

ENV_ARGS=()
[[ -f "$REPO/.env" ]] && ENV_ARGS=(--env-file "$REPO/.env")

cd "$REPO"
PYTHONPATH="$SOLUTION${PYTHONPATH:+:$PYTHONPATH}" exec uv run --project "$REPO" ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$@"
