"""Day 20: seeing what the automation is doing.

- Search attributes: index workflows by device and outcome, so `Device="bos-acc-01"` finds every
  workflow that touched it. They must be registered on the server first (lab/start-temporal.sh).
- Metrics: the SDK's own Prometheus metrics (workflows completed, activity latency, task queue
  backlog...), served by the worker at http://localhost:<port>/metrics.
- Tracing: OpenTelemetry spans for every workflow, activity and child, printed to the console.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from temporalio.common import SearchAttributeKey
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig

DEVICE_SA = SearchAttributeKey.for_keyword("Device")
# How a remediation ended: planned (dry run), fixed, rolled-back, failed or cancelled.
COMPLIANCE_SA = SearchAttributeKey.for_keyword("ComplianceStatus")


def runtime_with_metrics(port: int = 9464) -> Runtime:
    """A Temporal runtime that serves Prometheus metrics. Pass it to Client.connect(runtime=...)."""
    return Runtime(
        telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"127.0.0.1:{port}"))
    )


def tracing_interceptor() -> TracingInterceptor:
    """OpenTelemetry tracing, printed to the console. In production you'd export to a collector
    (Jaeger, Tempo, ...) instead of ConsoleSpanExporter; the interceptor stays the same."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    # By default, workflow spans only appear when the client that started the workflow traced
    # the start too. The orchestrator is started from the CLI, by a schedule, or by a starter
    # without tracing, so ask for workflow spans regardless.
    return TracingInterceptor(always_create_workflow_spans=True)
