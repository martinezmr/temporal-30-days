"""Day 28: the rules every agent tool and every proposal must pass, in one place.

Day 26 had the command check inside the show activity. Now the same rule protects the MCP
server too, and a second rule checks what the agent proposes. Plain code: no I/O, so
workflows can import it, and testable without a model.
"""

from netops_temporal.policies import POLICIES

ALLOWED_PIPES = ("include ", "section ")

# CLI mode changes, not config. Models like to write out a whole session; the saga pushes
# config lines into a config session of its own (Day 27).
MODE_COMMANDS = {
    "configure",
    "configure terminal",
    "end",
    "exit",
    "write",
    "write memory",
    "copy running-config startup-config",
}

# The only lines an agent may propose: the compliance policy's (Day 14).
POLICY_LINES = {line for lines in POLICIES.values() for line in lines}

USAGE = "only show commands, piped to include or section"


class CommandNotAllowed(ValueError):
    """A command the agent's tools refuse to run."""


def check_command(command: str) -> None:
    """Raise CommandNotAllowed unless `command` is a show command, piped only to filters."""
    first, *pipes = (part.strip() for part in command.split("|"))
    if not first.startswith("show "):
        raise CommandNotAllowed(f"command not allowed: {command!r} ({USAGE})")
    for pipe in pipes:
        if not pipe.startswith(ALLOWED_PIPES):
            raise CommandNotAllowed(f"command not allowed: `| {pipe}` ({USAGE})")


def non_policy_lines(lines: list[str]) -> list[str]:
    """The proposed lines that aren't policy lines (mode commands aside)."""
    return [
        line
        for line in lines
        if line.strip().lower() not in MODE_COMMANDS and line.strip() not in POLICY_LINES
    ]
