---
status: "proposed"
date: 2026-11-14
decision-makers: Jonas
---

# ADR-0015: Kommandon per avsikt för skrivningar på individ

## Kontext och problem

Alla skrivningar på en befintlig individ går genom `update_individual(form)`
och `form_to_individual(form)` i `data_access.py`: legacy `PATCH /api/individual`,
v2 `PATCH /api/individual/<nr>` och de fyra intygsrutterna. Funktionerna får
hela formuläret och avgör själva vad som har ändrats, vem som får ändra det
och i vilken ordning. Samma fält kan betyda olika saker: `herd` +
`yearly_report_date` är en årsrapport om kaninen redan är där, men en flytt
om den inte är det. Säkerhetsgranskningen hittade sju fynd i den här
kodvägen och två till i nummerbytena, och rättelserna lägger nya kontroller i
samma funktion. [ADR-0014](0014-authorization-model.md) räcker inte för
individer. Legacy-frontenden skickar ofta hela objektet, och svaren får inte
ändras ([ADR-0006](0006-api-compatibility-during-migration.md)).

## Alternativ

* Fortsätta lappa `update_individual`: avvisat, eftersom varje fix gör
  funktionen större och en ny ingång måste upprepa kontrollerna.
* Fält-allowlist och behörighet per route: avvisat, eftersom behörigheten då
  följer routen, inte avsikten, och routen inte kan se lagrat tillstånd före
  låset.
* Kommandon bara i nya v2-endpoints, legacy oförändrat: avvisat, eftersom det
  ger två skrivvägar med olika regler där en kontroll går att kringgå genom
  den andra.
* Kommandon, policytabell och legacy-adapter (valt)

## Beslut

Valt alternativ: "Kommandon, policytabell och legacy-adapter", eftersom det
ger en skrivväg där behörigheten går att läsa i en tabell och lås och
omläsning finns på ett ställe. `update_individual` och uppdateringsgrenen i
`form_to_individual` ersätts med ett kommando per avsikt, som körs av en
central skrivare med behörigheten i en deklarativ policytabell. Legacy-API:t
behålls genom en adapter, och svaren ändras inte.

Regler:

1. **Ett kommando per avsikt.** Frysta dataclasses i
   `app/utils/individual_commands.py`, till exempel `EditDescription`,
   `RecordDeath`, `TransferIndividual`, `RenameIndividual` och `MoveToLitter`.
   Inget kommando har ett fält som styr behörighet. `IssueDigitalCertificate`
   skapas bara av intygsrutterna, aldrig ur en request-body.
2. **Policyn är en tabell, deny-by-default.** `app/utils/individual_policy.py`
   är en ren modul utan databasimport. Den listar de kombinationer av kommando,
   roll och tillstånd (certifierad, utanför genbanken) som är tillåtna. Allt
   annat nekas. Rollerna är relationer mellan användaren och individen, och de
   härleds ur rollerna och metoderna i ADR-0014: admin, ansvarig för den
   nuvarande besättningens genbank, ansvarig för ursprungsbesättningens genbank
   (`manager` i den genbanken), ägare (`transfer_herd_ids()`) och skötare
   (besättningen finns i `effective_herd_ids()` men inte i
   `transfer_herd_ids()`, till exempel genom en åtkomstgrant). Inga nya roller
   lagras. `viewer` och `matrikel_admin` finns inte i tabellen och får därför
   ingen skrivrätt. Valideringar som inte gäller vem som frågar ligger i
   kommandot, inte i tabellen: datum, anledning vid genbanksbyte, unikt
   nummer, cykel i stamtavlan, intygskvot. Att ett mål i en annan genbank bara
   får väljas av admin är en rad i tabellen. v2:s försäljningsregler
   (`_check_transfer`) stannar i blueprinten, som i dag.
3. **Behörighet och validering under låset, på omläst rad.** Det här är
   ADR-0014:s scope-kontroll för individer. Endpointen gör inloggning och grov
   rollkontroll, och skrivaren gör resten. Den tar låsen i den globala
   ordningen (kull → individ, för intygsrutterna även kullens föräldrar, sist
   nummerlåset vid nummerbyte). Den läser om raden, räknar fram roll och
   tillstånd ur den, frågar policyn, validerar och skriver i en transaktion.
   Fel är typade undantag med HTTP-status, som `HerdTrackingError` i
   `herd_tracking.py`, vars centrala skrivare är förebilden.
