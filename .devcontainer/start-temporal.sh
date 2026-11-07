#!/usr/bin/env bash
# Starts the Temporal dev server in the background each time the Codespace starts.
export PATH="$HOME/.temporalio/bin:$PATH"
mkdir -p .temporal
if ! pgrep -f "temporal server start-dev" >/dev/null; then
  nohup temporal server start-dev --ip 0.0.0.0 \
    --db-filename .temporal/temporal.db \
    --namespace compliance > .temporal/server.log 2>&1 &
  echo "Temporal dev server starting (log: .temporal/server.log)"
fi
