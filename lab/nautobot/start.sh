#!/usr/bin/env bash
# Start the course Nautobot (http://localhost:8080) and wait until it is healthy.
# Usage: lab/nautobot/start.sh            (uses podman)
#        ENGINE=docker lab/nautobot/start.sh
# First start runs database migrations and takes a few minutes.
set -euo pipefail
ENGINE="${ENGINE:-podman}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$ENGINE" compose -f "$HERE/compose.yml" up -d

echo -n "Waiting for Nautobot on http://localhost:8080 "
for _ in $(seq 1 60); do
  if curl -fs -o /dev/null http://localhost:8080/health/; then
    echo " ready."
    echo "UI: http://localhost:8080 (admin/admin). Next: uv run python lab/nautobot/seed.py"
    exit 0
  fi
  echo -n "."
  sleep 5
done
echo
echo "Nautobot did not become healthy in 5 minutes. Logs: $ENGINE compose -f $HERE/compose.yml logs nautobot" >&2
exit 1
