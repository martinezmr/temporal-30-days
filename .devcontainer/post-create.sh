#!/usr/bin/env bash
set -euo pipefail
pip install --user uv
curl -sSf https://temporal.download/cli.sh | sh
grep -q temporalio/bin ~/.bashrc || echo 'export PATH="$HOME/.temporalio/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/.temporalio/bin:$HOME/.local/bin:$PATH"
uv sync
[ -f .env ] || sed 's/^DEVICE_MODE=live/DEVICE_MODE=mock/' .env.example > .env
