"""Shared names and settings. Read from the environment (see .env.example)."""

import os

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

# Task queues (Day 1). Workflows on one, device I/O on the other (split into two workers on Day 21).
ORCHESTRATION_TASK_QUEUE = "netops-orchestration"
DEVICE_IO_TASK_QUEUE = "netops-device-io"

# "live" = real cEOS over eAPI, "mock" = canned fixtures (Codespaces, unit tests).
DEVICE_MODE = os.environ.get("DEVICE_MODE", "live")

ORCHESTRATOR_WORKFLOW_ID = "network-compliance-orchestrator"
