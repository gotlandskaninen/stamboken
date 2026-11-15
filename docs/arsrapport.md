# Årsrapporten: API för statusvyn, "i tid" och den tomma blanketten

Det här dokumentet beskriver de tre delar av årsrapport-API:t som genbanksansvariga och
genbankshjälpare arbetar med: statusvyn per genbank och runda, "i tid" och den tomma blanketten
som PDF. Reglerna finns i `app/utils/arsrapport.py` och endpointsen i
`app/blueprints/arsrapport.py`. Fel kommer som `application/problem+json`, som i
[inkorg.md](inkorg.md).

## Vem får vad

| Endpoint | Vem |
|---|---|
| `GET /api/v2/arsrapport/<år>/status?genebank_id=<id>` | admin, och genbanksansvarig eller genbankshjälpare i den genbanken (`inbox.can_handle`) |
| `POST /api/v2/arsrapport/besattning/<besättning>/<år>/i-tid` | admin och genbanksansvarig i besättningens genbank. Hjälpare får 403. |
| `GET /api/v2/arsrapport/blankett.pdf` | alla som är inloggade |

## Statusvyn

`GET /api/v2/arsrapport/<år>/status?genebank_id=<id>` svarar med

```
{round, genebank_id, activated, counts: {läge: antal},
 rows: [{herd, herd_name, state, source, membership_after_end, received_at, on_time_override,
         inbox_item_id, flags: {ej_angivna, ej_angivna_paverkar},
         villkor: {hane, hona, kull, i_tid},
         statistik: {kullar, ungar, levande_6v, honor, hanar}}]}
```

- **Rader:** genbankens aktiva besättningar utom GX1 och MX1, och varje besättning med en inskickad
  rapport i rundan. Antalet frågor växer inte med antalet besättningar.
- **Läge (`state`):** det första som gäller av `avslutar` (inskickad med `ending_genbank`),
  `inskickad`, `blankett_vantar` (en öppen post med en arsblankett i läget `vantar_uppfodare`),
  `blankett_inkommen` (en sådan post i något annat öppet läge), `paborjad` (ett utkast finns),
  `ingen_epost` (huvudmedlemmen saknar e-post), `ej_rapporterad`. `counts` har alla lägena.
- **Stödvillkoren (`villkor`)** prövas per besättning mot kaninerna den höll 31 december
  (`innehav` i `arsrapport_statistik.py`):
  - `hane` och `hona`: minst en okastrerad kanin av könet. Kastrerade kaniner räknas inte, och inte
    heller en kanin med ett väntande försäljningsförslag daterat senast 31 december.
  - `kull`: minst en kull med minst en född unge.
  - `i_tid`: `on_time_override` om den är satt, annars att Stockholmsdatumet för `received_at` är
    senast rundans `deadline`.
- **Flaggor:** `ej_angivna` är antalet kaniner blanketten lämnade utan svar. `ej_angivna_paverkar`
  är sann när de fyra villkoren uppfylls först om de kaninerna räknas med.
- **Konto:** statusvyn har inga kontouppgifter. En blankettpost visar bara kontots två sista siffror
  (`item.account_end`) i rapportvyn.

`ReportView.report.villkor` har samma fyra villkor för en besättning (`herd_conditions`). Kvittot
har inga.

## "I tid"

`POST …/besattning/<besättning>/<år>/i-tid` med `{"on_time": true | false | null}` sätter eller
tar bort genbanksansvarigs val och svarar `{"on_time_override": …}`. `null` återgår till datumet.
Fältet `on_time` måste finnas. Valet skrivs under samma lås som Skicka och lämnar `received_at`
orört, så det gäller också efter en senare ändring. Den som satte det sparas i `on_time_set_by`.
Utan en inskickad rapport blir svaret 404.

## Den tomma blanketten

`GET /api/v2/arsrapport/blankett.pdf` skickar filen
`<PRIVATE_UPLOAD_FOLDER>/arsrapport/arsblankett.pdf` (som standard `/app/skyddat/arsrapport/`).
Drift bygger PDF:en med `blanketter/arsrapport/make.py` i drift-repot och kopierar den dit. Finns
filen inte blir svaret 404 med texten "Blanketten finns inte på servern än."
