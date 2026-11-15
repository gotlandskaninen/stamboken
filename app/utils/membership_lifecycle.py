"""
The membership-status state machine (Membership.membership_status plus whether an active huvudmedlem exists).

One table, deny by default: a transition exists only when `TRANSITIONS` has a row for it. The write that
applies it is `matrikel.set_membership_status`. Pure module: no database imports, so the table can be
tested and rendered on its own (`python -m utils.membership_lifecycle`).
"""

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    """The stored values; the CHECK constraint ck_membership_status lists the same four."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    FRIEXEMPLAR = "friexemplar"


class State(StrEnum):
    """Derived from the status and the existence of an active huvudmedlem; never stored."""

    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    FRIEXEMPLAR = "FRIEXEMPLAR"
    HEADLESS = "HEADLESS"  # non-inactive, no active huvudmedlem: only GDPR erasure of the main member gets here
    PAUSED = "PAUSED"  # inactive with an active huvudmedlem
    RETIRED = "RETIRED"  # inactive, no active huvudmedlem


class Event(StrEnum):
    CREATE = "CREATE"
    SET_STATUS = "SET_STATUS"
    RETIRE = "RETIRE"
    ERASE_MAIN = "ERASE_MAIN"  # anonymize_person on the active huvudmedlem
    ADD_MAIN = "ADD_MAIN"  # add_person(role huvudmedlem) or swap_main_member into a membership without one


class TransitionRefused(Exception):
    """The table has no row for the requested transition."""


@dataclass(frozen=True)
class Transition:
    src: State | None  # None = the membership does not exist yet
    event: Event
    target: Status | None  # SET_STATUS/CREATE: the new status; ADD_MAIN: the stored status; else None
    dst: State


def state_of(status: str, has_main: bool) -> State:
    if status == Status.INACTIVE:
        return State.PAUSED if has_main else State.RETIRED
    if not has_main:
        return State.HEADLESS
    return State(status.upper())


_WITH_MAIN = (State.ACTIVE, State.PENDING, State.FRIEXEMPLAR, State.PAUSED)
_NON_INACTIVE = (Status.ACTIVE, Status.PENDING, Status.FRIEXEMPLAR)

TRANSITIONS: tuple[Transition, ...] = (
    *[Transition(None, Event.CREATE, t, state_of(t, True)) for t in Status],
    # Status changes among the states with a main member; a no-op (target == current) is a row too.
    *[Transition(s, Event.SET_STATUS, t, state_of(t, True)) for s in _WITH_MAIN for t in Status],
    *[Transition(State.HEADLESS, Event.SET_STATUS, t, State.HEADLESS) for t in _NON_INACTIVE],
    Transition(State.HEADLESS, Event.SET_STATUS, Status.INACTIVE, State.RETIRED),
    # No way out of RETIRED: setting it inactive again is the no-op.
    Transition(State.RETIRED, Event.SET_STATUS, Status.INACTIVE, State.RETIRED),
    *[Transition(s, Event.RETIRE, None, State.RETIRED) for s in State],
    *[Transition(s, Event.ERASE_MAIN, None, State.HEADLESS) for s in (State.ACTIVE, State.PENDING, State.FRIEXEMPLAR)],
    Transition(State.PAUSED, Event.ERASE_MAIN, None, State.RETIRED),
    *[Transition(State.HEADLESS, Event.ADD_MAIN, t, state_of(t, True)) for t in _NON_INACTIVE],
    # swap_main_member does not look at the status: a family member left active after the main was erased.
    Transition(State.RETIRED, Event.ADD_MAIN, Status.INACTIVE, State.PAUSED),
)


def next_state(state: State | None, event: Event, target: Status | str | None = None) -> State:
    """The state after `event`; raises TransitionRefused when there is no row."""
    for row in TRANSITIONS:
        if (row.src, row.event, row.target) == (state, event, target if target is None else Status(target)):
            return row.dst
    raise TransitionRefused(f"{event} {target or ''} from {state}")


# Event -> who may trigger it (endpoint and role), for the rendered document.
TRIGGERS: tuple[tuple[Event, str, str], ...] = (
    (Event.CREATE, "POST /api/v2/memberships, godkänd ansökan, CLI `members`", "admin, matrikel_admin"),
    (Event.SET_STATUS, "PATCH /api/v2/memberships/{id}, PATCH /api/v2/members/{id}", "admin, matrikel_admin"),
    (Event.RETIRE, "DELETE /api/v2/memberships/{id}", "admin, matrikel_admin"),
    (Event.ERASE_MAIN, "POST /api/v2/persons/{id}/anonymize", "admin, matrikel_admin"),
    (
        Event.ADD_MAIN,
        "POST /api/v2/memberships/{id}/persons, POST /api/v2/memberships/{id}/main-member",
        "admin, matrikel_admin",
    ),
)


def render_mermaid() -> str:
    edges: dict[tuple[State | None, State], list[str]] = {}
    for row in TRANSITIONS:
        if row.src == row.dst:
            continue  # self-loops (the same status again, RETIRE on a retired one) only clutter the diagram
        label = f"{row.event} {row.target}" if row.target else str(row.event)
        edges.setdefault((row.src, row.dst), []).append(label)
    lines = [
        "# Medlemskapets tillståndsmaskin",
        "",
        "Genererad av `python -m utils.membership_lifecycle` ur `TRANSITIONS` i "
        "`app/utils/membership_lifecycle.py`. Ändra inte för hand. Övergångar till samma tillstånd är utelämnade.",
        "",
        "```mermaid",
        "stateDiagram-v2",
    ]
    for (src, dst), labels in edges.items():
        lines.append(f"    {src or '[*]'} --> {dst}: {', '.join(labels)}")
    lines += ["```", "", "| Händelse | Anrop | Roll |", "|---|---|---|"]
    lines += [f"| {event} | {call} | {role} |" for event, call, role in TRIGGERS]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render_mermaid(), end="")
