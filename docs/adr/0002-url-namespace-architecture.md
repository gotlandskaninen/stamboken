---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0002: URL-struktur och reserverade namnrymder

## Kontext och problem

`gotlandskaninen.se` är rot för flera delsystem: Payload CMS (catch-all
`/[slug]`), Stamboken, medlemsregistret, Payload admin och CMS API, Flask API
och uppladdade filer (nginx-proxade) samt legacy React-appen på en egen
subdomän. Utan explicit ägarskap av varje topp-nivå-path kolliderar nya sidor
med Payloads catch-all vid deploy. Flask-endpoints under `/api/*` ägs av nginx
och kan inte flyttas, och legacy-appen måste fungera under migrationen
([ADR-0006](0006-api-compatibility-during-migration.md)).

## Alternativ

* Prefixa alla app-sidor under /app/: avvisat, eftersom det bryter befintliga
  `/stamboken`- och `/admin`-bokmärken och OAuth-redirect-URI:er
* Flytta Payload till egen subdomän: avvisat, eftersom det ger fler
  OAuth-redirect-URI:er och mer nginx-konfig, och inte löser kollisionen
  mellan `/stamboken` och redaktionella sidor
* Reserverade topp-nivå-namespaces (valt)

## Beslut

Valt alternativ: "Reserverade topp-nivå-namespaces", eftersom URL:erna stannar
korta och kollisioner fångas vid Payload-validering i stället för vid deploy.

Topp-nivå-paths delas i kod-ägda (reserverade) och redaktionella (Payload
catch-all). Kod-ägda listas explicit i `RESERVED_SLUGS` (Payload-validator)
och organiseras i Next.js route-groups `(app)` (huvudskal) och `(payload)`
(isolerat CMS-skal). Middleware släpper bara in inloggade i auth-krävande
namespaces.

### Namespace-karta

| Namespace | Syfte | Auth | Route-grupp | Ägs av |
|-----------|-------|------|-------------|--------|
| `/stamboken/*` | Herdbook dashboard | Middleware `session` + `requireDashboardSession()` | `(app)/stamboken/(dashboard)` | Next.js |
| `/stamboken/verifiera/<uuid>` | Publik verifiering av digitalt intyg (QR-kod) | Ingen — undantagen i matchern | `(app)/stamboken/verifiera` | Next.js |
| `/medlem/*` | Medlemsregister | Middleware `session` + `requireUser()` | `(app)/medlem` | Next.js |
| `/ansok` | Publik medlemsansökan | Ingen — publik POST | `(app)/(public)/ansok` | Next.js |
| `/medlemsforum` | Publik sida | Ingen | `(app)/(public)/medlemsforum` | Next.js |
| `/stamboken-online` | Publik sida | Ingen | `(app)/(public)/stamboken-online` | Next.js |
| `/bli-genbanksbesattning` | Publik informationssida (steg-för-steg) | Ingen | `(app)/(public)/bli-genbanksbesattning` | Next.js |
| `/bli-genbank` | Sidans tidigare adress; permanent omdirigering till `/bli-genbanksbesattning` | Ingen | `(app)/(public)/bli-genbank` | Next.js |
| `/auth/*` | Inloggning | Ingen | `(app)/(auth)/auth` | Next.js |
| `/error/*` | Felsidor (404, 500) | Ingen | `(app)/(error)/error` | Next.js |
| `/preview/*` | Payload draft-preview | Inloggad editor/admin | `(app)/(public)/preview` | Next.js |
| `/admin`, `/admin/*` | Payload CMS admin | Middleware `session` + Payload | `(payload)/admin` | Payload |
| `/cms-api/*` | Payload REST | Payload | `(payload)/cms-api` | Payload |
| `/api/*` | Flask API | Flask, per endpoint | *ej Next.js* | nginx → Flask |
| `/api-test/*` | Flask API mot demodatabasen | Flask, per endpoint | *ej Next.js* | nginx → Flask (`api-test`) |
| `/uppladdningar/*` | Uppladdade filer | Ingen | *ej Next.js* | nginx (statiska filer) |
| `/v2` | Gammal adress till Next.js-appen | — | *ej Next.js* | nginx (301 → `/stamboken/`) |
| `/[slug]` | CMS-sidor | Publik | `(app)/(public)/[slug]` | Payload |
| `/` | Landningssida | Publik | `(app)/(public)/page.tsx` | Next.js |

