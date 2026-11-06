"""
Who may run which write command on an individual (ADR-0015 rule 2).

Deny by default: a command is allowed only when both an `Entry` row and a row for the
command match the user's roles and the rabbit's state. Validation that does not depend
on who asks (dates, uniqueness, quota, the reason for a genebank change) lives in the
commands, not here. Pure module: no database imports, so the table can be tested and
rendered on its own (`python -m utils.individual_policy`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER_CURRENT = "manager_current"  # manager of the current herd's genebank
    MANAGER_ORIGIN = "manager_origin"  # manager of the origin herd's genebank
    OWNER = "owner"  # current herd in user.transfer_herd_ids()
    CARETAKER = "caretaker"  # current herd in effective_herd_ids() - transfer_herd_ids()
    ACTOR = "actor"  # ran the logged command; derived only by Undo (actor_role), never by roles_for


@dataclass(frozen=True)
class State:
    certified: bool  # certificate or digital_certificate is set (truthy)
    outside_genebank: bool  # current herd is GX1/MX1


@dataclass(frozen=True)
class Allow:
    command: str  # command class name, or "Entry"
    role: Role
    certified: bool | None = None  # None = both
    outside_genebank: bool | None = None  # None = both

    def matches(self, command: str, roles: frozenset[Role], state: State) -> bool:
        return (
            self.command == command
            and self.role in roles
            and self.certified in (None, state.certified)
            and self.outside_genebank in (None, state.outside_genebank)
        )


EDITORS = (Role.ADMIN, Role.MANAGER_CURRENT)  # every state
HOLDERS = (Role.OWNER, Role.CARETAKER)  # never outside the genebank (_can_edit_herd)
EDIT_LIKE = (
    "EditDescription",
    "RecordDeath",
    "ClearFields",
    "SetMeasurements",
    "RecordAttestation",
    "IssueDigitalCertificate",
)
CERT_GUARDED = ("AssignPaperCertificate", "RenameIndividual", "MoveToLitter")  # IR-18, IR-19

POLICY: tuple[Allow, ...] = (
    *[Allow("Entry", r) for r in EDITORS],
    *[Allow("Entry", r, outside_genebank=False) for r in HOLDERS],
    *[Allow(c, r) for c in EDIT_LIKE for r in (*EDITORS, *HOLDERS)],
    *[Allow("TransferIndividual", r) for r in EDITORS],
    Allow("TransferIndividual", Role.OWNER, outside_genebank=False),  # never a caretaker
    *[Allow(c, r) for c in CERT_GUARDED for r in EDITORS],
    *[Allow(c, r, certified=False) for c in CERT_GUARDED for r in HOLDERS],
    Allow("ChangeOriginHerd", Role.ADMIN),
    Allow("ChangeOriginHerd", Role.MANAGER_ORIGIN),  # IR-28; Entry applies too
    # Not a command: TransferIndividual and ChangeOriginHerd ask it when the genebank changes (IR-54).
    Allow("GenebankCorrection", Role.ADMIN),
    # Entry applies too, so an actor who sold the rabbit or lost the right to edit it is denied (ADR-0017).
    *[Allow("Undo", r) for r in (Role.ACTOR, *EDITORS)],
)

# Command -> form fields, for the matrix.
COMMAND_FIELDS: Mapping[str, tuple[str, ...]] = {
    "EditDescription": (
        "name",
        "sex",
        "color",
        "color_note",
        "eye_color",
        "claw_color",
        "belly_color",
        "hair_notes",
        "notes",
        "foot_ring",
        "castration_date",
        "is_active",
        "has_photo",
    ),
    "RecordDeath": ("death_date", "death_note", "butchered"),
    "ClearFields": ("death_date", "death_note", "butchered", "castration_date"),
    "SetMeasurements": ("weights", "bodyfat"),
    "RecordAttestation": ("herd", "yearly_report_date"),
    "TransferIndividual": ("herd", "selling_date", "reason"),
    "AssignPaperCertificate": ("certificate",),
    "RenameIndividual": ("number",),
    "MoveToLitter": ("breeding",),
    "ChangeOriginHerd": ("origin_herd", "reason"),
    "IssueDigitalCertificate": ("digital_certificate",),
    "GenebankCorrection": ("herd", "origin_herd", "reason"),
    "Undo": ("undo",),
}

STATES = tuple(State(certified, outside) for outside in (False, True) for certified in (False, True))
ROLE_SETS = tuple(frozenset(c) for n in range(len(Role) + 1) for c in combinations(Role, n))


def allowed(command: str, roles: frozenset[Role], state: State) -> bool:
    """Entry and a row for `command`; anything without a row is denied."""

    def granted(name: str) -> bool:
        return any(row.matches(name, roles, state) for row in POLICY)

    return granted("Entry") and granted(command)


def matrix() -> list[tuple[str, str, frozenset[Role], State, bool]]:
    """(command, field, role set, state, allowed) for every role set, since a user can hold several roles."""
    return [
        (command, field, roles, state, allowed(command, roles, state))
        for command, fields in COMMAND_FIELDS.items()
        for field in fields
        for roles in ROLE_SETS
        for state in STATES
    ]


def _state_label(state: State) -> str:
    label = "certifierad" if state.certified else "ocertifierad"
    return f"{label}, GX1/MX1" if state.outside_genebank else label


def render_matrix() -> str:
    """
    One markdown table per command: a row per single role, plus each role combination
    that allows something none of its smaller combinations allows.
    """
    lines = [
        "# Behörighetsmatris för skrivningar på individ",
        "",
        "Genererad av `python -m utils.individual_policy` ur `POLICY` i "
        "`app/utils/individual_policy.py`. Ändra inte för hand.",
    ]
    header = "| Roll | " + " | ".join(_state_label(s) for s in STATES) + " |"
    rule = "|---|" + "---|" * len(STATES)
    for command, fields in COMMAND_FIELDS.items():
        lines += ["", f"## {command}", "", "Fält: " + ", ".join(f"`{f}`" for f in fields), "", header, rule]
        for roles in ROLE_SETS:
            outcome = [allowed(command, roles, s) for s in STATES]
            smaller = [any(allowed(command, roles - {r}, s) for r in roles) for s in STATES]
            if len(roles) == 1 or outcome != smaller:  # the empty set denies everything, like its subsets
                name = " + ".join(r.value for r in Role if r in roles)
                lines.append(f"| {name} | " + " | ".join("✓" if ok else "–" for ok in outcome) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render_matrix(), end="")
