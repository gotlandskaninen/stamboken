# Medlemskapets tillståndsmaskin

Genererad av `python -m utils.membership_lifecycle` ur `TRANSITIONS` i `app/utils/membership_lifecycle.py`. Ändra inte för hand. Övergångar till samma tillstånd är utelämnade.

```mermaid
stateDiagram-v2
    [*] --> ACTIVE: CREATE active
    [*] --> PAUSED: CREATE inactive
    [*] --> PENDING: CREATE pending
    [*] --> FRIEXEMPLAR: CREATE friexemplar
    ACTIVE --> PAUSED: SET_STATUS inactive
    ACTIVE --> PENDING: SET_STATUS pending
    ACTIVE --> FRIEXEMPLAR: SET_STATUS friexemplar
    PENDING --> ACTIVE: SET_STATUS active
    PENDING --> PAUSED: SET_STATUS inactive
    PENDING --> FRIEXEMPLAR: SET_STATUS friexemplar
    FRIEXEMPLAR --> ACTIVE: SET_STATUS active
    FRIEXEMPLAR --> PAUSED: SET_STATUS inactive
    FRIEXEMPLAR --> PENDING: SET_STATUS pending
    PAUSED --> ACTIVE: SET_STATUS active
    PAUSED --> PENDING: SET_STATUS pending
    PAUSED --> FRIEXEMPLAR: SET_STATUS friexemplar
    HEADLESS --> RETIRED: SET_STATUS inactive, RETIRE
    ACTIVE --> RETIRED: RETIRE
    PENDING --> RETIRED: RETIRE
    FRIEXEMPLAR --> RETIRED: RETIRE
    PAUSED --> RETIRED: RETIRE, ERASE_MAIN
    ACTIVE --> HEADLESS: ERASE_MAIN
    PENDING --> HEADLESS: ERASE_MAIN
    FRIEXEMPLAR --> HEADLESS: ERASE_MAIN
    HEADLESS --> ACTIVE: ADD_MAIN active
    HEADLESS --> PENDING: ADD_MAIN pending
    HEADLESS --> FRIEXEMPLAR: ADD_MAIN friexemplar
    RETIRED --> PAUSED: ADD_MAIN inactive
```

| Händelse | Anrop | Roll |
|---|---|---|
| CREATE | POST /api/v2/memberships, godkänd ansökan, CLI `members` | admin, matrikel_admin |
| SET_STATUS | PATCH /api/v2/memberships/{id}, PATCH /api/v2/members/{id} | admin, matrikel_admin |
| RETIRE | DELETE /api/v2/memberships/{id} | admin, matrikel_admin |
| ERASE_MAIN | POST /api/v2/persons/{id}/anonymize | admin, matrikel_admin |
| ADD_MAIN | POST /api/v2/memberships/{id}/persons, POST /api/v2/memberships/{id}/main-member | admin, matrikel_admin |
