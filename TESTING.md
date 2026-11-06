# Testing Guide for Herdbook

Hur Herdbooks tester körs: pytest för Flask-API:et, vitest och Playwright för
`next-app/`, samt den lokala CI-grinden.

## Innehåll

1. [Testarkitektur](#testarkitektur)
2. [Köra tester lokalt](#köra-tester-lokalt)
3. [Testfiler och struktur](#testfiler-och-struktur)
4. [CI](#ci)
5. [Felsökning](#felsökning)
6. [Legacy Regression Test Suite](#legacy-regression-test-suite)

---

## Testarkitektur

| Lager | Verktyg | Plats |
|-------|---------|-------|
| Flask-API och dataåtkomst | pytest (PostgreSQL) | `app/tests/` |
| Next.js enhetstester | vitest | `next-app/src/__tests__/` |
| Next.js e2e | Playwright | `next-app/e2e/` |
| Legacy-regression | pytest + Playwright | se [Legacy Regression Test Suite](#legacy-regression-test-suite) |
| Skript och compose-filer | bash | `scripts/tests/test-*.sh` |

Alla pytest-tester ärver från `DatabaseTest` (`app/tests/database_test.py`):

- Mot PostgreSQL när `POSTGRES_HOST` och `POSTGRES_DB` är satta. Då krävs
  `FLASK_ENV=testing` och ett databasnamn som innehåller `test`, annars
  vägrar testerna köra (skydd mot att tömma en riktig databas).
- Tömmer tabellerna (`TRUNCATE`) före varje test och skapar syntetisk
  testdata med `insert_default()`.

CI och den lokala grinden kör bara mot PostgreSQL; ett SQLite-läge stöds inte.

---

## Köra tester lokalt

### Flask-API (pytest)

Testerna körs alltid i en isolerad stack med egen databas (`herdbook_test`)
via `docker-compose.pytest.yml`. Kör **aldrig** pytest i dev-containern:
testerna tömmer databasen.

```bash
# Första gången: skapa env-filerna från .default-mallarna i .docker/
# (database-variables.test.env och api-variables.env)

DOCKER_TARGET=test docker compose \
  -f docker-compose.yml -f docker-compose.pytest.yml \
  -p herdbook-pytest up -d database api

# Alla tester
docker exec herdbook-pytest-api-1 pytest /app/tests/ -v --tb=short

# En fil / ett test
docker exec herdbook-pytest-api-1 pytest /app/tests/test_endpoints.py -v
docker exec herdbook-pytest-api-1 pytest \
  /app/tests/test_endpoints.py::TestEndpoints::test_breeding_list -v

# Städa (-v tar bort databasvolymen)
docker compose -p herdbook-pytest down -v
```

#### Fällor i pytest-stacken

1. **Fel worktree.** Projektnamnet `herdbook-pytest` delas av alla checkouts
   på maskinen, och en befintlig `herdbook-pytest-api-1` monterar `./app` från
   den checkout som startade den. Ett grönt resultat kan alltså gälla en annan
   branch. Kontrollera innan du litar på det:

   ```bash
   docker inspect herdbook-pytest-api-1 \
     --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' | grep app
   ```

   Kör du flera checkouts, använd ett eget namn (`-p herdbook-pytest-<namn>`)
   och byt containernamnet i `docker exec` därefter.
2. **Schemaändring i ORM:en kräver ny volym.** Stacken bygger schemat med
   `init()`, som bara skapar saknade tabeller och aldrig kör migrationer. En
   ny eller borttagen kolumn når därför inte en befintlig volym (symptom:
   `violates not-null constraint` eller en störtflod av `ProgrammingError`).
   Kör `down -v` före `up`.
3. **Saknade env-filer i en ny checkout.** `.docker/*.env` är gitignorerade;
   `up` misslyckas utan dem. Skapa dem från `.default`-mallarna.
4. **Intygstester failar på signeringen.** Pekar `api-variables.env` på en
   nyckel som inte finns i containern, kör med utvecklingsnyckeln:

   ```bash
   docker exec -e PDF_SIGNING_KEY=certs/key.pem -e PDF_SIGNING_CA=certs/ca.pem \
     herdbook-pytest-api-1 pytest /app/tests/ -v --tb=short
   ```

5. **Testordning.** Migrationstesterna i `app/tests/test_database.py` ändrar
   det delade schemat. Kör hela sviten; en handplockad ordning med
   migrationsfilen först kan få senare tester att fallera.

### Next.js (vitest, typer, lint)

```bash
cd next-app
pnpm type-check     # tsc
pnpm test           # vitest run
pnpm exec eslint .  # `pnpm lint` kör eslint --fix och ändrar filer
```

### Playwright (e2e)

```bash
cd next-app
pnpm exec playwright test                                      # e2e/, startar `pnpm dev` på :3000
pnpm exec playwright test --config playwright.legacy.config.ts # e2e-legacy/
```

e2e-testerna behöver ett Flask-API på `:9090` (`API_INTERNAL_URL`) och
testanvändare; uppsättningen per konfigurationsfil står i
[next-app/README.md](next-app/README.md). RSC-sidor kan inte mockas med
`page.route()` — de hämtar data server-side, så testerna går mot riktigt API.

#### Manuell verifiering mot dev-stacken

- Kontrollera vilken checkout som äger portarna innan du verifierar:
  `docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E "9090|3000"`.
- Gå alltid via nginx på `https://localhost`, aldrig direkt mot `:3000` eller
  `:9090`. Certifikatet är självsignerat, så ignorera certifikatfel
  (`ignoreHTTPSErrors: true` i Playwright).
- Logga in med en testanvändare innan du öppnar skyddade sidor, annars
  skickas du till Google-inloggningen. Testanvändarna skapas av
  bootstrap-skriptet och står i
  [docs/legacy-regression-testing.md](docs/legacy-regression-testing.md).

### Hela CI-grinden lokalt

```bash
scripts/ci-local.sh           # alla steg (lint, trivy, semgrep, pytest, tsc, eslint, vitest, build, images, e2e)
scripts/ci-local.sh --quick   # allt utom e2e och images
scripts/ci-local.sh --help    # lista steg, --only <steg>
```

Skriptet kopierar arbetskatalogen till en snapshot och kör pytest-stacken och
e2e-stackarna med eget projektnamn per worktree; sammanfattningen
(`summary.md`) hamnar bredvid loggarna under `~/.cache/stamboken-ci-local/<hash>/`.
Se `--help` för portar och krav.

- Ändrar branchen bara `*.md` eller filer under `docs/` körs utan flaggor
  bara lint, trivy och semgrep, som i Actions.
- lint granskar bara committade filer som skiljer sig från `origin/main`;
  committa innan du kör.
- e2e-stegen avbryter om portarna är upptagna och säger vem som har dem.
  Skriptet stoppar aldrig någon annans stack.
- Kräver Node 24, som CI.

---

## Testfiler och struktur

`app/tests/` har drygt 100 filer, ordnade efter område. Några utgångspunkter:

| Fil | Beskrivning |
|-----|-------------|
| `database_test.py` | Basklassen `DatabaseTest` |
| `conftest.py` | pytest-konfiguration, databas per xdist-worker, markören `slow` |
| `test_endpoints.py` | API-endpoint-tester (Flask routes) |
| `test_data_access.py` | Data access layer |
| `test_database.py` | Databasmodeller och migrationer |
| `test_permissions.py` | Behörighets- och rolltester |
| `test_legacy_api_contracts.py` | Kontraktstester för legacy-endpoints |
| `test_genetics_*.py` | Genetikberäkningar |

Blueprint-, v2-API- och herd-tracking-tester ligger i egna `test_*.py`-filer;
`ls app/tests` ger hela listan.

### Basklass: DatabaseTest

```python
from tests.database_test import DatabaseTest

class TestMyFeature(DatabaseTest):
    def test_success_case(self):
        # self.admin, self.viewer, self.manager, self.owner - testanvändare
        result = some_function(self.admin.uuid)
        self.assertEqual(result["status"], "success")
```

`insert_default()` skapar genbanker (Gotland, Mellerud), besättningar,
färger, individer, parningar och användare med olika roller. Läs metoden i
`database_test.py` för exakt innehåll.

### Skriva nya tester

1. Ärv från `DatabaseTest` — ger testdata och databashantering.
2. Undvik ordningsberoende; sortera listor före jämförelse.
3. Använd giltiga UUID:er.
4. Testa både lyckade och misslyckade fall.
5. Ändrar du ett API-svar: lägg testet i samma PR (ADR-0006).

---

## CI

Arbetsflödena ligger i `.github/workflows/`. `scripts/ci-local.sh` kör samma
grind lokalt; kör den före en PR och klistra in `summary.md` i PR-texten.

| Arbetsflöde | Trigger | Innehåll |
|-------------|---------|----------|
| `python_tests.yml` | push och PR mot `main` | skripttester (`scripts/tests/`) + pytest mot PostgreSQL-servicecontainer |
| `playwright.yml` | PR mot `main`, push till `feature/**` | `Playwright — Next.js` (e2e mot dev-server) och `Playwright — Legacy (advisory)` (`continue-on-error`, blockerar inte) |
| `lint.yml` | push, PR mot `main` | super-linter |
| `security.yml` | push och PR mot `main` | Trivy och Semgrep |
| `build-and-publish.yml` | se filen | image-byggen och release |

Branch protection (vilka jobb som är obligatoriska) ställs in i
GitHub-inställningarna, inte i förrådet.

---

## Felsökning

- **`No such container`**: stacken är inte uppe — kör `up -d database api` igen.
- **`connection refused`**: databasen är inte redo; följ
  `docker compose -p herdbook-pytest logs -f database` tills den accepterar anslutningar.
- **`SAFETY: Refusing to run tests`**: du kör mot en databas utan `test` i namnet
  eller utan `FLASK_ENV=testing`. Använd pytest-stacken ovan.
- **`duplicate key` / konstiga schemafel**: gammal databasvolym. Kör
  `docker compose -p herdbook-pytest down -v` och starta om.
- **Containerns ägare**: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep pytest`
  visar vilka pytest-containrar som finns; se
  [Fällor i pytest-stacken](#fällor-i-pytest-stacken) för hur du ser vilken
  checkout de monterar.

---

## Legacy Regression Test Suite

Tvålagers-testsuite som verifierar att legacy-frontenden fungerar mot det
aktuella API:et ([ADR-0006](docs/adr/0006-api-compatibility-during-migration.md)).
Kommandon, krav och testanvändare: [docs/legacy-regression-testing.md](docs/legacy-regression-testing.md).

- **Layer 1** — API-kontrakt, pytest: `app/tests/test_legacy_api_contracts.py`,
  körs i den vanliga pytest-stacken.
- **Layer 2** — UI-smoke, Playwright: `next-app/e2e-legacy/` (11 spec-filer),
  konfiguration `next-app/playwright.legacy.config.ts`. Kräver
  local-production-stacken (`bootstrap-local-production.sh`, ligger i stamboken-drift).

| Situation | Layer 1 | Layer 2 |
|-----------|:---:|:---:|
| Ändrat ett `/api/`-endpoint eller responsformat | Ja | Nej |
| Ändrat auth/session-logik | Ja | Ja |
| Före release eller servermigration | Ja | Ja |

Testanvändarna (admin, genbankshanterare, besättningsägare m.fl.) skapas av
`app/cli/create_test_users.py` och är avsedda för lokal utveckling; deras
användarnamn och roller står där.

---

## Relaterade dokument

- [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) - Utvecklingsriktlinjer
- [next-app/README.md](next-app/README.md) - Playwright-konfigurationer
- [docs/legacy-regression-testing.md](docs/legacy-regression-testing.md) - Legacy-regression
- [docs/db-migrations.md](docs/db-migrations.md) - Databasmigrationer
- [CLAUDE.md](CLAUDE.md) - AI-assistentguide
- [ADR-0006](docs/adr/0006-api-compatibility-during-migration.md) - API-kompatibilitet under migration
