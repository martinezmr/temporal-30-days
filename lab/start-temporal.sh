#!/usr/bin/env bash
# Temporal dev server + UI in a container, with persistence and a second namespace for Nexus.
# Usage: ./lab/start-temporal.sh            (uses podman)
#        ENGINE=docker ./lab/start-temporal.sh
set -euo pipefail
ENGINE="${ENGINE:-podman}"
NAME="${NAME:-temporal-dev}"

"$ENGINE" volume inspect temporal-data >/dev/null 2>&1 || "$ENGINE" volume create temporal-data
"$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true

"$ENGINE" run -d --name "$NAME" \
  -p 127.0.0.1:7233:7233 \
  -p 127.0.0.1:8233:8233 \
  -v temporal-data:/data \
  docker.io/temporalio/admin-tools:latest \
  temporal server start-dev --ip 0.0.0.0 \
    --db-filename /data/temporal.db \
    --namespace compliance

echo "Temporal UI:   http://localhost:8233"
echo "Temporal gRPC: localhost:7233"
echo "Namespaces:    default, compliance"
