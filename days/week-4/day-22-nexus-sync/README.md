# Day 22 — First Nexus service (sync operation)

[← Week 3](../../week-3/README.md) · [Day 23 →](../day-23-nexus-async/README.md)

## Goal

A workflow in `default` calls an operation served by a worker in `compliance`, through an endpoint.

## Build

1. **Contract** — `nexus/compliance_service.py` (shared by both sides):

    ```python
    import nexusrpc
    from pydantic import BaseModel

    class PolicyRequest(BaseModel):
        role: str

    class Policy(BaseModel):
        role: str
        required_lines: list[str]

    @nexusrpc.service
    class ComplianceService:
        get_policy: nexusrpc.Operation[PolicyRequest, Policy]
    ```

2. **Handler** — `nexus/compliance_handler.py`:

    ```python
    @nexusrpc.handler.service_handler(service=ComplianceService)
    class ComplianceServiceHandler:
        @nexusrpc.handler.sync_operation
        async def get_policy(self, ctx: nexusrpc.handler.StartOperationContext,
                             req: PolicyRequest) -> Policy:
            return POLICIES[req.role]
    ```

3. **Handler worker** — `workers/compliance.py`, connected to namespace `compliance`, task queue `compliance-tq`, with `nexus_service_handlers=[ComplianceServiceHandler()]`.
4. **Endpoint:**

    ```bash
    temporal operator nexus endpoint create \
      --name compliance-endpoint \
      --target-namespace compliance \
      --target-task-queue compliance-tq
    ```

5. **Caller** — in a workflow on `default`:

    ```python
    nexus = workflow.create_nexus_client(service=ComplianceService, endpoint="compliance-endpoint")
    policy = await nexus.execute_operation(ComplianceService.get_policy, PolicyRequest(role="access"),
                                           schedule_to_close_timeout=timedelta(seconds=30))
    ```

## Look for

`NexusOperationScheduled` → `NexusOperationCompleted` in the caller's history.

## Troubleshooting

If `endpoint create` fails, your CLI/server image predates Nexus GA. Pull a newer `admin-tools` image, or (older builds) start the dev server with `--http-port 7243 --dynamic-config-value system.enableNexus=true`.

## Done when

- [ ] The caller workflow gets a policy back, and the two namespaces share nothing but the contract module.
