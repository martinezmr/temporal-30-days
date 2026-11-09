"""Day 22: the compliance team's Nexus service contract.

This is the menu: operation names, and what goes in and comes out. Callers depend on this file
only, never on the handler, the team's workflows or its namespace. Think of it as the service
catalogue of a service desk: you can see what you can ask for, not how they do it.
"""

import nexusrpc

from netops_temporal.models import Policy, PolicyRequest


@nexusrpc.service
class ComplianceService:
    get_policy: nexusrpc.Operation[PolicyRequest, Policy]
