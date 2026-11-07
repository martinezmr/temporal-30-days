# Day 20 — Observability

[← Day 19](../day-19-versioning/README.md) · [Day 21 →](../day-21-production-workers/README.md)

## Goal

Find any device's compliance story in the UI in seconds, and see your workers' health in Grafana.

## Learn

- Replay-safe logging: `workflow.logger` (suppressed during replay), `activity.logger`.
- **Search attributes** — indexed fields you filter on. **Memo** — unindexed notes. **User metadata** — a static summary/details shown in the UI.
- SDK metrics (Prometheus) and OpenTelemetry tracing via interceptors.
- Docs: [Observability](https://docs.temporal.io/develop/python/platform/observability) · [Enriching the UI](https://docs.temporal.io/develop/python/platform/enriching-ui) · [Interceptors](https://docs.temporal.io/develop/python/workers/interceptors)

## Build

1. Register attributes:

    ```bash
    temporal operator search-attribute create --name DeviceName --type Keyword
    temporal operator search-attribute create --name Site --type Keyword
    temporal operator search-attribute create --name ComplianceState --type Keyword
    ```

2. Set them when starting children and update them as state changes:

    ```python
    DEVICE = SearchAttributeKey.for_keyword("DeviceName")
    STATE = SearchAttributeKey.for_keyword("ComplianceState")
    workflow.upsert_search_attributes([STATE.value_set("remediating")])
    ```

3. Give children a summary: `start_child_workflow(..., static_summary=f"Remediate {device}: {len(diff)} lines")`.
4. In the UI: `ComplianceState = "drifted" AND Site = "bos"`.

## Optional: metrics

```python
runtime = Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address="0.0.0.0:9000")))
client = await Client.connect(TEMPORAL_ADDRESS, runtime=runtime)
```

Add Prometheus + Grafana containers scraping `:9000`. Watch `temporal_activity_execution_failed` and schedule-to-start latency.

## Done when

- [ ] You can find every remediation for `nyc-rtr-01` this week with one UI query.
