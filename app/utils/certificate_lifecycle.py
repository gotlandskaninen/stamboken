"""
The certificate state of an individual, and the writes that move it between states.

The state is derived, never stored: `Individual.certificate` (paper number), `Individual.digital_certificate`
(digital number) and whether a `DigitalCertificateV2` row is current. Every writer derives the state before and
after its write and calls `check`; anything without a row in TRANSITIONS is refused (deny by default).
Pure module: no database imports, so the table can be tested and rendered on its own
(`python -m utils.certificate_lifecycle`).
"""

from dataclasses import dataclass
from enum import StrEnum


class CertState(StrEnum):
    NONE = "none"
    PAPER = "paper"
    DIGITAL_NUMBER = "digital_number"  # a digital number and no current PDF row: v1 certificates
    DIGITAL = "digital"  # a digital number and a current PDF row


class Event(StrEnum):
    REGISTER_WITH_PAPER = "register_with_paper"  # the paper number written when the rabbit is created
    ASSIGN_PAPER = "assign_paper"  # AssignPaperCertificate; retires the digital certificate
    ISSUE_NUMBER = "issue_number"  # IssueDigitalCertificate / assign_certificate_number; clears the paper number
    ISSUE_PDF = "issue_pdf"  # generate_and_store: the new current row; first issue and re-issue alike


@dataclass(frozen=True)
class Transition:
    source: CertState
    event: Event
    target: CertState


S = CertState
TRANSITIONS: tuple[Transition, ...] = (
    Transition(S.NONE, Event.REGISTER_WITH_PAPER, S.PAPER),
    *[Transition(s, Event.ASSIGN_PAPER, S.PAPER) for s in S],
    Transition(S.NONE, Event.ISSUE_NUMBER, S.DIGITAL_NUMBER),
    Transition(S.PAPER, Event.ISSUE_NUMBER, S.DIGITAL_NUMBER),
    Transition(S.DIGITAL_NUMBER, Event.ISSUE_PDF, S.DIGITAL),
    Transition(S.DIGITAL, Event.ISSUE_PDF, S.DIGITAL),
)

# Event -> (what writes it, who may trigger it), for the rendered document.
EVENTS = {
    Event.REGISTER_WITH_PAPER: ("POST /api/v2/individual med pappersintyg", "den som registrerar kaninen"),
    Event.ASSIGN_PAPER: ("`AssignPaperCertificate` (PATCH /api/individual)", "manager, admin; ägare bara utan intyg"),
    Event.ISSUE_NUMBER: (
        "`IssueDigitalCertificate`, `assign_certificate_number`",
        "den som får utfärda intyg (uppfödaren, manager, admin)",
    ),
    Event.ISSUE_PDF: (
        "`generate_and_store` (POST /api/v2/certificates/issue, PATCH .../update)",
        "den som får utfärda intyg (uppfödaren, manager, admin)",
    ),
}


def state_of(certificate, digital_certificate, has_current_v2) -> CertState:
    """The state of the three columns; raises on a combination no state allows."""
    paper, digital = bool(certificate), digital_certificate is not None
    if paper and digital:
        raise ValueError("Both a paper and a digital certificate number are set")
    if has_current_v2 and not digital:
        raise ValueError("A current digital certificate row without a digital certificate number")
    if paper:
        return CertState.PAPER
    if digital:
        return CertState.DIGITAL if has_current_v2 else CertState.DIGITAL_NUMBER
    return CertState.NONE


def next_state(state: CertState, event: Event) -> CertState:
    """The state after `event`; raises when the table has no row for it."""
    for row in TRANSITIONS:
        if row.source == state and row.event == event:
            return row.target
    raise ValueError(f"{event} is not allowed from the certificate state {state}")


def check(before: CertState | None, event: Event, after: CertState | None) -> None:
    """A writer's own check: the state it left must be the one the table gives. A mismatch is a programming error.

    `None` is a combination no state allows. Rows written before this table may be in one, so a writer may
    start there (the table cannot say where it ends), but it must never end there.
    """
    if after is None or (before is not None and next_state(before, event) != after):
        raise AssertionError(f"{event} took the certificate from {before} to {after}")


def render_mermaid() -> str:
    """The table as a markdown document with one Mermaid state diagram, parallel edges merged."""
    edges: dict[tuple[CertState, CertState], list[Event]] = {}
    for row in TRANSITIONS:
        edges.setdefault((row.source, row.target), []).append(row.event)
    lines = [
        "# Intygets tillstånd för en individ",
        "",
        "Genererad av `python -m utils.certificate_lifecycle` ur `TRANSITIONS` i "
        "`app/utils/certificate_lifecycle.py`. Ändra inte för hand.",
        "",
        "```mermaid",
        "stateDiagram-v2",
        f"    [*] --> {CertState.NONE}",
        *[f"    {src} --> {dst}: {', '.join(events)}" for (src, dst), events in edges.items()],
        "```",
        "",
        "| Händelse | Skrivs av | Vem |",
        "|---|---|---|",
        *[f"| `{event}` | {writer} | {who} |" for event, (writer, who) in EVENTS.items()],
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render_mermaid(), end="")
