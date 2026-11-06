# Databasmigrationer

Två separata system: **Peewee** för `herdbook`-databasen
(`app/utils/database.py`) och **Payload/Drizzle** för `herdbook_cms`
(`next-app/src/migrations/`, se [README där](../next-app/src/migrations/README.md)).

## Peewee (Flask-API)

### Skriva en ny migration

1. Lägg `migrate_N_to_N+1()` sist i kedjan i `app/utils/database.py`, lägg in
   den i `MIGRATIONS` och höj `CURRENT_SCHEMA_VERSION`. Kedjan ska vara
   lucklös och stigande.
2. Raden i `SchemaHistory` ska skrivas i samma `DATABASE.atomic()`-block som
   schemaändringen. Annars kan en halvt körd migration låsa databasen i fel
   version.
3. Migrationen körs på databaser i alla äldre versioner, inte bara N.
   Referera aldrig en tabell som skapas av en senare migration. Hjälpfunktioner
   som loopar över tabeller (till exempel audit-triggers) ska hoppa över
   tabeller som inte finns än och köras igen när tabellen skapas. Gör
   migrationen idempotent: lägg bara till en kolumn som saknas.
4. Grundtabellerna (bland annat `hbuser`) skapas av `init()`, inte av kedjan.
   Att spela upp kedjan från en helt tom databas är ingen väg som stöds.
5. `check_migrations()` tar ett advisory lock, så samtidiga API-processer är
   redan hanterade. Skriv inga egna lösningar för det.

### Merga en branch med migrationer

* Kontrollera att båda sidors kedjor bara har lagts till i slutet:

  ```bash
  git grep -nE "CURRENT_SCHEMA_VERSION|def migrate_" origin/main -- app/utils/database.py
  grep -nE "CURRENT_SCHEMA_VERSION|def migrate_" app/utils/database.py
  ```

* Har `main` redan tagit ditt nummer: numrera om din migration till nästa
  lediga och höj versionen igen.
* En långlivad branch som har mergat in `main` och numrerat om: använd
  `git merge origin/main`, aldrig linjär rebase. En rebase spelar upp
  commits från före omnumreringen och tvingar dig lösa numreringen igen.

### Testa

* `TestDatabaseMigration` i `app/tests/test_database.py` spelar upp kedjan och
  kör den samtidigt från flera processer. Lägg till tester för migrationer med
  eget beteende.
* Pytest-stacken bygger schemat med `init()`, inte med migrationer. En ändring
  av en befintlig tabell i ORM:en kräver därför `down -v`, se
  [TESTING.md](../TESTING.md#fällor-i-pytest-stacken).
* Validering mot en kopia av produktionsdata görs med skripten i föreningens
  driftrepo.

## Payload/Drizzle (CMS)

I dev synkar Drizzle `push` schemat automatiskt, så en glömd migration märks
varken i dev eller i CI. Produktion kör bara migrationer och smäller vid
deploy om en saknas. **Varje ändring av en collection eller ett fält kräver
en migration**, skapad i next-app-containern och committad:

```bash
docker compose exec next-app pnpm migrate:create <namn>
```

Detaljer: [next-app/src/migrations/README.md](../next-app/src/migrations/README.md).
