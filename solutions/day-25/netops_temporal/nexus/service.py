"""Days 22-24: the compliance team's Nexus service contract.

This is the menu: operation names, and what goes in and comes out. Callers depend on this file
only, never on the handler, the team's workflows or its namespace. Think of it as the service
catalogue of a service desk: you can see what you can ask for, not how they do it.

Day 24: callers and handler deploy on their own schedules, so at any moment an old caller may be
talking to a new handler, or the other way round. Every change keeps both working:

- Add fields only as optional, with a default (RemediationRequest.change_ticket). Never rename a
  field, remove one, change its type, or make an optional one required.
- Never rename or remove an operation, or change its input or output types. Add a new operation
  (say, remediate_v2) and keep the old one until no caller uses it.
- Errors are part of the contract:
  - HandlerError(BAD_REQUEST): the request can never work (an unknown device). Not retried.
  - OperationError(FAILED): the request was understood and refused (no change ticket). Not
    retried.
  - HandlerError(INTERNAL) or any other exception: something broke on our side. Retried until
    it works or the caller's timeout runs out.
- Cancelling an operation cancels the workflow behind it. Callers must wait for that (Day 23).
"""

import nexusrpc

from netops_temporal.models import Policy, PolicyRequest, RemediationRequest, RemediationResult


@nexusrpc.service
class ComplianceService:
    get_policy: nexusrpc.Operation[PolicyRequest, Policy]
    # Day 23: fix a device's config drift. Backed by a workflow, so it can take as long as the
    # saga needs, and survives either side's workers restarting.
    remediate: nexusrpc.Operation[RemediationRequest, RemediationResult]
