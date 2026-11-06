---
status: "proposed"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0003: Payload CMS inbäddat i Next.js

## Kontext och problem

Föreningens webbplats behöver redaktionella sidor (rasbeskrivningar, nyheter,
information om att bli genbank) som styrelsen och de genbanksansvariga kan
redigera utan utvecklare. Sidorna ligger på samma domän som Stamboken
([ADR-0002](0002-url-namespace-architecture.md)) och ska se ut som resten av
appen ([ADR-0009](0009-stamboken-design-system.md)). Stamboken har redan en
Next.js-app och en egen inloggning.

## Alternativ

Alternativen är formulerade i efterhand; valet dokumenterades utan jämförelse.

* Fristående headless CMS som egen tjänst: avvisat, eftersom det ger en
  container, ett API och en inloggning till att hålla ihop, och sidorna
  måste ändå renderas i Next.js
* Markdown-filer i repot: avvisat, eftersom redaktörerna inte är utvecklare
  och varje textändring skulle kräva en PR och en release
* Payload inbäddat i Next.js (valt)

## Beslut

Valt alternativ: "Payload inbäddat i Next.js", eftersom det ger en app och en
deploy, samma komponenter för CMS-sidor och app, och TypeScript-typer för
innehållet.

Payload CMS 3.x bäddas in i Next.js-appen (`next-app`) med en egen
PostgreSQL-databas (`herdbook_cms`). Ingen separat CMS-tjänst.

| Del | Plats |
|-----|-------|
| Konfiguration | `next-app/src/payload.config.ts` |
| Collections (Pages, Navigation, Media, Users) | `next-app/src/collections/` |
| Admin-UI | `/admin` — route-gruppen `(payload)` |
| REST-API | `/cms-api` — inte `/api`, som ägs av Flask |
| Publika sidor | `(app)/(public)/[slug]/page.tsx` (Server Component) |
| Förhandsvisning av utkast | `/preview/[slug]` — kräver inloggad redaktör eller admin |
| Uppladdade CMS-filer | Volymen för uppladdningar, katalogen `cms` (`staticDir` i `next-app/src/collections/Media.ts`) |
| Migrationer | `next-app/src/migrations/` |

Regler för dagligt arbete:

1. **Schemat:** i dev synkar Payload schemat automatiskt (Drizzle `push`);
   i produktion körs **bara** migrationer, via tjänsten `cms-migrate` före
   omstart av `next-app`. Varje schemaändring kräver därför en migration —
   annars märks felet först i produktion. Se
   `next-app/src/migrations/README.md`.
2. **Slugs:** sidor kan inte ta en sökväg som koden äger;
   `next-app/src/hooks/validateSlug.ts` och checklistan i ADR-0002 håller
   listan.
3. **Cache:** collections med publicerat innehåll har
   `afterChange`/`afterDelete`-hooks som invaliderar Next.js-cachen
   (`next-app/src/hooks/revalidateCache.ts`).
4. **Roller:** Payload har två roller, `admin` och `editor`, i
   Users-collectionen. De är skilda från Stambokens roller
   ([ADR-0014](0014-authorization-model.md)). Inloggningen går via
   Stambokens inloggning; Payloads egen lösenordsinloggning är avstängd.
5. **Utseende:** innehållsblocken renderas av egna komponenter i
   `next-app/src/components/blocks/` (via `RenderBlocks`) med Stamboken-temat,
   inte av Payload.

### Konsekvenser

* Bra, eftersom redaktörer redigerar sidorna själva i `/admin`.
* Bra, eftersom CMS-sidor och app delar layout, designsystem och inloggning.
* Dåligt, eftersom det blir två migrationskedjor: Peewee för Stambokens
  databas, Payload för `herdbook_cms`.
* Dåligt, eftersom Payload och Next.js måste uppgraderas i takt.
* Dåligt, eftersom en glömd migration inte märks i dev (regel 1 och
  `cms-migrate`-steget i deployen motverkar det).

## Mer information

* [ADR-0002: URL-struktur och reserverade namnrymder](0002-url-namespace-architecture.md)
* [ADR-0009: Stambokens designsystem för all UI](0009-stamboken-design-system.md)
* [ADR-0014: Behörighetsmodell för Stambokens API](0014-authorization-model.md)
* [Lokal testning av CMS](../local-cms-testing.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-03 | Jonas | Föreslaget |
| 2026-10-27 | Jonas | Utkast |
| 2026-11-06 | Jonas | MADR-format, kortad |
