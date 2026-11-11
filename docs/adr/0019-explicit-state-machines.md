---
status: "proposed"
date: 2026-11-11
decision-makers: Jonas
---

# ADR-0019: Explicita tillståndsmaskiner där en implicit har ett hål

## Kontext och problem

Flera fält i Stamboken är i praktiken tillståndsmaskiner: en status, en flagga
eller ett datum avgör vad som får hända härnäst. Reglerna låg utspridda i de
funktioner som skriver fältet. En genomgång av alla skrivställen hittade två
maskiner där det gav ett verkligt hål. Ett avslutat medlemskap kunde sättas
till aktivt igen utan personer i det, och ett pappersintyg som ersatte ett
digitalt lämnade det digitala intyget som gällande på den publika
verifieringssidan. I gränssnittet kunde dialogen för omnumrering av kullar
fastna om anslutningen bröts.

## Beslutsdrivare

* Ett otillåtet tillstånd ska inte gå att nå genom ett vanligt anrop.
* Lagliga nästa steg ska gå att läsa ur en fil, av människor och av agenter.
* Inget nytt beroende och helst ingen schemaändring.

## Alternativ

* En ren modul per maskin med en övergångstabell, efter mönstret i
  `individual_policy.py` (valt)
* Ett bibliotek för tillståndsmaskiner: avvisat, eftersom det är ett nytt
  beroende för några tiotal rader tabell.
* CHECK-villkor och triggrar i databasen: avvisat, eftersom tillstånden här är
  härledda ur flera tabeller och övergången beror på vem som frågar.
* Göra alla statusfält explicita: avvisat, eftersom de flesta saknar hål och en
  tabell utan hål bara är mer kod att underhålla.

## Beslut

Valt alternativ: "En ren modul per maskin med en övergångstabell", eftersom
mönstret redan finns för skrivningar på individ
([ADR-0015](0015-individual-write-commands.md)) och går att testa och rita
utan databas.

1. **En maskin görs explicit bara när den har ett hål**: ett otillåtet
   tillstånd som går att nå, en övergång utan spärr, eller ett läge där
   användaren fastnar. Övriga lämnas.
2. **Tabellen är en ren modul.** `app/utils/membership_lifecycle.py` och
   `app/utils/certificate_lifecycle.py` har tillstånd och händelser som
   `StrEnum`, en övergångstabell och nekar allt som saknar rad. Inga
   databasimporter.
3. **Fältet skrivs i en modul.** Medlemskapets status skrivs bara i
   `app/utils/matrikel.py`, intygskolumnerna på individ bara i
   `app/utils/individual_commands.py` och `is_current` bara i modellens två
   metoder i `app/utils/database.py`. Skrivaren prövar övergången mot
   tabellen. En rad som redan ligger i ett otillåtet läge får lämna det men
   aldrig hamna där.
4. **Diagrammet genereras.** `python -m utils.membership_lifecycle` och
   `python -m utils.certificate_lifecycle` skriver ett
   `stateDiagram-v2`-diagram ur tabellen. Resultatet ligger i
   `app/tests/membership_lifecycle.md` och `app/tests/certificate_lifecycle.md`
   och ritas aldrig för hand.
5. **I gränssnittet** speglas en serverstatus som en union med en uttömmande
   `Record` (`next-app/src/lib/membershipStatus.ts`), och ett flöde i flera
   steg som en diskriminerad union med `assertNever`
   (`next-app/src/components/herd/renumberFlow.ts`).

Ett avslutat medlemskap återaktiveras inte. Behövs det igen skapas ett nytt
medlemskap. Båda PATCH-anropen svarar 409 på försöket. De används bara av
Next.js, så [ADR-0006](0006-api-compatibility-during-migration.md) berörs inte.

### Konsekvenser

* Bra, eftersom de två hålen är stängda och regeln står på ett ställe i
  stället för i varje skrivare.
* Bra, eftersom listan över medlemskapets statusar fanns på nio ställen och nu
  finns på tre: i Python, i databasens CHECK-villkor och i TypeScript.
* Dåligt, eftersom ett medlemskap som avslutats av misstag inte går att öppna
  igen från gränssnittet.
* Dåligt, eftersom tabellen i Python och unionen i TypeScript hålls lika för
  hand.

### Bekräftelse

* Per maskin ett Hypothesis-test (`RuleBasedStateMachine`) som driver de
  riktiga anropen mot en modell som bara flyttas av tabellen:
  `test_membership_lifecycle_machine.py` och
  `test_certificate_lifecycle_machine.py`. Båda föll på koden före ändringen.
* Ett test per maskin söker igenom `app/` efter skrivningar av fältet utanför
  den ägande modulen, och ett jämför det incheckade diagrammet med det
  genererade.

## Mer information

* [ADR-0015: Kommandon per avsikt för skrivningar på individ](0015-individual-write-commands.md)
* [ADR-0017: Kommandologg och ångra för skrivningar på individ](0017-individual-command-log-and-undo.md)

Genomgången av övriga maskiner finns i föreningens interna dokumentation.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-11-11 | Jonas | Skapad |
