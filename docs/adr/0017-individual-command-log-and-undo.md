---
status: "proposed"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0017: Kommandologg och ångra för skrivningar på individ

## Kontext och problem

`audit_log` fångar varje ändrad rad med en trigger, och managers kan
återställa en rad därifrån. För användare räcker det inte. En rad beskriver
kolumner, inte avsikter, så den säger inte vilken regel en omvändning ska
prövas mot. `changed_by` är text som byts mot en pseudonym vid radering, och
inget kopplar en ångring till det den ångrar.
[ADR-0015](0015-individual-write-commands.md) gör skrivningar på individ till
ett kommando per avsikt, körda av en central skrivare, så kommandot är en
naturlig enhet för ångra.

## Alternativ

* Härdad återställning ur `audit_log`: avvisat, eftersom raden saknar avsikt,
  stabil aktör och koppling till det ångrade, och varje kopplad kolumn
  (kullnummer, intyg, BIRTH-raden) måste spärras för hand.
* Tre kolumner i `audit_log`: avvisat, eftersom den delade triggerfunktionen
  måste ändras och ångra blir beroende av hur `audit_log` gallras.
* Event sourcing: avvisat, eftersom varje läsväg kräver projektioner som hålls
  synkrona med händelserna, vilket är för dyrt.
* Egen tabell för kommandon (valt)

## Beslut

Valt alternativ: "Egen tabell för kommandon", eftersom semantiken blir tydlig,
tabellerna förblir sanningen för genetik, legacy-API och exporter, och
mönstret redan finns i herd-tracking. Varje kommando som skriver loggas i en
egen tabell, `individual_command`. Att ångra är ett eget kommando, `Undo`,
som går genom samma skrivare och samma policytabell som det ångrade.

Regler:

1. **Egen tabell.** Skrivaren loggar varje kommando som ändrar något, med
   `operation_id`, kommando, individ, aktör, tid, före- och eftervärden för de
   kolumner kommandot ändrade, `request_id` (ett per anrop, delat av
   kommandona i en legacy-PATCH) och `undoes`. Förevärdet läses innan
   nollningen körs. Ett eko loggas inte.
   `audit_log` och dess trigger ändras inte. Årsrapport och försäljning delar
   `operation_id` med sin herd-tracking-rad. En BIRTH-rad som ersätts när
   ursprung eller kull byts får ett eget id, tills de kommandona blir
   ångringsbara.
2. **Aktören är en härledd roll.** `ACTOR` finns i policytabellen men härleds
   bara när ett `Undo` prövas mot den loggade raden: användaren är den som
   körde kommandot. En skötare med skötaravtal har ett eget konto och ångrar
   sina egna ändringar. Rollen ger ingen annan rätt.
3. **Tre nivåer.**
   * Ångra: den som gjorde ändringen, inom 7 dagar, utan orsak.
   * Rättelse: manager för nuvarande genbank eller admin, med orsak och utan
     åldersgräns.
   * Återställning: admin, ur `audit_log`, för det som aldrig gick via
     kommandon. Den ingår inte här.
4. **Vad som går att ångra.** Beskrivning (utan foto), dödsfall, nollade fält
   och årsrapport. Övriga kommandon loggas men vägras med 400. En ångring
   nekas med 409 om någon har ändrat samma fält efteråt, och den prövar
   policyn på nytt mot dagens rad. Om en årsrapport är ångrad avgörs av
   herd-tracking, eftersom raden också kan makuleras och återställas där.
5. **Herd-tracking stramas åt på samma sätt.** Andra än managers kan bara
   makulera rader de själva har registrerat.
6. **GDPR.** Aktören är en FK till `hbuser` och följer `purge_user_audit_pii`.
   Raden pseudonymiseras och raderas inte, så historiken går att läsa.
   Fritexten i loggen rensas efter 13 månader, och direkt för en användare som
   rensas. En ångring som skulle återställa rensad text nekas.

### Konsekvenser

* Bra, eftersom användare kan ångra sina egna ändringar utan att managers
  behöver gå in, och historiken går att läsa efter att ett konto har rensats.
* Bra, eftersom ångra och rättelse prövas mot samma policytabell som
  skrivningen.
* Dåligt, eftersom det blir en tabell till och ett skrivsteg till i varje
  kommando. Skrivningar utanför kommandona (kull, besättning, konto, skript)
  går bara att rätta eller återställa tills deras domäner får kommandon.
* Dåligt, eftersom fritexten finns i två loggar och `audit_log`s kopia inte
  rensas av den här ändringen.
* Dåligt, eftersom dubbelklick inte stoppas: servern skapar `operation_id`. Ett
  id från klienten per formulär kommer med gränssnittet.

### Bekräftelse

* En tillståndsmaskin (Hypothesis) mot en modell visar att en ångring nekas med
  409 när fältet inte längre har eftervärdet.
* Ångra låser loggraden och rensningen tar samma radlås, så en samtidig
  rensning inte skrivs tillbaka av en ångring.
* Tabelltest: för alla andra kommandon än `Undo` ger `ACTOR` samma svar som
  utan.

## Mer information

* [ADR-0014: Behörighetsmodell för Stambokens API](0014-authorization-model.md)
* [ADR-0015: Kommandon per avsikt för skrivningar på individ](0015-individual-write-commands.md)

Rapporten om ändringar och ångra och implementationsplanen finns i föreningens
interna dokumentation.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-10-29 | Jonas | Utkast |
| 2026-11-06 | Jonas | MADR-format, kortad |
