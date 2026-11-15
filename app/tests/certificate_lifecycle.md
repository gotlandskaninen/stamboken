# Intygets tillstånd för en individ

Genererad av `python -m utils.certificate_lifecycle` ur `TRANSITIONS` i `app/utils/certificate_lifecycle.py`. Ändra inte för hand.

```mermaid
stateDiagram-v2
    [*] --> none
    none --> paper: register_with_paper, assign_paper
    paper --> paper: assign_paper
    digital_number --> paper: assign_paper
    digital --> paper: assign_paper
    paper --> none: clear_paper
    none --> none: clear_paper
    digital_number --> digital_number: clear_paper
    digital --> digital: clear_paper, issue_pdf
    none --> digital_number: issue_number
    paper --> digital_number: issue_number
    digital_number --> digital: issue_pdf
```

| Händelse | Skrivs av | Vem |
|---|---|---|
| `register_with_paper` | POST /api/v2/individual med pappersintyg | den som registrerar kaninen |
| `assign_paper` | `AssignPaperCertificate` (PATCH /api/individual, PATCH /api/individual/{number}) | manager, admin; ägare bara utan intyg |
| `clear_paper` | `AssignPaperCertificate` med tomt nummer (samma anrop) | manager, admin; ägare bara utan intyg |
| `issue_number` | `IssueDigitalCertificate`, `assign_certificate_number` | den som får utfärda intyg (uppfödaren, manager, admin) |
| `issue_pdf` | `generate_and_store` (POST /api/v2/certificates/issue, PATCH .../update) | den som får utfärda intyg (uppfödaren, manager, admin) |
