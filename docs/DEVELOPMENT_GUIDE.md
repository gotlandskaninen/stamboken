# Stamboken - Development Guide

Designprinciper, terminologi och fallgropar för utveckling av Stamboken
(stambok för gotlandskanin och mellerudskanin). Stack: Next.js 16, React 19
och MUI 9 via Stambokens designsystem
([ADR-0009](adr/0009-stamboken-design-system.md)). Konventioner för API,
blueprints, Server Components, tester och branching finns i
[CLAUDE.md](../CLAUDE.md) och dubbleras inte här; testkommandon finns i
[TESTING.md](../TESTING.md).

## Design-principer

### 1. **Användarfokus - Svenska Först**

**REGEL:** Svenska är standardspråk. UI-text läggs som i18next-nycklar i
`next-app/messages/sv.json` (engelska och tyska översätts i motsvarande
filer), inte som hårdkodade strängar.

```typescript
// RÄTT
<Button>{t("...")}</Button> // nyckel i sv.json: "Lägg till kanin"

// FEL
<Button>Add Rabbit</Button>
```

### 2. **Tydlig och Informativ UI**

**REGEL:** Status, badges och ikoner ska vara begripliga utan förkunskap:
kort text, och en förklaring (tooltip eller hjälptext) där betydelsen inte
är självklar. Exempel: "Registrerade och årsrapporterade inom 13 månader".
Individkortet (`components/herd/IndividualCard.tsx`) är referens.

### 3. **Smart Default-värden**

**REGEL:** Default-värden ska vara de mest praktiska för daglig användning.
Min besättning visar aktiva kaniner som förval; filtret är ett enda val
(`"active" | "all" | "cert"`). Alla kaniner sorterar på servern, förval
`name`.

### 4. **Responsiv Design - Mobile First**

**REGEL:** Alla komponenter ska fungera på mobil, tablet och desktop.
Uppfödarytor är mobile-first, admin-ytor desktop-first. Verifiera vid
375 / ≥640 / ≥900 px; ingen horisontell scroll vid 375 px
([ADR-0010](adr/0010-mobile-first-responsive-strategy.md)).

Kort och layout byggs med sb-primitiver och CSS-moduler, MUI bara för
komplexa widgets (ADR-0009):

```tsx
// RÄTT - responsiv kortgrid via CSS-modul (se min-besattning.module.css)
<div className={styles["mb-grid-cards"]}>
  <article className="sb-card">...</article>
</div>

// FEL - fast bredd som inte fungerar på mobil
<Box width={800}>
```

### 5. **Datavalidering Mot Verklighet**

**REGEL:** Testa mot API-data med realistisk form, inte bara teoretiska
scenarier. Skapa testanvändare och anropa API:t:

```bash
docker compose exec api python3 -m cli.create_test_users
curl -u test-admin:test-admin-pass http://localhost:9090/api/herd/G1274 \
  | jq '.individuals[0:5]'
```

Mönster att räkna med (påhittade exempel, jfr
[ADR-0011](adr/0011-status-detection.md)):

- `death_note` med år först: "2018 bet ofta", "2019 dog plötsligt"
- `death_note` om slakt utan `death_date`: "Slaktad, platsbrist"
- `alive=false` men inget `death_date`: `alive` är
  `not death_date and not death_note`, så en anteckning räcker

Lägg aldrig produktionsdata (riktiga anteckningar, gårdsnamn, namn på
personer) i repot ([ADR-0013](adr/0013-public-code-private-operations.md)).

### 6. **Progressiv Förbättring**

**REGEL:** Bygg steg för steg med tydliga commits, t.ex. först flik-struktur,
sedan kortvy, filtrering och statusdetektering var för sig, inte "komplett
sida" i en commit.

---

## Svensk Terminologi

| **Svenska**         | **Kod/API**                                  | **Kommentar**                                                                                  |
| ------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Individnummer**   | `number`                                     | Format `G1274-2312`, se nedan. Ordlista: `docs/ORDLISTA.md`                                    |
| **Besättning**      | `herd`                                       | Besättningskod, t.ex. G1274 (`^[GM](\d+)$`)                                                    |
| **Kanin / Individ** | `individual`                                 | Ett djur i systemet                                                                            |
| **Parning / Kull**  | `breeding`                                   | Samma rad: `breed_date`, `birth_date`, `litter_size`, `litter_number`. Det finns ingen `litter`-modell |
| **Oregistrerad unge** | `Bunny`                                    | Unge som inte ännu fått eget individnummer                                                     |
| **Födelsedatum**    | `birth_date`                                 | Lagras på `Breeding`, kopieras in i individens svar                                            |
| **Dödsdatum**       | `death_date`                                 |                                                                                                |
| **Dödsorsak**       | `death_note`                                 | Fritext                                                                                        |
| **Årsrapport**      | `YearlyHerdReport`, `herd_tracking` ATTESTATION | Årlig rapportering av besättning                                                            |
| **Aktiv kanin**     | `is_active`                                  | Se "Status och aktiv kanin"                                                                    |
| **Avelsdjur**       | aktiv + ej kastrerad + hona/hane             | Se `OversiktTab.tsx`                                                                           |
| **Intyg**           | `certificate` / `digital_certificate`        | Pappersintyg (text) respektive digitalt intyg (heltal)                                         |
| **Gotlandskanin**   | genbank 1                                    | Prefix G                                                                                       |
| **Mellerudskanin**  | genbank 2                                    | Prefix M                                                                                       |
| **GX1 / MX1**       | besättningskoder                             | Såld utanför genbanken                                                                         |

Rasnamn skrivs med gemener i löptext: gotlandskanin, mellerudskanin.

