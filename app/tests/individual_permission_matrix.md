# Behörighetsmatris för skrivningar på individ

Genererad av `python -m utils.individual_policy` ur `POLICY` i `app/utils/individual_policy.py`. Ändra inte för hand.

## EditDescription

Fält: `name`, `sex`, `color`, `color_note`, `eye_color`, `claw_color`, `belly_color`, `hair_notes`, `rex`, `notes`, `foot_ring`, `castration_date`, `is_active`, `has_photo`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | – | – | – | – |

## RecordDeath

Fält: `death_date`, `death_note`, `butchered`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | ✓ | ✓ | – | – |

## ClearFields

Fält: `death_date`, `death_note`, `butchered`, `castration_date`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | – | – | – | – |

## SetMeasurements

Fält: `weights`, `bodyfat`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | ✓ | ✓ | – | – |

## RecordAttestation

Fält: `herd`, `yearly_report_date`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | ✓ | ✓ | – | – |

## TransferIndividual

Fält: `herd`, `selling_date`, `reason`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | – | – | – | – |

## AssignPaperCertificate

Fält: `certificate`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | – | – | – |
| caretaker | ✓ | – | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | – | – | – |
| rapport | – | – | – | – |

## RenameIndividual

Fält: `number`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | – | – | – |
| caretaker | ✓ | – | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | – | – | – |
| rapport | – | – | – | – |

## MoveToLitter

Fält: `breeding`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | – | – | – |
| caretaker | ✓ | – | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | – | – | – |
| rapport | – | – | – | – |

## ChangeOriginHerd

Fält: `origin_herd`, `reason`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | – | – | – | – |
| manager_origin | – | – | – | – |
| owner | – | – | – | – |
| caretaker | – | – | – | – |
| actor | – | – | – | – |
| handlaggare | – | – | – | – |
| rapport | – | – | – | – |
| manager_current + manager_origin | ✓ | ✓ | ✓ | ✓ |
| manager_origin + owner | ✓ | ✓ | – | – |
| manager_origin + caretaker | ✓ | ✓ | – | – |
| manager_origin + handlaggare | ✓ | ✓ | – | – |
| manager_origin + rapport | ✓ | ✓ | – | – |

## IssueDigitalCertificate

Fält: `digital_certificate`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | – | – | – | – |

## GenebankCorrection

Fält: `herd`, `origin_herd`, `reason`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | – | – | – | – |
| manager_origin | – | – | – | – |
| owner | – | – | – | – |
| caretaker | – | – | – | – |
| actor | – | – | – | – |
| handlaggare | – | – | – | – |
| rapport | – | – | – | – |

## RegisterLitter

Fält: `litter`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | ✓ | ✓ | – | – |

## ConfirmLitterSize

Fält: `litter_size6w`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | ✓ | ✓ | – | – |
| caretaker | ✓ | ✓ | – | – |
| actor | – | – | – | – |
| handlaggare | ✓ | ✓ | – | – |
| rapport | ✓ | ✓ | – | – |

## Undo

Fält: `undo`

| Roll | ocertifierad | certifierad | ocertifierad, GX1/MX1 | certifierad, GX1/MX1 |
|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ |
| manager_current | ✓ | ✓ | ✓ | ✓ |
| manager_origin | – | – | – | – |
| owner | – | – | – | – |
| caretaker | – | – | – | – |
| actor | – | – | – | – |
| handlaggare | – | – | – | – |
| rapport | ✓ | ✓ | – | – |
| owner + actor | ✓ | ✓ | – | – |
| caretaker + actor | ✓ | ✓ | – | – |
| actor + handlaggare | ✓ | ✓ | – | – |
