---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0011: Statusdetektering och dödsorsaksanalys

## Kontext och problem

Kaniner är Aktiva (`is_active`, från `Individual.active` i
`app/utils/database.py`: registrerad, levande, inte kastrerad, en BIRTH-,
TRANSFER- eller ATTESTATION-händelse inom 13 månader och i en aktiv
besättning inom genbanken), Inaktiva (levande men inte aktiva), Döda (har
dödsdatum) eller Döda (uppskattad)
(har `death_note` men inget `death_date`). I befintlig data har många kaniner
`death_note` utan `death_date`, `death_note` innehåller ofta ett årtal
(t.ex. "2018 bet ofta"), dödsorsaker uttrycks olika (slakt, avlivning,
rymning) och `alive` kan vara `false` utan `death_date`.

## Alternativ

* Endast visa Aktiv/Inaktiv: avvisat, eftersom information om dödsorsak går
  förlorad
* Kräva exakt `death_date`: avvisat, eftersom hundratals kaniner då skulle
  sakna status
* Intelligent parsing med prioritetsordning (valt)

## Beslut

Valt alternativ: "Intelligent parsing med prioritetsordning", eftersom det
ger mest nytta av befintlig data. Logiken finns i `getStatusInfo` och `getAge`
i `next-app/src/components/herd/IndividualCard.tsx` och används på
individsidan. Min besättning visar en förenklad status (Aktiv, Såld, Död,
Inaktiv) via `rabbitStatus` i `min-besattning-ui.tsx`
([ADR-0009](0009-stamboken-design-system.md)).

1. Statusprioritet, högst först:

   ```text
   1. death_date finns        → "Död YYYY-MM-DD" / "Slaktad …" / "Avlivad …" (error)
   2. Försvunnen keywords     → "Försvunnen ~YYYY" (warning)
   3. Slaktad keywords        → "Slaktad ~YYYY" (error)
   4. Avlivad keywords        → "Avlivad ~YYYY" (error)
   5. death_note + !alive     → "Död ~YYYY" (error)
   6. !is_active              → "Inaktiv" (default, neutral)
   7. is_active               → "Aktiv" (success)
   ```

2. Keywords (gemener): Försvunnen: "rymt", "rymde", "försvann", "stulen".
   Slaktad: "slakt", "kött" + `butchered === true`. Avlivad: "avliv".
3. Året tas bara från början av `death_note`, följt av blanksteg eller
   komma (regex `^(19\d{2}|20\d{2})[\s,]`). Årtal mitt i texten ignoreras.
4. Åldern för döda kaniner räknas till dödsdatumet. Saknas det, och kaninen är
   död med `death_note`, uppskattas slutet: mitten av året i anteckningen,
   annars senaste årsrapporten plus ett år, annars dagens datum. Har
   årsrapporterna inga datum blir åldern okänd. Uppskattningar markeras med
   "~" och förklaras i tooltipen.

### Konsekvenser

* Bra, eftersom användare ser dödsorsak (Slaktad/Avlivad/Försvunnen) direkt.
* Bra, eftersom ungefärlig ålder beräknas även utan exakt dödsdatum.
* Dåligt, eftersom `death_note` kan feltolkas och nya formuleringar inte
  fångas utan underhåll.
* Dåligt, eftersom "~YYYY" kan missförstås som exakt datum.

## Mer information

* [ADR-0009: Stambokens designsystem för all UI](0009-stamboken-design-system.md)
* [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) – "Datavalidering mot verklighet"

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2025-12 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
