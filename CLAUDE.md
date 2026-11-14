# Stamboken – guide för AI-agenter

Digital stambok för genbankskaniner (gotlandskanin och mellerudskanin):
registrering av individer, parningar och kullar, digitala intyg, medlemsregister
och föreningens webbplats. Flask-API (`app/`), Next.js 16 + Payload CMS
(`next-app/`), Postgres, nginx, docker compose. Legacy React-frontend under
avveckling. Snabbstart, tester och hur man kommer igång: [README.md](README.md).

## URL-struktur

Formell definition och checklista för nya topp-nivå-paths:
[ADR-0002](docs/adr/0002-url-namespace-architecture.md).

```text
gotlandskaninen.se/              → Landing page (Next.js)
gotlandskaninen.se/[slug]        → CMS-sidor (Payload)
gotlandskaninen.se/stamboken/    → Stamboken (inloggning krävs)
gotlandskaninen.se/stamboken/verifiera/<uuid> → Publik verifiering av digitalt intyg (QR)
gotlandskaninen.se/medlem/       → Medlemsregister (inloggning krävs)
gotlandskaninen.se/ansok         → Publik medlemsansökan
gotlandskaninen.se/integritetspolicy → Hur föreningen behandlar personuppgifter
gotlandskaninen.se/admin         → Payload CMS admin
gotlandskaninen.se/api/          → Flask-API (via nginx)
gotlandskaninen.se/api-test/     → Flask-API mot demodatabasen (via nginx)
gotlandskaninen.se/cms-api/      → Payload REST API
<legacy-subdomän>                → Legacy React-app (tills den avvecklas)
```

## Payload CMS

Payload 3.x inbäddat som Next.js-plugin med egen databas `herdbook_cms`
([ADR-0003](docs/adr/0003-payload-cms-in-nextjs.md)). Förhandsvisning av
utkast kräver inloggad editor/admin. Roller: admin (föreningens
systemansvarig), editor (styrelse och genbanksansvariga).

**Schema:** dev synkar via Drizzle `push`, produktion kör **enbart**
migrationer, så en glömd migration märks aldrig i dev. Följ
[docs/db-migrations.md](docs/db-migrations.md) vid varje schemaändring;
detaljer i `next-app/src/migrations/README.md`.

## Planering

Tracker: GitHub Issues + Project i organisationen `gotlandskaninen`. Issues är
publika: inga medlemsnamn, inga besättningsnummer kopplade till personer, ingen
proddata, inga serverdetaljer. Design-specar, planer, datarättningar och drift
ligger i föreningens privata driftrepo
([ADR-0013](docs/adr/0013-public-code-private-operations.md)); skriv inga specar
eller planer här, inte heller i `docs/superpowers/`. Issues är den enda kön,
och projektet "Stamboken" på organisationen samlar issues från båda repona.
Säkerhetshål som inte är rättade blir issues i driftrepot. Issues härifrån
läggs till med `gh project item-add`
([ADR-0018](docs/adr/0018-ett-organisationsprojekt-och-issues-som-ko.md)).

## Konventioner

**API**

- Alla routes under `/api/`; nya Next.js-endpoints under `/api/v2/<resurs>`,
  i domänblueprints under `app/blueprints/` med affärslogik i `app/utils/`
  ([ADR-0007](docs/adr/0007-blueprint-refactor.md)).
- Legacy och Next.js delar API: ändra aldrig returformat eller statuskoder på
  befintliga endpoints, ny funktionalitet = ny endpoint
  ([ADR-0006](docs/adr/0006-api-compatibility-during-migration.md)).
- Behörighet avgörs i Flask per endpoint mot resursen anropet rör;
  `@manager_required` är en grov gate, per-genbank-endpoints anropar även
  `check_genebank_access` ([ADR-0014](docs/adr/0014-authorization-model.md)).
- Skrivningar på individ går genom kommandon i `app/utils/individual_commands.py`
  med policytabellen i `individual_policy.py`, aldrig direkt via
  `update_individual` ([ADR-0015](docs/adr/0015-individual-write-commands.md));
  ångra och rättelse via kommandologgen
  ([ADR-0017](docs/adr/0017-individual-command-log-and-undo.md)).
