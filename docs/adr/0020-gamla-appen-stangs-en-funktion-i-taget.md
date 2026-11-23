---
status: "accepted"
date: 2026-11-23
decision-makers: Jonas
---

# ADR-0020: Gamla appen stängs en funktion i taget

## Kontext och problem

Gamla appen och nya Stamboken delar Flask-API och databas tills gamla appen
avvecklas ([ADR-0006](0006-api-compatibility-during-migration.md)). Så länge
gamla appen skriver måste varje ny datamodell också förstå dess skrivningar.
Ett exempel: gamla appen skickar tillbaka hela besättningen varje gång någon
sparar. Det skulle återskapa den kopia av kontaktuppgifterna som issue #117
tar bort. Intygen har redan stängts i gamla appen (PR #62), men det finns
ingen gemensam regel för hur en funktion stängs medan resten finns kvar.

## Beslutsdrivare

* Ingen ska förlora en funktion. Det som stängs i gamla appen ska gå att göra i
  nya Stamboken.
* Läsningar i gamla appen ska fungera tills den avvecklas.
* Den som försöker använda en stängd funktion ska få veta var den finns nu,
  inte få ett tekniskt fel.

## Alternativ

* Stänga en funktion i taget, med 410 i API:t och en banner i gamla appen
  (valt)
* Stänga hela gamla appen på ett visst datum: avvisat, eftersom nya Stamboken
  ännu inte gör allt som gamla appen gör.
* Låta gamla appen skriva tills den avvecklas och översätta dess skrivningar:
  avvisat, eftersom varje ny modell (matrikeln, kommandona i
  [ADR-0015](0015-individual-write-commands.md)) då behöver kod för gamla
  appens format. Två skrivvägar med olika regler ger fel som är svåra att
  upptäcka.
* Skrivskydd i databasen: avvisat, eftersom gamla appen och nya Stamboken delar
  databas, och ett skydd där ger fel utan förklaring.
* Dölja funktionen bara i gamla appens gränssnitt: avvisat, eftersom API:t då
  fortfarande tar emot skrivningar från en flik som varit öppen länge eller från
  ett direkt anrop.
* 403 i stället för 410: avvisat, eftersom 403 betyder att behörighet saknas.
  410 säger att vägen är borta.

## Beslut

Valt alternativ: "Stänga en funktion i taget", eftersom nya Stamboken då kan ta
över i den takt den hinner, och gamla appen inte behöver förstå de nya
modellerna.

Regler för dagligt arbete:

1. **Nya Stamboken först.** En funktion stängs i gamla appen först när samma
   användare kan göra samma sak i nya Stamboken. PR:en som stänger säger var.
2. **En stängd skrivväg svarar 410 Gone** med en svensk text som säger var
   funktionen finns nu, till exempel "Intyg utfärdas och ändras nu i nya
   Stamboken.". Svaret har samma form som gamla appen redan visar för fel på
   den vägen, så att texten syns.
3. **Ingenting händer på en stängd väg**: ingen databasändring, ingen fil och
   inget mejl. Svaret är detsamma oavsett vem som frågar och om objektet finns,
   så att det inte avslöjar något.
4. **Stäng i routen**, inte i funktionen under den. Nya Stambokens vägar som
   anropar samma funktion ska fortsätta fungera. Till exempel anropar
   `PATCH /api/v2/herd/<herd_id>` också `update_herd`.
5. **Läsvägarna behåller formatet** (ADR-0006, regel 1). De får hämta data ur
   nya källor, till exempel matrikeln, men lämnar dem i samma fält.
6. **Gamla appen visar en banner** där funktionen fanns, med en länk till nya
   Stamboken. Knappen eller formuläret går inte att använda. Ändringen görs i
   `gotlandskaninen/stamboken-legacy` och pinnas i det här repot.
7. **Kontraktstester** visar att vägen svarar 410, att inget har ändrats och att
   läsvägen är oförändrad, som för intygen i
   `app/tests/test_legacy_api_contracts.py`.
8. **Tabellen nedan uppdateras** i samma PR som stänger en funktion.

| Funktion | Stängda vägar | Görs nu i | Issue eller PR |
|---|---|---|---|
| Utfärda och ändra intyg | `PATCH /api/certificates/update/<i_number>`, `POST /api/certificates/issue/<i_number>` | Intygen i nya Stamboken | PR #62 |
| Lägga till och ändra besättning | `POST /api/manage/herd`, `PATCH /api/manage/herd` | Min besättning och adminsidan för besättningar | #134 (planerad) |

### Konsekvenser

* Bra, eftersom nya modeller inte behöver översätta gamla appens skrivningar,
  och en uppgift ändras bara på ett ställe åt gången.
* Bra, eftersom medlemmarna får veta var funktionen finns nu.
* Dåligt, eftersom gamla appen under en tid har både öppna och stängda
  funktioner, och regel 1 kan skjuta upp en stängning tills nya Stamboken har
  kommit ikapp.
* ADR-0006, regel 5 (statuskoder ändras inte) har ett undantag för vägar som
  stängs enligt den här ADR:n.

### Bekräftelse

Kontraktstesterna enligt regel 7, och legacy-regressionen i
[legacy-regression-testing.md](../legacy-regression-testing.md).

## Mer information

* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* Specen för #117 (besättningens kontaktuppgifter från matrikeln) ligger i
  driftrepot och beskriver i vilken ordning besättningsskrivningarna stängs.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-11-23 | Jonas | Beslutat |
