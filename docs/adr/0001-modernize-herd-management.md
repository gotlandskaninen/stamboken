---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0001: Stegvis modernisering av besättningssidan

## Kontext och problem

Den äldre React-frontenden (legacy-appen) var svår att använda på telefon,
hade komplex navigation med funktioner gömda i popup-fönster, blandade
UI-mönster och en monolitisk struktur. Next.js-appen gör det möjligt att
modernisera användarupplevelsen utan att legacy-appen stängs på en gång.

## Alternativ

* Porta befintlig kod direkt: avvisat, eftersom gamla problem följer med
* Total omskrivning från grunden: avvisat, eftersom det är tidskrävande och
  funktionalitet kan missas
* Iterativ modernisering (valt)

## Beslut

Valt alternativ: "Iterativ modernisering", eftersom den ger balans mellan ny
design och befintlig funktionalitet och kan testas steg för steg.

Besättningssidan moderniseras stegvis med fokus på:

1. Modern flik-navigering med responsiv design
2. Dubbla vyer: kort (visuell) + lista/tabell (dataintensiv)
3. Smart filtrering med aktiva kaniner som default
4. Förbättrad statusvisning med tooltips
5. Mobil-först approach

Punkt 1–3 preciseras för Min besättning i
[ADR-0009](0009-stamboken-design-system.md), punkt 4 i
[ADR-0011](0011-status-detection.md) och punkt 5 i
[ADR-0010](0010-mobile-first-responsive-strategy.md). Under övergången delar
legacy och Next.js samma Flask-API ([ADR-0006](0006-api-compatibility-during-migration.md)).

### Konsekvenser

* Bra, eftersom designen blir responsiv och fungerar på mobil.
* Bra, eftersom komponentstrukturen blir tydlig och enklare att underhålla.
* Dåligt, eftersom två system går parallellt under migreringen.
* Dåligt, eftersom vana användare måste anpassa sig och funktionalitet kan
  missas vid portering.

## Mer information

* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* [ADR-0009: Stambokens designsystem för all UI](0009-stamboken-design-system.md)
* [ADR-0010: Mobile-first som responsiv strategi](0010-mobile-first-responsive-strategy.md)
* [ADR-0011: Statusdetektering och dödsorsaksanalys](0011-status-detection.md)
* [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2025-12 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
