---
status: "proposed"
date: 2026-11-14
decision-makers: Jonas
---

# ADR-0014: Behörighetsmodell för Stambokens API

## Kontext och problem

Behörigheterna i Stamboken har vuxit fram i flera steg: legacy-appens roller,
genbanksansvariga per genbank, medlemsregistret med egna roller och åtkomst
till besättningar via medlemskap. Reglerna finns i koden och i
[ADR-0007](0007-blueprint-refactor.md) men har aldrig samlats. Den som
skriver en ny endpoint behöver veta vilka roller som finns och var kontrollen
ska göras. Payload CMS har egna roller och beskrivs i
[ADR-0003](0003-payload-cms-in-nextjs.md).

## Alternativ

Alternativen är formulerade i efterhand; modellen växte fram utan ett samlat
beslut.

* Bara rolldekoratorer: avvisat, eftersom en dekorator inte vet vilken genbank
  eller besättning anropet rör.
* Row-level security i PostgreSQL: avvisat, eftersom varje request då måste
  sätta användarkontext i databasen och legacy-frågorna och Peewee-koden
  skulle skrivas om.
* Kontroll i varje endpoint med delade hjälpfunktioner (valt)

## Beslut

Valt alternativ: "Kontroll i varje endpoint med delade hjälpfunktioner",
eftersom det passar befintlig kod och scope-kontrollen ligger nära logiken.
**Flask avgör alltid behörigheten**, per endpoint och mot den genbank,
besättning eller individ som anropet faktiskt rör. Roller hålls få och
scopade; rätt till en besättning härleds på ett ställe.

### Roller

Rollerna lagras i tabellen `user_role`, se *Lagring av roller* nedan. Tills
den migrationen är körd ligger de som JSON-lista i `privileges` på `User`
(`app/utils/database.py`).

| Roll | Omfattning | Typiskt |
|------|------------|---------|
| `admin` | Hela systemet | Systemansvarig |
| `manager` | En genbank | Genbanksansvarig |
| `viewer` | En genbank | Läsrätt i genbanken |
| `owner` | En besättning | Uppfödare (äldre form) |
| `matrikel_admin` | Medlemsregistret, inga stamboksrättigheter | Matrikelansvarig |

**Rätt till en besättning** härleds i `User.effective_herd_ids()`: äldre
`owner`-roller, besättningar som ägs av det medlemskap där användaren är
huvudmedlem, och aktiva åtkomstgrants (`HerdAccessGrant`, med valfritt
slutdatum). Ny kod frågar `effective_herd_ids()` eller metoderna som bygger
på den, och läser inte `privileges` direkt.

**Att sälja eller flytta en kanin** är en snävare rätt än att redigera den:
den avgörs av `User.can_transfer()` (admin, ansvarig för genbanken, eller
ägaren via `transfer_herd_ids()`). En åtkomstgrant ger redigeringsrätt men
aldrig rätt att flytta djur ur besättningen.

### Var kontrollen görs

1. **Inloggning:** `@json_login_required` på alla nya endpoints utom de som
   medvetet är publika (ansökningsformuläret, intygsverifieringen). En publik
   endpoint säger det i sin docstring och tar bara emot det formuläret behöver.
2. **Grov rollkontroll:** `@manager_required`, `@admin_required`,
   `@matrikel_admin_required`, `@matrikel_read_required`
   (`app/blueprints/common.py`). De säger bara att användaren har rollen
   någonstans.
3. **Scope:** endpointen kontrollerar mot den resurs anropet rör —
   `check_genebank_access(genebank_id)` för genbanker; för besättningar och
   individer metoderna på `User` (t.ex. `can_edit`, `can_transfer`) eller
   `effective_herd_ids()`. För skrivningar på individ görs steg 3 och 4 av en
   central skrivare under låset ([ADR-0015](0015-individual-write-commands.md)).
4. **Resursen läses från databasen först.** Genbank, besättning och ägare
   tas från den lagrade raden, aldrig från request-body eller query
   ([ADR-0008](0008-server-first-data-architecture.md)). Fält som styr
   behörighet eller ägarskap tas inte emot genom generella uppdateringar.
5. **Next.js** använder `useUser()` (`is_admin`, `is_manager`, `is_owner`)
   bara för att visa eller dölja UI. En dold knapp är ingen kontroll.

Fel ger 401/403 som RFC 9457-svar via `problem()`; legacy-endpoints behåller
sitt format ([ADR-0006](0006-api-compatibility-during-migration.md)).

### Lagring av roller

<!-- check-adr-refs: planned user_role granted_at -->

Beslutat 2026-10-31. Rollerna låg som JSON-lista i textkolumnen
`hbuser.privileges`, vilket gjorde frågor om alla användare till
Python-loopar, lät databasen ta emot roller mot saknade besättningar och
gjorde en rolländring till en kopia av hela kontoraden i `audit_log`.
Rollerna lagras i stället som rader i `user_role`: konto, roll, `genebank_id`
eller `herd_id`, `granted_by` och `granted_at`, med främmande nycklar
(`ON DELETE CASCADE` för kontot, `RESTRICT` för genbank och besättning), en
CHECK på scope (inget för `admin` och `matrikel_admin`, genbank för `manager`
och `viewer`, besättning för `owner`) och ett unikt index med
`NULLS NOT DISTINCT` på konto, roll och scope. Inget slutdatum förrän en roll
behöver det; tidsbegränsad åtkomst finns i `HerdAccessGrant`. Att behålla
JSON-texten avvisades, eftersom frågorna förblir Python-loopar och
referenserna okontrollerade; `jsonb` med GIN-index avvisades, eftersom det
saknar främmande nycklar, CHECK och unikhet och revisionen blir densamma.