Kommentarer i kod skrivs på engelska; svenska domäntermer är OK.

### Individnummer

Format: `{besättning}-{ÅÅ}{kullnummer}{plats 1-9}`. Exempel `G1274-2312`:
besättning G1274, år 23, kull 1 (första kullen, räknas från 1), plats 2 i
kullen. Generatorn finns i `app/utils/individual_number_v2.py`. Sortera inte
på klienten: besättningsvyn sorterar på `number` i `data_access.py` och Alla
kaniner sorterar på servern.

---

## Status och aktiv kanin

Källor: [ADR-0011](adr/0011-status-detection.md) och `Individual.active` i
`app/utils/database.py`.

En kanin är **aktiv** (`is_active`, beräknas på servern) när allt stämmer:

- registrerad (har `certificate` eller `digital_certificate`)
- ingen `death_date` eller `death_note`, inte kastrerad
- besättningen är aktiv och inte GX1/MX1
- senaste livstecknet (BIRTH, TRANSFER eller ATTESTATION i `herd_tracking`)
  är högst 395 dagar gammalt

Aktiv betyder alltså mer än "årsrapporterad inom 13 månader"; inaktiv
omfattar även döda, kastrerade och oregistrerade kaniner.

**Statusetikett** i `getStatusInfo` (individsidan), prioritetsordning:
`death_date` -> Försvunnen -> Slaktad -> Avlivad -> Död ca ÅÅÅÅ (från
`death_note`) -> Inaktiv -> Aktiv. Med `death_date` blir etiketten Slaktad
eller Avlivad om anteckningen har nyckelord, annars Död. Servern har en
motsvarighet (`_derive_individual_status`, Alla kaniner) och Min besättning
en förenklad (`rabbitStatus`); ändra alla tre tillsammans.

**`death_note`-tolkning** (`IndividualCard.tsx`, `app/utils/genetics.py`):

- år först: `/^(19\d{2}|20\d{2})[\s,]/`; ålder räknas till 1 juli det året,
  med reserv senaste `herd_tracking` + 1 år
- slakt: "slakt" eller "kött" i anteckningen, eller `butchered === true`

### Sålda och köpta kaniner

`selling_date` är **inte** en kolumn och inte ett fält i API-svaret, bara
ett fält i överlåtelseformuläret som daterar `herd_tracking`-raden. Sålda
kaniner syns därför inte i besättningsvyn (den visar bara nuvarande
innehav), men i Alla kaniner med `include_historical` och i
besättningshistoriken.

**Köpt** = `origin_herd` skiljer sig från nuvarande `herd`. **Köpdatum** =
datumet på senaste `herd_tracking`-rad med `kind == "TRANSFER"` in i
nuvarande besättning (`GET /api/v2/individual/<number>/herd-tracking`; API:t
exponerar `kind`). Använd inte `herd_tracking[0]`: listan innehåller även
ATTESTATION-rader, så efter en årsrapport är det rapportdatumet.

---

## Arbetsflöde

- Branch från `main`, PR mot `main` (se CLAUDE.md).
- Kontroller: `pnpm lint`, `pnpm type-check`, `pnpm test` i `next-app/`,
  ruff via pre-commit, allt samlat i `scripts/ci-local.sh`. Kringgå aldrig
  pre-commit-hooks.
- Starta stacken med `docker compose up -d`, eller `pnpm dev` mot API:t på
  :9090 (se `next-app/README.md`). Kör aldrig pytest i dev-containern.
- Gammalt Grid-API (`item`-prop) används inte: MUI `Grid` med `size`-prop,
  och i första hand sb-primitiver och CSS-moduler.
- Fånga `herd?.individuals || []` istället för att anta att listan finns.

### Commit-konventioner

Format `<type>(<scope>): <subject>`, scope är valfritt men uppmuntras.
Typer: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `build`,
`ci`, `style`. Subject i imperativ, högst ca 72 tecken, utan punkt; body
bara när varför inte syns i diffen. Små commits, en logisk ändring var.

Exempel: `fix(mui): preserve 16px paragraph margins`

---

## Testning och kantfall

Se [TESTING.md](../TESTING.md) för pytest-stack, vitest och Playwright.
Verifiera UI vid 375 / ≥640 / ≥900 px (ADR-0010) och kontrollera kantfallen:

- kanin utan foto: placeholder (`public/static/img/placeholder-rabbit.png`)
- kanin utan namn: "Namnlös" (individkortet), `Kanin <nummer>` (Min besättning)
- `death_note` utan `death_date`: år utläses, "Kött" ger Slaktad
- långt namn: text kortas med ellipsis (`noWrap`)
- tom besättning: empty state
- tom sökning: visar allt inom aktivt filter

Tillgänglighet: flikar har `herd-tab-<key>` och `herd-tabpanel-<key>` som
id/`aria-controls` (`components/shell/TabBar.tsx`), och bilder har alt-text
(namn, annars nummer, annars "Kanin").

## Vanliga fallgropar

- Hårdkodad engelsk eller svensk text: använd `t()`-nycklar.
- Anta inte datastruktur: läs fältet i `Individual.as_dict()` eller
  `apiSlice.ts` (typerna) innan du använder det.
- Skapa aldrig testdata med riktiga besättningsnamn eller anteckningar.
- Legacy-frontenden förväntar sig `null` när ingen är inloggad; API:t svarar
  401. Session-cookien är `SameSite=Lax` och det finns ingen CORS i
  produktion: varje frontend når API:t via sin egen hosts `/api/`.
- Släktskaps- och inavelsberäkningar (NumPy) kan ta sekunder för stora genbanker.
