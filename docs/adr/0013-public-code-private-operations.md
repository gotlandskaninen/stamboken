---
status: "proposed"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0013: Publikt kodrepo, privat driftrepo

## Kontext och problem

Stamboken utvecklades i ett privat repo, av tre skäl: den licensierade
dashboard-mallen (borttagen, [ADR-0009](0009-stamboken-design-system.md)),
driftuppgifter (deploy, servrar, hemligheter) och planeringsmaterial som
bygger på produktionsdata. Koden är licensierad under AGPL-3.0 (`LICENSE`),
som kräver att källkoden erbjuds dem som använder tjänsten över nätet, och
föreningen vill kunna ta emot bidrag utifrån. Drift och data får samtidigt
inte bli publika, och loggar från GitHub Actions i ett publikt repo är
publika.

## Alternativ

* Göra det gamla repot publikt efter historikomskrivning: avvisat, eftersom
  den licensierade mallen och privat material finns i tusentals commits och
  en enda miss publicerar det.
* Allt i ett publikt repo, även deploy: avvisat, eftersom Actions-loggar är
  publika och deploy-hemligheter och servrar blir synliga.
* Fortsätta helt privat: avvisat, eftersom AGPL-3.0 kräver att källkoden
  erbjuds användarna och externa bidrag blir omöjliga.
* Två repon: publikt kodrepo och privat driftrepo (valt)

## Beslut

Valt alternativ: "Två repon", eftersom källkoden då kan delas enligt
licensen medan drift, hemligheter och persondata hålls privata. Projektet
delas upp i två repon i organisationen `gotlandskaninen`: ett publikt kodrepo
(`gotlandskaninen/stamboken`, AGPL-3.0) och ett privat driftrepo
(`gotlandskaninen/stamboken-drift`).

Det publika repot innehåller all kod, tester med syntetiska data,
Dockerfiler och compose-filer, CI som bygger, testar och publicerar images
och releaser, ADR:er, utvecklardokumentation, användarmanual samt Issues och
Project. Det privata driftrepot innehåller deploy-workflow och
serverdokumentation, specar, planer och beslutshistorik från före
uppdelningen, datarättningar och beslut om enskilda djur eller medlemmar samt
testdata och referensvärden som bygger på produktionsdata.

Regler:

1. Det publika repot innehåller ingen produktionsdata, inga servernamn eller
   IP-adresser och inga hemligheter. Issues skrivs utan personuppgifter.
2. Deploy körs från driftrepot med ett versionsnummer; det publika repot
   bygger bara images och releaser ([ADR-0012](0012-release-based-deployment.md)).
3. Nya specar och planer skrivs i driftrepot. Publika dokument (ADR:er,
   README) nämner dem i text, utan länk, eftersom länken inte fungerar för
   andra.
4. Det publika repot började som en enda commit av den rensade koden; den
   gamla historiken finns kvar i det privata, arkiverade repot.

### Konsekvenser

* Bra, eftersom källkoden är tillgänglig enligt licensen och externa
  bidragsgivare kan läsa, köra och testa allt som behövs.
* Bra, eftersom drift, hemligheter och persondata hålls borta från det
  publika repot.
* Dåligt, eftersom två repon ska hållas i synk och en gren som rör båda
  delarna måste delas upp.
* Dåligt, eftersom bidragsgivare inte ser specarna bakom äldre beslut; ADR:erna
  måste därför vara läsbara på egen hand.
* Dåligt, eftersom historiken före uppdelningen inte syns i det publika repot.
* Dåligt, eftersom privat material kan checkas in i det publika repot av
  misstag.

### Bekräftelse

GitHubs secret scanning, Trivys hemlighetsskanning i CI
(`.github/workflows/security.yml`) och granskning av varje PR.

## Mer information

* [ADR-0012: Releasebaserad driftsättning](0012-release-based-deployment.md)
* [ADR-0009: Stambokens designsystem för all UI](0009-stamboken-design-system.md)
* [README](../../README.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-10 | Jonas | Föreslaget |
| 2026-10-27 | Jonas | Utkast |
| 2026-11-06 | Jonas | MADR-format, kortad |