* `User.privileges` är en härledd vy i det gamla listformatet; legacy-
  endpointsen ger samma array som förut
  ([ADR-0006](0006-api-compatibility-during-migration.md)) tills legacy är
  avvecklad.
* Frågor om en användare går via metoderna på `User`. Frågor om vilka
  användare som har en roll ställs i SQL mot `user_role`, aldrig genom att
  läsa `privileges` för alla användare.
* Roller skrivs genom `update_role()`, som sätter `granted_by`. Varje
  tilldelning och borttagning blir en egen `INSERT` eller `DELETE` i
  `audit_log`, med id:n och utan kontots personuppgifter.
* `HerdAccessGrant` ligger kvar i egen tabell: den gäller en person i ett
  medlemskap, inte ett konto, och följer medlemskapets status.
* Migrationen (expand med dubbelskrivning, sedan contract) körs i första
  releasen efter servermigreringen. Torrkörning mot produktionsdumpen är grind
  före deploy: antal rader = antal poster minus dubbletter, inga dinglande
  referenser, minst en aktiv admin.
* Vakterna i `update_role()` står kvar för legacy-formatets felsvar (legacy
  skickar `genebank: -1` när ingen genbank är vald). När JSON-kolumnen är
  borttagen går rollback bara via dump.

Synlighetsnivåerna för besättningarnas kontaktuppgifter och vem som får se
vad i medlemsregistret beslutas separat.

### Konsekvenser

* Bra, eftersom den som skriver en ny endpoint har en plats att läsa och
  besättningsrätt härleds på ett ställe.
* Bra, eftersom roller mot en besättning eller genbank som inte finns, och
  roller utan rätt scope, inte går att lagra.
* Dåligt, eftersom kontrollerna är spridda över endpoints och en glömd kontroll
  inte syns i koden; varje ny endpoint behöver egna tester för 401, 403 och
  fel scope.
* Dåligt, eftersom `user_role` kostar en tabell och en fråga till per
  inloggad användare och request.

### Bekräftelse

* Varje ny endpoint har tester för oinloggad (401), saknad roll (403) och
  roll i fel genbank eller besättning (403).
* Behörighetsändringar granskas särskilt i PR-review. Kod som läser
  `privileges` för fler än en användare flaggas i review.
* `app/tests/test_effective_access.py` låser härledningen av besättningsrätt.
* Kontraktstesterna för arrayen och `/api/manage/role` passerar oförändrade,
  utom de vars uppsättning lagrade poster som tabellen förbjuder; de
  kontrollerar i stället att databasen vägrar roll utan scope och dinglande
  besättning.

## Tillägg 2026-11-14: genbankshjälpare (föreslaget)

Föreslaget tillägg, att godkännas av beslutsfattaren. Inläsningskön
([docs/inkorg.md](../inkorg.md)) behöver en lagrad roll till:

| Roll | Omfattning | Typiskt |
|------|------------|---------|
| `helper` | En genbank | Genbankshjälpare i inläsningskön |

* `helper` lagras och delas ut som de andra rollerna: av admin, eller av
  genbanksansvarig i sin egen genbank.
* En hjälpare ser hela inläsningskön och originalen i den, och får läsrätt i
  sin genbank. Hon har **ingen allmän rätt att ändra kaniner**:
  `effective_herd_ids()`, `can_edit()` och `can_transfer()` ger henne inget
  utöver läsrätten.
* Hon skriver bara genom en post i kön som hon själv har i läget `tagen`, för
  en kanin i en genbank där hon är hjälpare. Det är en grant, inte en roll:
  se ADR-0015, tillägg 2026-11-14. Flask prövar den per anrop, under låset,
  mot den lagrade posten.
* "Arbetar i kön" (admin, eller `manager` eller `helper` i någon genbank) är
  den grova kontrollen för köns endpoints. Varje skrivning prövas sedan mot
  kaninen enligt ADR-0015.

## Mer information

* [ADR-0007: Flask-API:et delas upp i blueprints per domän](0007-blueprint-refactor.md)
* [ADR-0008: Serverförst dataarkitektur i Next.js](0008-server-first-data-architecture.md)
* [ADR-0003: Payload CMS inbäddat i Next.js](0003-payload-cms-in-nextjs.md)
* [ADR-0015: Kommandon per avsikt för skrivningar på individ](0015-individual-write-commands.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-10-27 | Jonas | Utkast |
| 2026-10-31 | Jonas | Lagring av roller: tabellen `user_role` ersätter JSON-kolumnen `hbuser.privileges`; införs första releasen efter servermigreringen |
| 2026-11-06 | Jonas | MADR-format, kortad |
| 2026-11-14 | Jonas | Föreslaget tillägg: den lagrade rollen `helper` (genbankshjälpare), utan allmän skrivrätt |
