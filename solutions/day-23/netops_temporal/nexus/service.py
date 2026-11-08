"""Days 22-23: the compliance team's Nexus service contract.

This is the menu: operation names, and what goes in and comes out. Callers depend on this file
only, never on the handler, the team's workflows or its namespace. Think of it as the service
catalogue of a service desk: you can see what you can ask for, not how they do it.
"""

import nexusrpc

from netops_temporal.models import Policy, PolicyRequest, RemediationRequest, RemediationResult


@nexusrpc.service
class ComplianceService:
    get_policy: nexusrpc.Operation[PolicyRequest, Policy]
    # Day 23: fix a device's config drift. Backed by a workflow, so it can take as long as the
    # saga needs, and survives either side's workers restarting.
    remediate: nexusrpc.Operation[RemediationRequest, RemediationResult]