- Felformat i v2: RFC 9457 Problem Details.

**Frontend (Next.js)**

- Svenska först. UI-termerna är fastslagna i [docs/ORDLISTA.md](docs/ORDLISTA.md)
  och grindas av `scripts/check-ui-terms.sh`; raserna skrivs med gemen i löptext.
- Stambokens designsystem: `next-app/src/styles/tokens.css` är källan, MUI (v9)
  bara för komplexa widgets, ljust tema enbart
  ([ADR-0009](docs/adr/0009-stamboken-design-system.md)).
- Uppfödarvända ytor mobile-first, 375 px
  ([ADR-0010](docs/adr/0010-mobile-first-responsive-strategy.md)).
- Nya sidor: Server Components för data, Server Actions för mutationer,
  RTK Query bara för interaktiva features
  ([ADR-0008](docs/adr/0008-server-first-data-architecture.md)).
- EU-stödet visas alltid via `EUFundingBadge`, aldrig ett eget ritat emblem
  ([docs/design/eu-logotyp-regler.md](docs/design/eu-logotyp-regler.md)).

**Databas:** Peewee (synkron), schemaversion i `SchemaHistory`, migrationer
`migrate_X_to_Y()` i `app/utils/database.py`; se
[docs/db-migrations.md](docs/db-migrations.md).

**Branching:** `main` är huvudbranch och PR-mål; arbetsbrancher
`feature/*`, `fix/*`, `chore/*`; releaser är taggar `vX.Y.Z` med GitHub Release
([ADR-0012](docs/adr/0012-release-based-deployment.md)). Tagga bara en
commit på `main` där alla kontroller är gröna, också Playwright: varje PR
testas för sig, så körningen på `main` är den enda som testar summan.

## Tester och verktyg

- **Kör aldrig pytest i dev-containern**, testerna tömmer databasen. Isolerad
  pytest-stack och dess fällor, vitest och Playwright: [TESTING.md](TESTING.md).
- GitHub Actions är grinden för en PR: alla kontroller ska vara gröna före
  merge. Kör inte `scripts/ci-local.sh` inför en PR. Skriptet finns kvar för
  felsökning av ett enskilt steg (`--only <steg>`), se [TESTING.md](TESTING.md).
- Legacy-regression (API-kontrakt + UI-smoke) vid API-ändringar och före
  release: [docs/legacy-regression-testing.md](docs/legacy-regression-testing.md).
- CMS lokalt från tom databas: [docs/local-cms-testing.md](docs/local-cms-testing.md).
  Google-inloggning lokalt: [docs/google-oauth-local-dev.md](docs/google-oauth-local-dev.md).
- Genetik: `docker exec <api-container> flask genetics --help`.
- Playwright MCP mot dev-stacken: alltid `https://localhost` via nginx, ignorera
  certifikatfel, logga in med en testanvändare först; se [TESTING.md](TESTING.md).

## Git

- Långlivad branch med omnumrerade migrationer: `git merge origin/main`,
  aldrig linjär rebase ([docs/db-migrations.md](docs/db-migrations.md)).
- Kringgå aldrig pre-commit (`--no-verify`, `SKIP=`), fixa grundorsaken.
- Inga symlänkar i git (`git diff-tree --no-commit-id -r HEAD | grep 120000`
  ska vara tomt); sanktionerade undantag: `AGENTS.md` och `.markdownlint.yml`.
- PR- och issuenummer upp till ~#150 i äldre kommentarer pekar på det tidigare,
  privata repot.

## ADR-disciplin

Arkitekturbeslut skrivs i `docs/adr/` i kort MADR 4-format efter mallen
`docs/adr/0000-template.md` och förs in i `docs/adr/README.md`. En ny ADR med
regler för dagligt arbete får **en rad med länk** under Konventioner ovan, i
samma commit; resten står i ADR:n. Kör `scripts/check-adr-refs.py` när en ADR
eller koden den beskriver ändras: 0 saknade referenser.

## Mer dokumentation

- [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) — designprinciper, terminologi, fallgropar