4. **Legacy-adaptern (Strangler Fig).** `update_individual(form, user_uuid,
   issue_digital=False, genebank_change_reason=None)` behåller svaren. Den får
   ett nyckelordsargument till, `clear_nulls`, för v2:s nollning. Under låset
   jämför den formuläret med det lagrade värdet. Bara skillnaderna blir
   kommandon, så ett eko är ingen ändring. Formuläret innehåller fält som styr
   ägarskap, som `herd`. Att adaptern tar emot dem är det undantag från
   ADR-0014 (punkt 4 under "Var kontrollen görs") som ADR-0006 tvingar fram: en
   ändrad `herd` blir `TransferIndividual`, som prövas mot flyttpolicyn, aldrig
   en fältskrivning. Legacy kan inte skicka någon anledning, så en admins flytt
   till en annan genbank får en fast anteckning. Kontrollerna körs i dagens
   ordning, och felen blir dagens kuvert. ADR-0006 gäller oförändrat. En
   avvikelse från dagens svar är bara tillåten som avsiktlig säkerhetsvägran,
   med hänvisning till fyndet i granskningen.
5. **En domän i taget:** individ, sedan kull (`update_breeding`), besättning
   (`update_herd`) och sist konto/roller (`update_user`, `update_role`). Varje
   domän får samma mönster och en egen plan.

### Konsekvenser

* Bra, eftersom behörigheten för en individ står i en tabell. Matrisen roll ×
  fält × tillstånd genereras ur den och testas.
* Bra, eftersom varje kommando har egna tester, och nya ingångar (v2, intyg)
  anropar kommandona och får samma regler. Låsordning och omläsning görs på
  ett ställe.
* Dåligt, eftersom det blir fler moduler (kommandon, policy, adapter) i
  stället för en funktion.
* Dåligt, eftersom adaptern måste behålla dagens egenheter, till exempel 500
  när `herd` saknas, tills legacy avvecklas. Under övergången finns gamla
  mönster kvar i kull, besättning och konto.
* Dåligt, eftersom en tabell som tillåter för mycket eller för lite är en risk.
  Kontroller som i dag görs före låset flyttas in under låset; det ändrar bara
  utfallet vid samtidiga anrop, och då till det korrekta.

### Bekräftelse

* `test_legacy_api_contracts.py` är oförändrad och grön, och skrivscenarier
  spelas om före och efter med identiska svar och identiskt DB-tillstånd.
* Matrisen genereras ur policytabellen och jämförs med en incheckad
  förväntan. Mutationstest på policymodulen.

## Tillägg 2026-11-14: policyrollen HANDLAGGARE och grants (föreslaget)

Föreslaget tillägg, att godkännas av beslutsfattaren. Regel 2 säger att inga
nya roller lagras. Inläsningskön behöver en relation mellan användaren och
kaninen som inte är en lagrad roll:

1. **Grant.** `execute(…, grant=…)` tar emot ett objekt (`Grant` i
   `app/utils/individual_commands.py`) som ger roller på en kanin utifrån något
   användaren håller, inte utifrån hennes egna roller. Skrivaren frågar det
   under kaninens lås, i skrivtransaktionen. Det granten själv beror på (dess
   egen rad) låser anroparen före `execute`. Grantens roller läggs till
   rollerna från `roles_for`, och policytabellen ensam avgör. Granten skriver
   sitt spår när kommandona är loggade.
2. **`HANDLAGGARE`** är en roll i policytabellen men lagras aldrig. Bara
   `InboxGrant` (`app/utils/inbox.py`) ger den: till en genbankshjälpare som är
   handläggare för en post i läget `tagen` utan `ref_type`, för en kanin vars
   besättning ligger i en genbank där hon är hjälpare och inte är GX1 eller MX1.
   Tabellen ger `HANDLAGGARE` samma rader som ägaren, alltså inga
   korrigeringar (ADR-0017 nivå 2).
3. Den lagrade rollen `helper` (ADR-0014, tillägg 2026-11-14) har ingen rad i
   tabellen: utan grant har en hjälpare ingen skrivrätt på en kanin.
4. Varje skrivning genom kön ger en rad i `inbox_operation` (operationen,
   handläggaren, dokumentet). Genbanksansvarig och admin skriver med sina egna
   roller också genom kön; för dem lämnar granten bara spåret.

## Mer information

* [ADR-0006: API-kompatibilitet under migreringsperioden](0006-api-compatibility-during-migration.md)
* [ADR-0007: Flask-API:et delas upp i blueprints per domän](0007-blueprint-refactor.md)
* [ADR-0014: Behörighetsmodell för Stambokens API](0014-authorization-model.md)
* `app/utils/herd_tracking.py`: central skrivare för herd-tracking

Underlaget (avsiktstabell och dagens implicita regler) och
implementationsplanen ligger i driftrepot.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-10-27 | Jonas | Utkast |
| 2026-11-06 | Jonas | MADR-format, kortad |
| 2026-11-14 | Jonas | Föreslaget tillägg: policyrollen `HANDLAGGARE`, som bara en grant ger |
