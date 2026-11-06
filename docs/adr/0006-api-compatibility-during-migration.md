---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0006: API-kompatibilitet under migreringsperioden

## Kontext och problem

Under migreringsperioden kör legacy-frontenden (React/Snowpack) och
Next.js-frontenden parallellt mot samma Flask-API
([ADR-0002](0002-url-namespace-architecture.md)). Ändringar i befintliga
endpoints kan bryta legacy-frontenden, det fanns ingen överenskommelse om vad
som får ändras, och Next.js-endpoints behöver skiljas från legacy-endpoints.
Legacy sparar hela JSON-objekt i state och använder specifika fält, så extra
fält ignoreras i praktiken, men det är inte en medveten design.

## Alternativ

* `/api/v2/`-prefix för alla endpoints: avvisat, eftersom det ger extra
  nginx-routing och komplexitet för bara en konsument, och migreringsperioden
  har slutdatum
* Full FastAPI-rewrite: avvisat, eftersom det är stor risk under pågående
  migration, Flask fungerar, Peewee är synkron och det inte finns något akut
  behov
* Kompatibilitetsregler utan versionering (valt)

## Beslut

Valt alternativ: "Kompatibilitetsregler utan versionering", eftersom det ger
minimalt overhead, fungerar med befintlig infrastruktur och en enkel
kodkonvention. Befintliga endpoints versioneras inte; de följer strikta
kompatibilitetsregler under migreringsperioden. Ny funktionalitet får nya
endpoints.

1. **Ändra inte returformat** på befintliga endpoints som legacy använder.
2. **Lägg till fält i svar** är tillåtet (bakåtkompatibelt) men dokumentera i
   commit-meddelandet.
3. **Ny funktionalitet** får en ny endpoint, i en Blueprint
   ([ADR-0007](0007-blueprint-refactor.md)).
4. **Ta inte bort endpoints eller fält** förrän legacy är helt avvecklad.
5. **Ändra inte HTTP-statuskoder** på befintliga endpoints.

Behövs ett annat svar än legacy-endpointen ger: skriv en ny endpoint under
`/api/v2/<resurs>` enligt [ADR-0008](0008-server-first-data-architecture.md)
och låt den gamla stå kvar orörd. Prefixet `/api/v2/` infördes med ADR-0008
för nya endpoints; det är ingen versionering av de befintliga.

Nya endpoints som bara Next.js använder markeras med en kommentar `# [Next.js]`
vid route-dekoratorn. Legacy-endpoints lämnas okommenterade (default).
Endpoints under `/api/v2/` är Next.js-endpoints per definition och behöver
ingen markering. Sök med `grep -rn "\[Next.js\]" app/`.

### Konsekvenser

* Bra, eftersom ingen extra infrastrukturkomplexitet tillkommer och reglerna
  är tydliga för alla som arbetar med API:et.
* Bra, eftersom en FastAPI-migration kan ske som ett separat projekt efter
  att legacy avvecklats; den bör övervägas när legacy är avvecklad, async
  behövs, Peewee ersätts eller OpenAPI blir ett krav.
* Dåligt, eftersom det kräver manuell disciplin: inget tekniskt skydd mot
  breaking changes utöver kontraktstesterna och code review.

### Bekräftelse

Legacy-kontraktet testas av tvålagerssviten i
[legacy-regression-testing.md](../legacy-regression-testing.md) (API-kontrakt
i pytest + Playwright-smoke mot legacy-UI:t). Kör den vid ändringar i
befintliga endpoints.

## Mer information

* [ADR-0007: Flask-API:et delas upp i blueprints per domän](0007-blueprint-refactor.md)
* [ADR-0008: Serverförst dataarkitektur i Next.js](0008-server-first-data-architecture.md)
* [Legacy regression-tester](../legacy-regression-testing.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-02 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
