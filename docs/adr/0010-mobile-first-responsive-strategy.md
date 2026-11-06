---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0010: Mobile-first som responsiv strategi

## Kontext och problem

Friktion är bevarandedatas fiende: varje onödigt tryck betyder data som aldrig
hamnar i systemet. Uppfödarna sköter sin besättning med telefonen i handen i
ladugården, medan genbanksansvariga arbetar med tabeller, massregistrering och
godkännandeköer vid en dator. Principen är "fungerar det enhänt i ladugården
fungerar det överallt". 375 px är den smalaste skärm vi designar för.

## Alternativ

* Desktop-first för alla ytor: avvisat, eftersom det bryter 375-px-kravet för
  uppfödarnas vanligaste situation
* Mobile-first för alla ytor: avvisat, eftersom ytor för genbanksansvariga
  blir sämre på desktop, där de används
* Uppdelning efter användargrupp (valt)

## Beslut

Valt alternativ: "Uppdelning efter användargrupp", eftersom varje yta då
optimeras för hur den används. Varje ny komponent fungerar i mobil-,
surfplatte- och desktopbredd.

1. **Uppfödarvända ytor** (min besättning, individer, kullar/parningar,
   årsrapport, intyg, överlåtelser, profil) designas mobile-first vid 375 px,
   för en hand; desktop är progressiv förbättring. 375-px-kravet är
   godkännandegränsen:
   * ingen horisontell scroll och ingen nyp-zoom vid 375 px;
   * på pekskärm är tryckytor minst 44 × 44 px, och tryckytor bredvid varandra
     har minst 8 px mellanrum. Länkar i löptext är undantagna; flikar,
     segmentknappar och listrader får stå kant i kant;
   * på pekskärm har formulärfält minst 16 px text (annars zoomar iOS Safari
     in vid fokus).

   Pekskärmsreglerna ligger bakom `@media (pointer: coarse)`, så skrivbordet
   behåller de tätare måtten (15 px fält, 36 px små knappar).
2. **Ytor för genbanksansvariga och admin** (adminpanel, matrikel/medlemsadmin,
   massregistrering, godkännandeköer, genetik-dashboard) designas desktop-first;
   mobilen ska vara en fungerande läsreserv (innehållet nås, inga
   layoutfällor), men redigeringsflöden optimeras inte för telefon.
3. **Komponentregel** ([DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) §4):
   responsiva grid-storlekar, filterrader som bryts, inga fasta
   desktop-bredder i delade komponenter.
4. **Verifiering:** uppfödarflöden kontrolleras vid tre bredder — bas (375 px),
   ≥640 px och ≥900 px — som en del av verifieringen av varje funktion. 900 px
   är där appskalet byter från hamburgermeny till inline-navigering
   (`next-app/src/components/shell/topbar.module.css`).

### Konsekvenser

* Bra, eftersom ladugårdsfallet skyddas av en testbar gräns, 375-px-kravet.
* Bra, eftersom granskare har en namngiven princip att hålla ny UI mot.
* Dåligt, eftersom ytor för genbanksansvariga medvetet inte är
  mobiloptimerade.
* Dåligt, eftersom varje uppfödarvänd funktion kostar verifiering vid tre
  bredder.

### Bekräftelse

`next-app/e2e/touch-targets.spec.ts` mäter tryckytor och formulärtext på
uppfödarsidorna.

## Mer information

* [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) §4 — levande komponentregel
* [ADR-0009: Stambokens designsystem för all UI](0009-stamboken-design-system.md) — appskalet implementerar strategin

Kvarvarande mobilskuld spåras i det privata driftrepot och i projektets
GitHub Issues.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-03 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-10-30 | Jonas | Kravet heter 375-px-kravet och kontexten står utan arkivdokument; tryckytor och formulärtext på pekskärm ingår i kravet och mäts av ett e2e-test |
| 2026-11-06 | Jonas | MADR-format, kortad |
