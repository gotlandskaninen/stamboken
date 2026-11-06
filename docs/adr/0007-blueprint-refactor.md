---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0007: Flask-API:et delas upp i blueprints per domän

## Kontext och problem

`app/herdbook.py` var en monolitisk fil (~2300 rader) med alla API-endpoints.
Nya funktioner (årsrapport, audit, medlemmar, certifikat, uppladdningar)
behövde en struktur utan risk för befintlig funktionalitet. Befintliga
endpoints får inte ändras ([ADR-0006](0006-api-compatibility-during-migration.md))
eftersom legacy-frontend och Next.js delar samma Flask API.

## Alternativ

* Fortsätta i `herdbook.py`: avvisat, eftersom filen växer okontrollerat
* Domänbaserade Blueprints (valt)
* Full omskrivning med FastAPI: avvisat, eftersom det är stor risk under
  migrationen och Peewee ORM är synkron

## Beslut

Valt alternativ: "Domänbaserade Blueprints", eftersom varje domän isoleras
utan risk för befintliga endpoints. **Nya** endpoints organiseras i
Blueprints under `app/blueprints/`. Befintliga endpoints i `herdbook.py`
lämnas där de är tills legacy-frontenden avvecklas.

Var en ny endpoint hamnar:

1. Hör den till en befintlig domän: lägg den i den modulen.
2. Ny domän: skapa `app/blueprints/<domän>.py` och registrera den i
   `register_blueprints()` i `app/blueprints/__init__.py`.
3. Nya endpoints för Next.js får sökvägen `/api/v2/<resurs>` och följer
   kontraktet i [ADR-0008](0008-server-first-data-architecture.md).

Modulnamnen följer domänen, oftast i plural; suffixet `_v2` används där en
legacy-domän med samma namn redan finns (`breeding.py` / `breeding_v2.py`).
`arsrapport.py` och `tokens.py` är tomma moduler som reserverar sina domäner.

URL-prefix: Blueprints använder `url_prefix="/api"`, samma som befintliga
endpoints, och routes anger resten av sökvägen. Undantag: `admin.py` har
`url_prefix="/api/v2/admin"`.

Delade dekoratorer och hjälpfunktioner finns i `app/blueprints/common.py`:

* `json_login_required` — standard för nya endpoints; 401 som RFC 9457
* `manager_required` — grov gate: **någon** manager- eller admin-roll
* `admin_required` — kräver admin-roll
* `matrikel_admin_required`, `matrikel_read_required` — medlemsregistrets roller
* `check_genebank_access(genebank_id)` — per-genbank-auktorisering; returnerar ett felsvar eller `None`
* `problem(status, title, detail)` — RFC 9457-felsvar (v2-endpoints)
* `json_error(message, status)` — felsvar i legacy-format
* `login_required` — svarar 401 i legacy-format; bara för legacy-kompatibla endpoints

Regler för blueprint-kod:

1. `@manager_required` kontrollerar bara att användaren har manager-/admin-roll
   överhuvudtaget. Endpoints som opererar på en specifik genbank **måste**
   även anropa `check_genebank_access(genebank_id)`. Endpoints som opererar på
   en besättning eller en individ måste kontrollera behörigheten mot just den
   besättningen. Se [ADR-0014](0014-authorization-model.md).
2. Blueprints är tunna route-handlers: validera indata, kontrollera
   behörighet, anropa logiken, forma svaret.
3. Affärslogiken ligger under `app/utils/`: i `data_access.py` eller i en
   domänmodul.
4. Endpoints utanför `/api/v2/` som bara Next.js använder markeras
   `# [Next.js]` ([ADR-0006](0006-api-compatibility-during-migration.md)).
5. Inga cirkulära importer: blueprints importerar aldrig `herdbook.py`.
6. Legacy-endpoints får inte flyttas före legacy-avvecklingen; efter den
   flyttas de gradvis från `herdbook.py` till blueprints. En
   `[Next.js]`-endpoint i `herdbook.py` får flyttas till en blueprint när
   domänen ändå berörs.

### Konsekvenser

* Bra, eftersom nya endpoints hamnar i rätt domän från start och
  domänspecifik kod är lätt att hitta.
* Bra, eftersom migrationen kan ske gradvis utan risk.
* Dåligt, eftersom endpoints finns på två platser under migreringsperioden;
  `herdbook.py` har fortsatt växa (2844 rader 2026-10) eftersom regeln inte
  följts fullt ut.
* Dåligt, eftersom delade dekoratorer måste hållas synkade med motsvarande
  kontroller i `herdbook.py`.

## Mer information

* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* [ADR-0008: Serverförst dataarkitektur i Next.js](0008-server-first-data-architecture.md)
* [ADR-0014: Behörighetsmodell för Stambokens API](0014-authorization-model.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-03 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
