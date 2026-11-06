---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0009: Stambokens designsystem för all UI

## Kontext och problem

Next.js-appen var uppdelad mellan två designsystem: den köpta dashboard-mallen
Mira Pro (licens från MUI Store, vars licens förbjuder att källkoden sprids,
därför var repot privat) för den inloggade `/stamboken`-dashboarden, och
Stambokens eget designsystem (papper/bläck-palett, Source Serif 4 + IBM Plex)
på de publika CMS-sidorna och i inloggningen. Det gav dubbla
stylingkonventioner, ett licensierat beroende som inte kunde publiceras och en
dashboard som såg annorlunda ut än föreningens identitet.

## Alternativ

* Behålla två designsystem: avvisat, eftersom det ger dubbla konventioner och
  den licensierade mallen hindrar ett publikt repo
* Mira Pro för all UI: avvisat, eftersom licensen hindrar publicering och de
  publika sidorna skulle behöva göras om bort från föreningens identitet
* Stambokens designsystem för all UI (valt)

## Beslut

Valt alternativ: "Stambokens designsystem för all UI", eftersom det ger en
identitet, en konvention och inget licensierat beroende. Mira Pro är borttaget
och ingen ny kod får följa Mira-mönster.

1. **Tokens är enda sanningskällan** för färg, typografi, avstånd, radier,
   skuggor och rörelse: `next-app/src/styles/tokens.css`, importerad i
   `next-app/src/app/(app)/layout.tsx`, i synk med designöverlämningens
   `tokens.css`. Nya ytor byggs av sb-primitiverna (`.sb-btn`, `.sb-card`,
   `.sb-badge`, `.sb-input`, `.sb-meta`, `.sb-eyebrow`, …) och/eller
   CSS-moduler som använder `--sb-*`-variablerna.
2. **Hybridregel:** vanlig CSS från token-lagret är basen för ramverk, layout,
   kort, badges och knappar. MUI används för komplexa widgets (DataGrid,
   DatePickers, dialoger, autocomplete, selects) och temas enbart av det
   gemensamma temat i `next-app/src/theme/stamboken.ts`, som speglar token-värdena. Inget andra
   `createTheme`, ingen temaväljare.
3. **Förbjudet i ny kod:** komponenter eller mönster från Mira-mallen —
   flervariant-teman, temaväljare, sidebar- och navbar-skal.
4. **Bara ljust tema.** Ett framtida mörkt läge är en utökning av
   token-lagret, inte ett andra temaobjekt.
5. **Appskal** utan sidebar: sticky topbar med inline-navigering (≥900 px) /
   hamburgermeny (<900 px), masthead, sticky flikar och EU-sidfot
   (`next-app/src/components/shell/`). Rollstyrda val (t.ex. Admin) ligger i
   avatarmenyn.
6. **Min besättning** har fyra flikar — Översikt, Kaniner, Kullar & parningar
   och Släktträd — definierade i `MB_TABS`
   (`next-app/src/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning-ui.tsx`)
   och ritade av `next-app/src/components/shell/TabBar.tsx`; på smal skärm
   scrollar flikraden i sidled. Fliken Kaniner
   visar kort (förval) eller lista; valet sparas i webbläsaren (`KaninView` i
   `KaninerTab.tsx`) och filtret visar aktiva kaniner som förval. Arbete över
   hela genbanken görs i Alla kaniner: en server-paginerad DataGrid från
   900 px och en kortlista under
   (`next-app/src/components/explorer/RabbitExplorer.tsx`). Statusen visas
   enligt [ADR-0011](0011-status-detection.md).
7. Tokens är slutgiltiga; avvikelser kräver en ändring på designsidan, inte
   ad hoc-CSS. Adminpanelen får använda MUI-mönster inom det gemensamma
   skalet; nya ytor följer designsystemet från start.

### Konsekvenser

* Bra, eftersom en visuell identitet och en stylingkonvention gäller från
  landningssidan till dashboarden.
* Bra, eftersom den licensierade mallen är borta ur koden, vilket gjorde det
  möjligt att publicera repot med ren historik.
* Dåligt, eftersom det inte finns något mörkt läge.
* Dåligt, eftersom sidor utan egen design fick en ommålning och ser mindre
  genomarbetade ut än Min besättning tills de får en egen designomgång.

## Mer information

* Designöverlämningens tokens: [docs/design/design_handoff_min_besattning/tokens.css](../design/design_handoff_min_besattning/tokens.css) (mockarna och designspecen ligger i det privata driftrepot)
* [ADR-0002: URL-struktur och reserverade namnrymder](0002-url-namespace-architecture.md) — inga URL-ändringar i ommålningen
* [ADR-0008: Serverförst dataarkitektur i Next.js](0008-server-first-data-architecture.md) — RSC-gränserna gäller även ny UI
* [ADR-0010: Mobile-first som responsiv strategi](0010-mobile-first-responsive-strategy.md) — appskalets brytpunkter implementerar den

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-07 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
