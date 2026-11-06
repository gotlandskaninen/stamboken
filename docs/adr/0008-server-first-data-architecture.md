---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0008: Serverförst dataarkitektur i Next.js

## Kontext och problem

Next.js-frontenden använde RTK Query för all datahämtning och alla
mutationer, och alla sidor var klient-renderade. Det gav cache-race-conditions
(`invalidatesTags` tömmer cachen innan refetch hunnit klart, vilket ger
"Kunde inte hämta" och flimrande UI), dubbla nätverkshopp, laddningsspinnare
vid varje navigering och full klient-hämtning av stora listor. Legacy-frontend
behöver fortfarande samma Flask-endpoints
([ADR-0006](0006-api-compatibility-during-migration.md)), Flask förblir
synkront (Peewee) och migrationen sker sida för sida.

## Alternativ

* Blueprint v2 + RTK Query optimistic updates: avvisat, eftersom det löser
  symptomet (cache-race), inte orsaken
* Server Components + Server Actions (valt)
* Full rewrite till tRPC/FastAPI: avvisat, eftersom det är stor insats och
  Peewee är synkront

## Beslut

Valt alternativ: "Server Components + Server Actions", eftersom cache-problemen
elimineras strukturellt och sidorna renderas på servern.

1. **Server Components** hämtar data, **Server Actions** gör mutationer. Flask
   anropas internt via Docker-nätverket (`API_INTERNAL_URL`).
2. Klientside-fetching (RTK Query) behålls enbart för genuint interaktiva
   funktioner (filter, autocomplete, live-sökning). Nya funktioner med
   mutationer använder RSC + Server Actions; inga nya RTK Query endpoints.
3. Alla server-side Flask-anrop går genom `fetchApi<T>` i
   `next-app/src/lib/api.ts`: alla cookies vidarebefordras (`getAll()`, inte
   bara `session`), `cache: "no-store"` (autentiserade svar cachas aldrig
   mellan användare), ingen JSON-`Content-Type` för `FormData`,
   `redirect: "manual"` så att en 302 från Flask blir `ApiError` 401,
   timeout 10 s som kan ändras per anrop, och `ApiError` vid fel.
4. Server-side auth via `getUser()`, `requireUser()` och
   `requireDashboardSession()` i `next-app/src/lib/auth.ts`. Behörighets-
   kontroller i Next.js styr bara vad som visas; Flask avgör alltid
   ([ADR-0014](0014-authorization-model.md)). Login och logout är Server
   Actions som fångar Flasks `Set-Cookie`. `ClientProviders` (Redux,
   MUI-tema, datumväljare, i18n) laddas bara i dashboard- och
   medlemslayouterna, aldrig i `(public)` eller `(payload)`.
5. `is_owner` innehåller herd-nummer som **strängar** (t.ex. `"G1274"`), inte
   id:n; jämför mot `individual.origin_herd.herd`, inte `.id`. `is_manager` och
   `is_owner` kan vara `null`, inte tom array.
6. Nya v2-endpoints i `app/blueprints/` ([ADR-0007](0007-blueprint-refactor.md)),
   både läs och skriv; legacy-endpoints lämnas orörda. För alla v2-endpoints:
   * URL `/api/v2/<resurs>`.
   * `@json_login_required`. Medvetet publika endpoints (t.ex.
     `GET /api/v2/genebanks/public`, `POST /api/v2/member-applications`,
     `/api/v2/certificates/verify/<token>`) markeras som publika i sin
     docstring.
   * Fel som RFC 9457 Problem Details via `problem()` i `common.py`.
   * Data returneras direkt, utan `{"status": "...", "data": ...}`-wrapper.
7. Mutation-endpoints (PATCH/POST/DELETE) returnerar full uppdaterad entitet
   (HTTP 200/201), laddar entiteten först för behörighetskontroll (litar inte
   på id:n eller ägarskap från frontend) och anropar
   `trigger_invalidation(genebank_id)` (`app/utils/cache_invalidation.py`)
   efter ändringar som påverkar stamtavlan. Inbreeding/MK skippas i svaret.
8. Läs-endpoints returnerar alla fält frontend behöver, optimerade för
   server-to-server, med svensk kollation i ORDER BY där relevant.
9. Server Actions anropar v2-endpoint via `fetchApi`, kör `revalidatePath()`
   efter success (inte `revalidateTag`, som bara Payload-hookarna använder för
   CMS-sidor) och visar `ApiError.detail` i formuläret. Klientkomponenten
   använder `useTransition` så att det gamla UI:t syns tills den nya
   renderingen är klar.
10. RSC-sidor har `export const dynamic = "force-dynamic"`. Legacy
    `GET /api/individual/<n>` returnerar `200 null` vid saknad individ; använd
    `fetchApi<Individual | null>` + `notFound()`.

Migrationsläge 2026-10: individ, profil, adminpanel och medlemsregister är
RSC + Server Actions; Min besättning har RTK Query kvar i vissa dialoger; Alla
kaniner och provparning är SSR + RTK Query för filtrering; Genetik är
klientsida. Redux `Provider`, `authSlice` och `SessionExpiredModal` finns kvar
för omigrerade sidor; `apiSlice` krymper gradvis, och `authSlice` och
`SessionExpiredModal` tas bort när de sista klientsidorna migrerats.

### Konsekvenser

* Bra, eftersom cache-race elimineras strukturellt och sidor laddas snabbare.
* Bra, eftersom auth blir enklare (server-to-server cookies) och RTK Query
  krymper gradvis.
* Dåligt, eftersom två datahämtningsmönster samexisterar under migrationen.
* Dåligt, eftersom Docker Compose behöver `API_INTERNAL_URL`.

## Mer information

* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* [ADR-0007: Flask-API:et delas upp i blueprints per domän](0007-blueprint-refactor.md)
* [ADR-0014: Behörighetsmodell för Stambokens API](0014-authorization-model.md)

Den detaljerade tekniska specen med kodexempel ligger i det privata driftrepot.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-03 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
