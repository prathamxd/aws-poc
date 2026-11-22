"""Ticket status workflow: Open -> In Progress -> Resolved -> Closed."""
from __future__ import annotations

STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]

# A resolved ticket can be re-opened (back to In Progress) if the fix did not work.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Open": {"In Progress"},
    "In Progress": {"Resolved"},
    "Resolved": {"Closed", "In Progress"},
    "Closed": set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in ALLOWED_TRANSITIONS.get(current, set())


def next_statuses(current: str) -> list[str]:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    return [s for s in STATUSES if s in allowed]
