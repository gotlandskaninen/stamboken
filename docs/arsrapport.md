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
| `GET /api/v2/arsrapport/besattning/<besättning>/<år>/forslag` | admin och genbanksansvarig i besättningens genbank. Hjälpare får 403. |
| `POST /api/v2/arsrapport/forslag/<id>/godkann` och `…/avvisa` | admin och genbanksansvarig i besättningens genbank. Hjälpare, ägare och genbanksansvarig i den andra genbanken får 403. |
| `POST /api/v2/arsrapport/besattning/<besättning>/<år>/kop` och `…/kop/inskick` | den som får rapportera för besättningen, inloggad eller via länken (`report_actor_required`). Länken når bara sin egen besättning och sitt år. |
| `GET /api/v2/arsrapport/blankett.pdf` | alla som är inloggade |

## Statusvyn

`GET /api/v2/arsrapport/<år>/status?genebank_id=<id>` svarar med

```text
{round, genebank_id, activated, counts: {läge: antal},
 rows: [{herd, herd_name, state, source, membership_after_end, received_at, on_time_override,
         inbox_item_id, telefon (bara för genbanksansvariga och administratör),
         flags: {ej_angivna, ej_angivna_paverkar, forsaljning_vantar, forsaljning_avvisad,
                 forsaljning_avvisad_paverkar, kopt_efter_inskick, kop_anmalt},
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
  - `forsaljning_vantar` är antalet försäljningsförslag som väntar på beslut.
  - `forsaljning_avvisad` är antalet kaniner som en avvisad försäljning lämnade åt medlemmen att välja
    igen. `forsaljning_avvisad_paverkar` prövas som `ej_angivna_paverkar`, och "Att ringa" tar med
    besättningen när någon av de två är sann.
  - `kopt_efter_inskick` är antalet godkända köp daterade senast 31 december till besättningen, där
    kaninen saknas i rapportens senaste inskick. Bara köparens eget val för kaninen tar bort
    flaggan; ett avvisningsinskick kopierar det senaste inskicket och lägger inte till kaninen.
  - `kop_anmalt` är antalet öppna köpanmälningar daterade under året som inget väntande
    försäljningsförslag matchar och vars köp inte är registrerat (se nedan).
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

## Försäljning direkt

`POST …/besattning/<besättning>/<år>/forsaljning` med `{"individual_id": …, "sald": {till, ar, manad, dag,
kopare}}` registrerar en kanins försäljning direkt, som Sälj på kaninens sida (Jonas 2026-11-26). Servern
kontrollerar den med samma regler som Skicka: kontrollen körs på ett inskick med bara den kaninen. På
pappersvägen låses posten och kontrolleras igen. Svaret är `{"operation_id": …}`, eller 422 med `refusals`.
Endast före första Skicka och för en roll som får sälja. Med en inskickad rapport blir svaret 409, och
försäljningen går med Skicka. Försäljningen hör till registret: en försäljning till och med 31 december tar
kaninen från listan och visas i `sales`, en senare försäljning ger raden läget `via_flytt`. `sales[].undo`
och `rabbits[].undo` är försäljningens rad när säljaren får ångra den som på kaninens sida (7 dagar).
`POST …/forsaljning/<rad>/angra` med `{"operation_id": …}` ångrar den och kontrollerar säljarens regel igen
nu, aldrig en rad som en rapport skrev. Efter sista dagen går försäljningen med Skicka, som kräver en orsak.
En försäljning utan dag visas med månad. Skicka sparar årets försäljningar som ingen rapport skrev i
inskicket (`salda_direkt`), så kvittot räknar dem bland de sålda, och en defekt på en såld kanin följer med.

## Försäljningsförslag

`GET …/besattning/<besättning>/<år>/forslag` svarar `{"forslag": [{id, individual_id, number, name,
to_herd, buyer, buyer_not_recorded, sale_date, buyer_notified_at, kopanmalan}]}` med de förslag som väntar.
En köpare utanför genbanken visas bara med namn och ort (`buyer`), och `to_herd` är då `null`. En
försäljning "såld utanför genbanken" utan köpare (#273) har `buyer` `null` och `buyer_not_recorded`
`true`. `kopanmalan` är
köparens köpanmälan som förslaget matchar, eller `null`.

`POST /api/v2/arsrapport/forslag/<id>/godkann` registrerar försäljningen, också efter rundans
`end_date`. Är köpet daterat senast 31 december och köparens besättning har skickat in sin rapport,
får köparens huvudmedlem mejlet `arsrapport.kop_godkant`. Godkännandet tar både säljarens och
köparens rapportlås, i besättningarnas id-ordning, så köparens Skicka kommer helt före eller helt
efter det.

`POST /api/v2/arsrapport/forslag/<id>/avvisa` med `{"reason": …, "then": "kvar" | "valj_igen"}`
avvisar förslaget. Orsaken krävs och får inte innehålla köparens namn, telefonnummer eller
e-postadresser. `kvar` skriver kaninen som Finns kvar med Ej vägd ("Försäljningen avvisades"), så
att raden är klar och medlemmen ändå kan väga den, och `valj_igen` lämnar den åt medlemmen att
välja igen. Båda skrivs som ett inskick av genbanksansvarig på samma rapport och flyttar
revisionen, så att en sida som öppnades före beslutet får 409. Inskicken ordnas i den ordning de
skrevs under rapportens lås, inte efter `created_at`. Vägrar registret `kvar` blir svaret
409 med registrets orsak, och förslaget står kvar. Medlemmen får orsaken i mejlet
`arsrapport.forsaljning_avvisad`. Ett förslag som redan är avgjort ger 409.

## Köpanmälan

`POST …/besattning/<besättning>/<år>/kop` med `{"number", "from_herd", "date"}` anmäler att
besättningen köpt kaninen `number` från besättningen `from_herd` (`"utanfor"` blir genbankens GX1
eller MX1) på dagen `date` under året. Anmälan blir en post i kön, `kind` `kontroll` med `ref_type`
`kopanmalan` och fälten i `ref_data`: `{number, from_herd, date, individual_id}`, utan personuppgifter.
Postens `member` är den som anmälde: länkens medlem, eller kontots person i matrikeln, så att en
radering hittar anmälan. Länken står i historiken med `via` och `access_code_id`. Svaret är `{id,
number, from_herd, date, state}`.

Kroppen kan också ha `document_id` och `doc_type` (`"bevis"` eller `"intyg"`): ett foto av
försäljningsbeviset eller intyget som sessionen laddat upp med `…/foto?syfte=kop`. Fotot flyttar till
anmälans post med den typen, och fotots egen post tas bort. Bildmodellen läser det aldrig: inte
efter uppladdningen, och en tidigare läsning tas bort vid flytten. Kön visar det bara, utan typ,
format och Tolka igen, och servern låter inte kön skicka det till läsning: köpet registreras på
kaninens sida. Ett foto uppladdat med `syfte=kop` som i stället blir en kanins läses som andra. Samma regler gäller som när en kanin registreras
från ett foto: bara sessionens egna uppladdningar (403), och bara ett foto som inte är kopplat och som
kön fortfarande kan kontrollera (409), båda med `field` `photo`. Kön får notisen `ny_post` en gång,
när anmälan får sitt första foto; en anmälan utan foto ger ingen notis. Samma begäran igen svarar
med anmälan.

- Kaninen och säljaren söks bara i besättningens genbank (kaninens ursprungsbesättning), så en
  annan genbanks nummer eller besättning får samma svar som ett som inte finns.
- Ett nummer som Stamboken saknar ger 422 med `code` `inte_i_stamboken`: köparen skickar foton av
  intyget och försäljningsbeviset till kön (se nedan), och genbanksansvarig registrerar kaninen i
  säljarens besättning och för över den. Köparen får inte registrera i en annan besättning. En kanin som redan står i besättningen ger 409. En öppen anmälan av samma
  kanin under året är svaret igen, och en öppen anmälan från ett annat år ger 409.
- Anmälan skrivs som rapporten, under rapportens lås: medan rundan är öppen, och efter `end_date`
  bara av genbanksansvarig och admin. Annars 409 med `code` `rundan_stangd`.
- En anmälan **matchar** ett väntande försäljningsförslag för samma kanin från `from_herd` till
  besättningen när datumen skiljer högst 14 dagar. Godkänns förslaget stängs anmälan i samma
  transaktion; dess post låses i samma stigande pass som förslagets. Förslaget och anmälan kan höra
  till olika års rapporter, så både anmälan och godkännandet tar köpets eget lås (köparens
  besättning och kaninen) efter rapportlåsen och före posterna.
- En anmälan **stänger sig själv** ("Köpet är registrerat") när en aktiv `TRANSFER` av kaninen till
  besättningen finns, registrerad efter anmälan eller daterad högst 14 dagar före anmälans datum,
  och ingen senare aktiv rad flyttar kaninen till en annan besättning senast anmälans datum. En
  vistelse som slutade före köpet är inte köpet, också när den registrerades efter anmälan.
  Kontrollen görs utan trigger i rapportvyn, för årets anmälningar under rapportens lås, och när
  posten öppnas i kön. Posten låses före kaninen, och flytten läses igen under båda låsen.
- Rapportvyns `rabbits` har `kopt: {datum, fran} | null` från den senaste aktiva `TRANSFER` till
  besättningen daterad under året, och `kopanmalningar: [{id, number, from_herd, date, state}]` med
  besättningens anmälningar daterade under året.

### Köpt kanin som Stamboken saknar (S7)

`POST …/besattning/<besättning>/<år>/kop/inskick` med `{"number", "from_herd", "date", "documents":
[{"id", "doc_type"}]}` skickar ett eller två foton som sessionen laddat upp med
`…/foto?syfte=inskick` (samma filkontroller, samma gräns på 60 i timmen och samma bindning till
sessionen som andra foton genom rapporten). `doc_type` är `"intyg"` eller `"bevis"`. Fotona blir en
vanlig post i kön, `kind` `upload` utan `ref_type`, för besättningen och med kontot som avsändare
(länken står i historiken, `via` och `access_code_id`, och länkens medlem är postens `member`, dit
köns mejl om posten går och som en radering hittar), som om köparen mejlat dem. Köpets fält står
i `ref_data`: `{number, from_herd, date, receipt}`. Intyget läses av bildmodellen som andra intyg,
och köns arbetare får notisen `ny_post` en gång. Genbanksansvarig eller en hjälpare registrerar
kaninen i ursprungsbesättningen och för över den till köparen genom kön. Svaret är `{id, number,
from_herd, date, state}`. Samma begäran igen svarar med posten bara när den kommer från samma
konto eller länk, i den session som laddade upp fotona, för samma besättning och år och med samma
innehåll: kvittot `receipt` är fotonas egna poster och en hash av begäran. Alla andra begäranden
kontrolleras som nya.

- Ett nummer som finns i genbanken ger 409 (det är en anmälan), saknat foto 400 med `field`
  `photo`, och sessionens regler för foton gäller som för anmälan (403, 409).
- Rundan och länken kontrolleras under rapportens lås som för anmälan.
- Posten stängs av kön, som andra inskick, aldrig av rapportvyn. När numret finns i genbanken och en
  `TRANSFER` av kaninen till besättningen är registrerad (samma regler som för en anmälan) visar
  rapportvyn den som `registrerad` tills kön stänger den. Statusvyns `kop_anmalt` räknar öppna
  inskick som inte är registrerade.
- Ett foto uppladdat med `syfte=kop` eller `syfte=inskick` bär syftet i postens `ref_data`
  (`{"syfte": …}`) tills det skickas, blir en anmälans eller binds till en kanin. Under tiden läses det
  aldrig: varken en ny typ, Tolka igen eller ett läge satt till `vantar` får bildmodellen att läsa det.
  Ett sådant foto som efter ett dygn varken har skickats, blivit en anmälans eller bundits raderas med
  sin fil av nattjobbet (`purge_held`).
- Ett foto till "Lägg till kanin från intyget" (`…/foto` utan `syfte`) hålls på samma sätt med
  `{"syfte": "kanin"}` tills Spara registrerar kaninen. Först då blir det en vanlig `kontroll`-post
  i kön, en per kanin, som läses och som köns arbetare får notis om. Ett hållet foto listas inte i
  kön, kan inte skickas som ett köps foto, och raderas efter ett dygn om ingen kanin har sparats från
  det (Släng eller en stängd flik). Spara på ett raderat foto ger 409 med `field` `photo`. Dialogen tar med ett foto som laddats upp till anmälan när
  numret visar sig saknas, så att det skickas med de andra.

## Ärenden hos genbanksansvarig (S8)

Rapportvyns `arenden: [{id, what, number, photos, state}]` listar köns poster som gäller rapporten,
öppna först, och en stängd post i 14 dagar efter att den stängdes. Med finns det som kom genom
rapporten: foton som skickats (S7) och rapportens `kontroll`-poster (försäljningsförslag,
köpanmälningar och foton av kaniner som lagts till från rapporten). Dessutom vanliga inskick som
rapportens mottagare har skickat, huvudmedlemmen som länken går till: den person som sparades som
avsändare när inskicket kom in (`member`), eller för ett äldre inskick utan den, mottagarens konto.
En rätt till besättningen räcker aldrig, så en skötarrätt som ges senare visar inget och en som
återkallas döljer inget, och en ny huvudmedlem ser inte den förras inskick. Mejl, andras inskick,
meddelanden och köparuppgifter är inte med. Köp och försäljningar från ett annat år är inte med.

- `what`: `inskick`, `kop_saknas` (S7), `kopanmalan`, `foto` eller `forsaljning`.
- `state`: `tolkas` (ny, med ett intyg som väntar på bildmodellen), `vantar` (ny), `arbetar`
  (någon har posten, eller avsändaren har fått en fråga), `registrerad` (skickade foton vars
  `TRANSFER` är registrerad, medan posten är öppen) eller `klart` (stängd, också som dubblett eller
  skräp).

## Den tomma blanketten

`GET /api/v2/arsrapport/blankett.pdf` skickar filen
`<PRIVATE_UPLOAD_FOLDER>/arsrapport/arsblankett.pdf` (som standard `/app/skyddat/arsrapport/`).
Drift bygger PDF:en med `blanketter/arsrapport/make.py` i drift-repot och kopierar den dit. Finns
filen inte blir svaret 404 med texten "Blanketten finns inte på servern än."
