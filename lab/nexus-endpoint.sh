#!/usr/bin/env bash
# Day 22: create the Nexus endpoint the orchestrator calls. It routes `compliance-endpoint` to
# the compliance team's task queue in their own namespace. Safe to run again.
set -euo pipefail
if ! temporal operator namespace describe --namespace compliance >/dev/null 2>&1; then
  # lab/start-temporal.sh creates it; an older dev server may not have it yet.
  temporal operator namespace create --namespace compliance
fi
# A new namespace takes a few seconds to be usable. Day 20's search attributes, there too.
for _ in $(seq 1 30); do
  temporal operator search-attribute create --namespace compliance \
    --name Device --type Keyword --name ComplianceStatus --type Keyword >/dev/null 2>&1 && break
  if temporal operator search-attribute list --namespace compliance 2>/dev/null | grep -q ComplianceStatus; then
    break
  fi
  sleep 1
done
if temporal operator nexus endpoint get --name compliance-endpoint >/dev/null 2>&1; then
  echo "compliance-endpoint already exists"
else
  temporal operator nexus endpoint create \
    --name compliance-endpoint \
    --target-namespace compliance \
    --target-task-queue compliance-tq \
    --description-file <(echo "The compliance team's ComplianceService (Days 22-24).")
fi
temporal operator nexus endpoint get --name compliance-endpoint
