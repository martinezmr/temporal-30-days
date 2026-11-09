#!/usr/bin/env bash
# Day 30: roll out a build of the "netops" worker deployment, in both namespaces.
#
#   lab/deploy.sh <build-id>             make it current: new workflows start on it
#   lab/deploy.sh <build-id> <percent>   ramp: send that share of new workflows to it first
#   lab/deploy.sh status                 what's current, ramping and draining
#
# Its workers must already be polling (BUILD_ID=<build-id>): the server refuses a version
# it has never seen. Both namespaces have workers: workers.main and workers.compliance.
set -euo pipefail
DEPLOYMENT=netops
NAMESPACES=(default compliance)

if [[ "${1:-}" == "status" ]]; then
  for ns in "${NAMESPACES[@]}"; do
    echo "== $ns"
    temporal worker deployment describe --namespace "$ns" --name "$DEPLOYMENT"
  done
  exit 0
fi

BUILD_ID="${1:?usage: lab/deploy.sh <build-id> [ramp-percent] | status}"
PERCENT="${2:-}"
# Check both first: stopping halfway would leave the namespaces on different builds.
for ns in "${NAMESPACES[@]}"; do
  if ! temporal worker deployment describe-version --namespace "$ns" \
    --deployment-name "$DEPLOYMENT" --build-id "$BUILD_ID" >/dev/null 2>&1; then
    echo "$ns has never seen build $BUILD_ID: start its workers with BUILD_ID=$BUILD_ID. Nothing changed." >&2
    exit 1
  fi
done
for ns in "${NAMESPACES[@]}"; do
  if [[ -n "$PERCENT" ]]; then
    temporal worker deployment set-ramping-version --namespace "$ns" \
      --deployment-name "$DEPLOYMENT" --build-id "$BUILD_ID" --percentage "$PERCENT" --yes
  else
    temporal worker deployment set-current-version --namespace "$ns" \
      --deployment-name "$DEPLOYMENT" --build-id "$BUILD_ID" --yes
  fi
done
