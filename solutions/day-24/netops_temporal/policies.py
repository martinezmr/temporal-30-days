"""Day 14: the compliance policy. Config lines every device of a role must have.

Plain data, so workflows can import it. From Day 22 the compliance team serves it over Nexus.
"""

POLICIES: dict[str, list[str]] = {
    "access": ["ntp server 192.0.2.10"],
    "router": ["ntp server 192.0.2.10", "logging host 192.0.2.50"],
}