### Middleware

`next-app/src/middleware.ts` skickar besökare utan `session`-cookie till
`/auth/sign-in?return_to=…`:

```ts
matcher: [
  "/stamboken/((?!verifiera(?:/|$))(?!.*\\.).*)",
  "/admin/:path*",
  "/medlem/((?!.*\\.).*)",
],
```

Paths med punkt (statiska filer) och `/stamboken/verifiera/*` är undantagna.
Middleware kontrollerar bara att cookien finns; sessionen valideras av
`requireUser()`/`requireDashboardSession()` och av Flask. När sessionen inte
är giltig skickar `requireUser()` till samma sign-in-sida med `return_to`.

### Reserverade slugs (Payload-validator)

`next-app/src/hooks/validateSlug.ts` stoppar redaktörer från att skapa sidor
som kolliderar med kod-ägda namespaces. Listan **måste** hållas synkroniserad
med tabellen ovan:

```text
admin, ansok, api, api-test, cms-api, cms-graphql, auth, stamboken,
stamboken-online, medlem, medlemsforum, bli-genbank, bli-genbanksbesattning, v2,
uppladdningar, _next, static, favicon.ico, robots.txt, sitemap.xml, error,
not-found, preview
```

`cms-graphql` är reserverad eftersom Payload är konfigurerad med den sökvägen
(`routes.graphQL` i `next-app/src/payload.config.ts`).

### Legacy-subdomänen

Legacy-appen ligger kvar på sin subdomän tills `/stamboken/*` täcker samtliga
legacy-vyer; avveckla inte tidigare. Vid avveckling tas nginx server-blocket
bort, legacy-jobben (`build-legacy-prod`, `build-legacy-test`) rensas ur
`.github/workflows/build-and-publish.yml` och denna ADR uppdateras. Ingen
redirect från legacy-subdomänen till `/stamboken/*` planeras: legacy-URL:er
delas sällan externt, och mer nginx-konfiguration kostar mer än den ger.

`api` och `api-test` är samma image mot var sin databas (`herdbook` och
`herdbook_demo`). nginx skickar `/api/` till `api` och `/api-test/` till
`api-test`.

### Checklista: lägga till ett nytt topp-nivå-namespace

Gör **allt** detta i samma PR:

1. [ ] Lägg till slug i `RESERVED_SLUGS` (`next-app/src/hooks/validateSlug.ts`)
2. [ ] Beslut om auth — behövs middleware matcher-entry?
   * Ja → lägg till i `next-app/src/middleware.ts` `matcher`-listan
3. [ ] Välj route-grupp: `(app)/(public)/*`, `(app)/<namespace>` med egen
   auth-layout, eller ny grupp?
4. [ ] Uppdatera namespace-kartan i denna ADR
5. [ ] Uppdatera `CLAUDE.md` URL-struktur-sektionen
6. [ ] Om nginx-rewrite krävs (proxy till Flask/upstream) — uppdatera
   relevant nginx-conf under `nginx/`

### Konsekvenser

* Bra, eftersom redaktörer inte kan råka blockera kod-vägar (validatorn
  kastar fel) och `RESERVED_SLUGS` är enda sanningskällan för dem.
* Bra, eftersom route-groups gör uppdelningen auth/publik tydlig i
  filstrukturen.
* Dåligt, eftersom `RESERVED_SLUGS`, middleware-matchern, denna ADR och
  `CLAUDE.md` måste uppdateras tillsammans när namespaces tillkommer.
* Dåligt, eftersom redaktörer inte kan återanvända reserverade slugs.

### Bekräftelse

`scripts/check-adr-refs.py` jämför `RESERVED_SLUGS` och middleware-matchern i
kodblocken ovan med koden. Playwright-projekten `public-tests` och
`owner-tests` i `next-app/playwright.config.ts` täcker publik åtkomst och
inloggning.

## Mer information

* [ADR-0003: Payload CMS inbäddat i Next.js](0003-payload-cms-in-nextjs.md)
* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* [ADR-0008: Serverförst dataarkitektur i Next.js](0008-server-first-data-architecture.md)
* [ADR-0012: Releasebaserad driftsättning](0012-release-based-deployment.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-07 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
| 2026-11-06 | Jonas | `api-test` reserverad och tillagd i namnrymdstabellen |
