# Inläsningskön (inkorgen): API

Inläsningskön är en gemensam inkorg i Stamboken. En medlem fotograferar sina pappersintyg och
laddar upp fotona eller mejlar dem till föreningen, och den som arbetar i kön tar posten, lägger in kaninerna och lägger en
maskerad kopia av intyget på kaninen. Det här dokumentet beskriver Flask-API:t som gränssnittet
bygger på: varje endpoint, vem som får anropa den, vad den tar emot och svarar, och lägena en
post går igenom. Reglerna finns i `app/utils/inbox.py` och endpointsen i `app/blueprints/inbox.py`;
mejlen in och frågan till uppfödaren i `app/utils/inbox_gmail.py` och `app/blueprints/inbox_gmail.py`.
Driften av mejlläsningen står i [inkorg-gmail.md](inkorg-gmail.md).

## Innehåll

1. [Begrepp](#begrepp)
2. [Roller](#roller)
3. [Lägen](#lägen)
4. [Arbetsgången](#arbetsgången)
5. [Fel](#fel)
6. [Objekt i svaren](#objekt-i-svaren)
7. [Ladda upp](#ladda-upp)
8. [Kön](#kön)
9. [Ta, ta över och tilldela](#ta-ta-över-och-tilldela)
10. [Byta läge](#byta-läge)
11. [Dokument](#dokument)
12. [Spara det intyget visar](#spara-det-intyget-visar)
13. [Registrera en försäljning](#registrera-en-försäljning)
14. [Maskning och kopian på kaninen](#maskning-och-kopian-på-kaninen)
15. [Bilderna](#bilderna)
16. [Fråga uppfödaren](#fråga-uppfödaren)
17. [Mejlade poster](#mejlade-poster)
18. [Mina inskick](#mina-inskick)
19. [Notiser](#notiser)
20. [Mejl](#mejl)
21. [Tolkning](#tolkning)
22. [Gallring](#gallring)
23. [Gränser och sådant gränssnittet behöver veta](#gränser-och-sådant-gränssnittet-behöver-veta)

## Begrepp

- **Post** (`item`): det som kom in i ett svep, en uppladdning eller ett mejl. Postens id visas som
  "ärende 1234" i kön, under Mina inskick och i ämnesraden på mejlen.
- **Dokument** (`document`): en bild i posten. Ett foto blir ett dokument, och en PDF blir ett
  dokument per sida.
- **Handläggare**: den som har posten (`assigned_to`). Bara handläggaren ändrar posten och sparar
  genom den. Alla andra i kön kan läsa allt men måste ta över posten för att ändra något.
- **Originalet**: bilden som den kom in, omsparad som JPEG utan EXIF och GPS. Bara de som arbetar
  i kön ser den.
- **Kopian**: originalet vridet rätt och med säljarens och köparens uppgifter täckta av svarta
  rektanglar. Den visas på kaninens sida som "Pappersintyg".

Alla tider är ISO 8601 med tidszon (UTC), till exempel `2026-11-14T08:01:02.123456+00:00`.
Alla datum är `ÅÅÅÅ-MM-DD`.

## Roller

| Roll | Ser | Gör |
|---|---|---|
| Admin | hela kön, originalen | allt |
| Genbanksansvarig (`manager`, per genbank) | hela kön, originalen | tar, tar över, tilldelar poster i sin genbank, sparar med sina vanliga rättigheter, korrigerar, öppnar stängda poster |
| Genbankshjälpare (`helper`, per genbank) | hela kön, originalen | tar, tar över, sparar genom en post hen har tagit det en ägare får spara, för kaniner i sin genbank; lämnar till genbanksansvarig, markerar ofullständig, dubblett och skräp |
| Ägare och skötare | sina egna inskick | laddar upp för sina besättningar |

"Arbetar i kön" betyder admin, genbanksansvarig eller genbankshjälpare i någon genbank. Alla tre
ser hela kön, också den andra genbankens poster. `GET /api/v2/inkorg/notiser/antal` svarar
`works_in_queue` så att gränssnittet vet om kön ska visas.

Rollen genbankshjälpare delas ut som andra roller: `POST /api/v2/admin/role` med
`{"operation": "add", "user_id": 5, "role": {"level": "helper", "genebank": 1}}` (admin), eller
den äldre `POST /api/manage/role` (genbanksansvarig i sin egen genbank). Användarlistan
`GET /api/v2/admin/users?role=helper` filtrerar på rollen, och `role_summary` visar till exempel
`helper(G)`. En hjälpare får läsrätt i sin genbank men ingen egen rätt att ändra kaniner: hen
skriver bara genom en post hen har tagit.

**Skrivrätt genom en post.** När kön sparar en kanin eller en försäljning prövas rätten under
låset, mot den lagrade posten:

- Posten är i läget `tagen` och anroparen är dess handläggare. Det gäller alla, också admin och
  genbanksansvarig.
- Posten har ingen `ref_type`. En post som hänvisar till något annat (till exempel ett förslag
  från årsrapporten) avgörs där och kan aldrig sparas genom kön (409).
- En hjälpare får skriva till en kanin vars besättning ligger i en genbank där hen är hjälpare,
  aldrig i GX1/MX1, och bara det en ägare får: lägga till ett pappersintyg på en kanin som saknar
  intyg, registrera en ny kanin och registrera en försäljning med ett datum som inte ligger före
  kaninens senaste händelse. Korrigeringar (datum före senaste händelse, ändringar av andras rader)
  gör genbanksansvarig och admin. En hjälpare som behöver en korrigering lämnar posten till
  genbanksansvarig (`hos_genbanksansvarig`).
- Genbanksansvarig och admin skriver med sina vanliga rättigheter.

Varje skrivning ger en rad i `inbox_operation` med operationens id, handläggaren och dokumentet,
så att kaninens historik kan visa "inlagd från foto av …". Raden finns kvar också när posten tas
bort.

## Lägen

| Läge | Betyder | Har handläggare |
|---|---|---|
| `ny` | ingen har tagit posten | nej |
| `tagen` | en handläggare har posten | ja |
| `vantar_uppfodare` | en fråga till uppfödaren är skickad (`…/fraga`) | ja |
| `vantar_foralder` | ett intyg kan inte sparas förrän en förälder finns | ja |
| `hos_genbanksansvarig` | lämnad till genbanksansvarig för korrigering eller beslut | nej |
| `ofullstandig` | något saknas; handläggaren har skrivit vad, och avsändaren har fått ett mejl | ja |
| `klar` | alla dokument är klara eller avfärdade, eller meddelandet är besvarat | (den sista) |
| `dubblett` | samma sak finns i en annan post (`duplicate_of`) | (den sista) |
| `skrap` | reklam, fel adress | (den sista) |

`klar`, `dubblett` och `skrap` är stängda (`closed_at` är satt). Öppna lägen är de övriga sex.

Övergångarna:

| Till | Hur | Från | Vem |
|---|---|---|---|
| `ny` | posten kommer in | – | – |
| `tagen` | `…/ta`, `…/ta-over` | alla öppna lägen | alla i kön |
| `tagen` | `…/tilldela` | `ny`, `hos_genbanksansvarig`, `tagen` (de väntande lägena behåller sitt läge och byter bara handläggare) | genbanksansvarig för postens genbank, admin |
| `tagen` | `…/lage` | `vantar_foralder`, `ofullstandig` | handläggaren |
| `tagen` | `…/lage` (öppna igen) | `klar`, `dubblett`, `skrap` | genbanksansvarig för postens genbank, admin; den som öppnar blir handläggare |
| `tagen` | föräldern sparas (var som helst i Stamboken) | `vantar_foralder` | systemet |
| `tagen` | ett svar från avsändaren läses in (se [Fråga uppfödaren](#fråga-uppfödaren)) | `vantar_uppfodare`, `ofullstandig` | systemet |
| `vantar_uppfodare` | `…/fraga` | `tagen` | handläggaren |
| `vantar_foralder` | `…/lage`; något dokument måste ha `waiting_for` | `tagen` | handläggaren |
| `hos_genbanksansvarig` | `…/lage`; handläggaren tas bort | `tagen` | handläggaren |
| `ofullstandig` | `…/lage` med `note` (vad som saknas) | `tagen` | handläggaren |
| `dubblett` | `…/lage` med `duplicate_of` | `tagen`, `vantar_uppfodare`, `vantar_foralder`, `ofullstandig` | handläggaren |
| `skrap` | `…/lage` | `tagen`, `vantar_uppfodare`, `vantar_foralder`, `ofullstandig` | handläggaren |
| `klar` | det sista dokumentet blir klart eller avfärdat | alla öppna lägen | systemet |
| `klar` | `…/lage`, bara för `kind: "meddelande"` ("besvarat"); dokument som kommit med ett svar måste vara klara eller avfärdade | `tagen`, `vantar_uppfodare`, `vantar_foralder`, `ofullstandig` | handläggaren |

Allt annat nekas med 409. `ny` och `vantar_uppfodare` kan inte sättas med `…/lage` (400), och inte heller
`klar` för en post som inte är ett meddelande.

## Arbetsgången

1. Ta posten (`…/ta`), eller få den tilldelad.
2. Gå igenom dokumenten: vrid dem rätt och ange typ och format (`PATCH …/dokument/{dok}`).
3. Ett intyg: spara det intyget visar (`…/spara`), en ny kanin eller pappersintyget på en kanin
   som finns. Visar intyget också en försäljning, registrera den nu (`…/overlat`): ett dokument som
   är klart går inte att spara eller sälja från.
4. Bekräfta vridning och maskning (`…/maskning`). Kopian läggs på kaninen och dokumentet blir klart.
5. Ett överlåtelsebevis: typen `bevis`, sedan `…/overlat`. Beviset blir klart med försäljningen.
6. Ett foto som inte ska sparas: `dismissed: true`.
7. När det sista dokumentet är klart eller avfärdat blir posten `klar`, och uppladdaren får en
   notis och ett mejl.

Saknas en förälder i Stamboken: ange numret i `waiting_for` och byt läge till `vantar_foralder`.
Behövs en korrigering eller ett beslut: lämna posten till genbanksansvarig
(`hos_genbanksansvarig`). Saknas något från uppladdaren: `ofullstandig` med vad som saknas.

## Fel

Alla fel är RFC 9457 Problem Details med `Content-Type: application/problem+json`:

```json
{"type": "about:blank", "title": "Konflikt", "status": 409, "detail": "Ta posten först."}
```

`detail` är på svenska och kan visas för användaren. Vissa fel har fler fält, se respektive
endpoint. Ett fel från `…/spara` och `…/overlat` som gäller ett fält i anropet har dessutom
`"field"`: fältets namn i anropet (till exempel `"paper_number"`, `"mother"` eller `"date"`).
Gränssnittet placerar felet vid det fältet. Har felet inget `field` gäller det anropet som helhet. Gemensamt för alla endpoints:

| Status | När |
|---|---|
| 401 | inte inloggad |
| 403 | anroparen arbetar inte i kön (gäller endpointsen från "Kön" till och med originalet), eller saknar rätt till det anropet gäller |
| 404 | posten finns inte, eller dokumentet hör inte till posten |
| 409 | posten är inte anroparens (`"Ta posten först."`, `"<namn> har posten. Ta över den för att arbeta med den."`), posten är stängd, eller läget tillåter inte anropet |

## Objekt i svaren

### Post (listform)

Kölistan och de flesta anrop som ändrar en post svarar med posten i listform:

```json
{
  "id": 12,
  "kind": "upload",
  "state": "tagen",
  "genebank_id": 1,
  "herd": "G1",
  "received_at": "2026-11-14T08:01:02.123456+00:00",
  "state_changed_at": "2026-11-14T09:15:00.000000+00:00",
  "closed_at": null,
  "sender": {"id": 4, "name": "Test Uppladdare"},
  "assigned_to": {"id": 7, "name": "Konto 7"},
  "assigned_at": "2026-11-14T09:15:00.000000+00:00",
  "duplicate_of": null,
  "stalled": false,
  "missing_proof": false,
  "ref_type": null,
  "ref_id": null,
  "sender_authenticated": null,
  "has_message": true,
  "maybe_blurry": false,
  "documents": 2,
  "documents_done": 1
}
```

- `kind`: `upload`, `mail` (ett mejl med bilagor) eller `meddelande` (ett mejl utan bilagor);
  `kontroll` och `avisering` kommer med senare delar.
- `herd`: besättningsnumret uppladdaren valde. För ett mejl gissningen från avsändarens adress i
  matrikeln, och `null` (okänd) när adressen inte finns där eller medlemskapet har flera
  besättningar; `genebank_id` är då också `null` om besättningarna ligger i olika genbanker.
- `sender` och `assigned_to`: `null` eller `{id, name}`. `name` är kontots fullständiga namn, och
  `"Konto <id>"` när namnet saknas. E-postadressen visas aldrig.
- `missing_proof`: en försäljning har registrerats utan överlåtelsebevis ("bevis saknas").
- `stalled`: "står still". Nattjobbet sätter den på en post som varit `tagen` i 14 dagar utan någon
  händelse (att öppna posten eller visa originalet räknas inte), och tar bort den när något har hänt.
  Genbanksansvariga i postens genbank får notisen `star_still`, en gång för varje gång posten stannar.
- `sender_authenticated`: för en mejlad post `true` när Gmail har godkänt avsändaradressens domän (SPF
  eller DKIM, samma kontroll som kvittot) och annars `false`; `null` för en uppladdning. Mejlen om posten
  (`inlasning.klar`, `inlasning.ofullstandig`, `inlasning.paminnelse`) går till en mejlad posts adress
  bara när den är `true`, så att en förfalskad avsändare aldrig får kön att mejla någon annan. Visa till
  exempel "Avsändaren är inte bekräftad" när den är `false`.
- `maybe_blurry`: något dokument har varningen `suddig` (kön visar "kan vara oskarp").
- `documents` och `documents_done`: antal dokument och antal klara eller avfärdade.

### Post (detalj)

`GET /api/v2/inkorg/{id}` ger listformen och dessutom:

```json
{
  "message": "Tre intyg från i våras",
  "sender_address": null,
  "documents": [ { "…": "dokument, se nedan" } ],
  "events": [
    {"id": 1, "at": "2026-11-14T08:01:02+00:00", "kind": "inkommen", "user": {"id": 4, "name": "Test Uppladdare"}, "detail": {"documents": 2}}
  ]
}
```

`message` är `null` när texten är gallrad (se [Gallring](#gallring)). `sender_address` är avsändarens
adress för en mejlad post och `null` för uppladdningar. Den nollas när posten är stängd och inget mejl
till avsändaren väntar, och senast 30 dagar efter stängningen.

### Dokument

```json
{
  "id": 31,
  "status": "ny",
  "mime": "image/jpeg",
  "quality": {"short_side": 3024, "sharpness": 812.4, "brightness": 201.3},
  "warnings": [],
  "duplicates": [{"item_id": 9, "document_id": 20}],
  "doc_type": "intyg",
  "cert_format": null,
  "rotation": 0,
  "mask_rects": null,
  "mask_suggestion": null,
  "waiting_for": null,
  "interpretation_status": "av",
  "proposal": null,
  "individual": null,
  "herd_tracking_id": null,
  "has_original": true,
  "has_copy": false,
  "done_at": null
}
```

- `status`: `ny`, `vantar_foralder` (har `waiting_for`), `sparad` (kaninen är sparad men kopian är
  inte gjord), `klar` (kopian är gjord, eller beviset hör till en försäljning) eller `avfardad`
  (klart utan att något sparades).
- `quality` och `warnings`: se [Ladda upp](#ladda-upp).
- `duplicates`: andra dokument i kön med exakt samma bild. Visa en varning.
- `doc_type`: `intyg` (standard), `bevis` (överlåtelsebevis), `arsblankett` eller `annat`.
- `cert_format`: `null` eller `handskrivet` (det gröna, format 1), `datorskrivet` (format 2),
  `v1_pdf` (utskriven v1-PDF), `intyg_b` (det nya tomma intyget B), `digitalt_v2` (digitalt intyg
  med QR-kod).
- `rotation`: 0, 90, 180 eller 270 grader medurs, så att intyget står rätt.
- `mask_rects`: rektanglarna som täcker säljaren och köparen, se
  [Maskning](#maskning-och-kopian-på-kaninen). `null` tills handläggaren har angett dem.
- `mask_suggestion`: förslaget när `cert_format` är `handskrivet` och `mask_rects` saknas: den
  nedre tredjedelen, `[{"x": 0.0, "y": 0.6667, "w": 1.0, "h": 0.3333}]`. Annars `null`.
- `waiting_for`: `null` eller en lista med de föräldranummer dokumentet väntar på.
- `interpretation_status`: bildtolkningen av fotot, se [Tolkning](#tolkning). `av` (tolkningen är
  avstängd, eller dokumentet är inget intyg), `vantar` (i kö), `klar` (förslaget finns) eller
  `misslyckad` (två försök gick fel; handläggaren skriver av fälten själv).
- `proposal`: `null`, eller förslaget från tolkningen när `interpretation_status` är `klar`:

  ```json
  {
    "fields": {
      "paper_number": {"value": "G1-2511", "source": "läst", "read": "G1 2511"},
      "mother": {"value": "G1-1911", "source": "härlett", "read": "61 1911"},
      "father": {"value": null, "source": "avviker", "read": "G2 1712"},
      "farfar": {"value": null, "source": "avviker", "read": "G2 1411", "registry": "G2-1311"},
      "birth_date": {"value": null, "source": "osäker", "read": "10/5"}
    },
    "checks": [
      {"ok": true, "text": "Intygsnumret är ledigt."},
      {"ok": false, "text": "Far: far- och morföräldrarna på intyget är inte registrets för G2-1712."}
    ]
  }
  ```

  Nycklarna i `fields` är fälten i `…/spara` (se [Spara det intyget visar](#spara-det-intyget-visar)),
  `individual` när kaninen redan finns i Stamboken, och `farfar`, `farmor`, `morfar` och `mormor`.
  Ett fält som tolkningen inte såg saknas. `source` säger varifrån värdet kommer: `läst` (läst på
  intyget; ett nummer är dessutom bekräftat av registret, medan namn, kön, färg, intygsnummer och, för
  en kull som inte finns i Stamboken, födelsedatum och antal bara är lästa och giltiga), `härlett`
  (hämtat ur registret), `avviker` (intyget och registret säger olika) eller `osäker`. Bara `läst` och
  `härlett` har ett `value` att fylla i formuläret med; `avviker` och `osäker` har `value: null` och
  skrivs av från fotot. `read` är det tolkningen läste på intyget och `registry` registrets värde där
  de skiljer sig. `checks` är kontrollerna i ord; `ok` är `true`, `false` eller `null` (upplysning).
  Förslaget sparas aldrig av sig självt: det är handläggarens `…/spara` som skriver.
- `individual`: kaninens nummer när dokumentet är sparat, annars `null`.
- `herd_tracking_id`: raden i besättningshistoriken för försäljningen som registrerats genom
  dokumentet (för ett bevis: försäljningen det visar).
- `has_original`: originalet finns. `false` när det är gallrat eller raderat på begäran (se
  [Gallring](#gallring)); `…/original` svarar då 404.
- `has_copy`: kopian finns.

### Händelser

`events` är postens historik, äldst först. `user` är `null` för systemets händelser.

| `kind` | `detail` |
|---|---|
| `inkommen` | `{"documents": 2}`; för ett mejl också `not_saved` (namnen på bilagor som inte sparades) och `maybe_item` (posten ett svar från någon annan kanske gäller), när de finns |
| `oppnad` | `null`; någon i kön öppnade posten (högst en gång i timmen per person och post) |
| `tagen` | `null` |
| `overtagen` | `{"from_user": 7}` |
| `tilldelad` | `{"to_user": 7, "from_user": null}` |
| `lage` | `{"from": "tagen", "to": "ofullstandig", "note": "Pappersintyget saknas"}`; `note` bara när den gavs, `duplicate_of` vid `dubblett` |
| `dokument` | `{"document": 31, "fields": ["mask_rects", "rotation"]}` |
| `sparad` | `{"document": 31, "action": "ny_kanin" \| "pappersintyg", "individual": "G1-2511"}`, eller vid en försäljning `{"document": 31, "action": "overlatelse", "individual": "G1-2111", "herd": "G2", "missing_proof": true}`; `"action": "bevis"` när ett bevis kopplas till en försäljning som redan är registrerad |
| `kopia` | `{"document": 31, "rects": 1, "rotation": 90}`; varje anrop till `…/maskning` |
| `original_visat` | `{"document": 31}` |
| `foralder_inlagd` | `{"individual": "G1-2431"}` |
| `fraga` | `{"text": "Står det G1-2112?", "document": 31, "rotation": 0, "crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.25}}`; de tre sista bara med utsnitt |
| `svar` | `{"text": "Ja.", "documents": [33], "not_saved": ["brev.docx"]}`; `user` är `null`, `not_saved` bara när något inte sparades |
| `tolka_igen` | `{"document": 31}`; handläggaren lade dokumentet i tolkningens kö igen |
| `original_raderat` | `{"document": 31}`; originalet raderades på begäran (`…/radera-original`) |

När postens text gallras försvinner `text`, `note` och `not_saved` ur `detail`; händelsen står kvar.

## Ladda upp

### `POST /api/v2/inkorg/upload`

**Vem:** inloggad ägare eller skötare av besättningen (den finns bland användarens besättningar),
eller vem som helst som arbetar i kön, för vilken besättning som helst. Högst 20 anrop i timmen
per användare (429 efter det).

**Begäran:** `multipart/form-data`:

| Fält | | |
|---|---|---|
| `herd` | krävs | besättningsnumret, till exempel `G1` |
| `files` | krävs, upprepas | 1–10 filer: JPEG, PNG, WebP, HEIC eller PDF, högst 10 MB styck |
| `message` | valfritt | uppladdarens meddelande, högst 2000 tecken |
| `dry_run` | valfritt | `1` eller `true`: mät bilderna och svara, men spara ingenting |

Filtypen avgörs av filens innehåll, inte av namnet. Varje bild avkodas, vrids efter telefonens
orientering och sparas om som JPEG utan EXIF och GPS. En PDF blir en bild per sida (200 dpi,
högst 3000 bildpunkter på längsta sidan). Allt som allt högst 10 bilder per inskick: en PDF
räknas sida för sida. En bild får ha högst 40 megapixlar.

**Kvalitet.** Varje bild mäts direkt:

- `short_side`: den kortaste sidan i bildpunkter;
- `sharpness`: skärpan, variansen efter ett kantfilter på en nedskalad gråbild;
- `brightness`: medelljuset, 0–255.

`warnings` listar det som gör bilden svårläst: `lag_upplosning` (kortaste sidan under 1000
bildpunkter), `suddig`, `for_mork`, `for_ljus`. Gränserna är preliminära. Visa till exempel
"Bilden ser suddig ut. Ta om den?" med "Skicka ändå". Gränssnittet kan först anropa med
`dry_run=1`, visa varningarna och sedan skicka på riktigt; båda anropen räknas mot gränsen 20 i
timmen.

**Svar 201** (inskicket är sparat):

```json
{
  "item": { "…": "posten i listform, state ny" },
  "documents": [
    {"id": 31, "file": 0, "page": null, "quality": {"short_side": 3024, "sharpness": 812.4, "brightness": 201.3}, "warnings": []},
    {"id": 32, "file": 1, "page": 1, "quality": {"short_side": 1654, "sharpness": 12.0, "brightness": 210.0}, "warnings": ["suddig"]}
  ]
}
```

`file` är filens plats (0, 1, …) i begäran, och `page` sidan i en PDF (`null` för en bild).

**Svar 200** med `dry_run`: samma `documents` utan `id`, och inget `item`.

Genbanksansvarig och hjälpare i besättningens genbank får notisen `ny_post`, utom uppladdaren
själv.

**Fel:**

| Status | `detail` |
|---|---|
| 400 | `Välj besättning.` (saknas eller okänd), `Ingen fil bifogad.`, `Högst 10 bilder per inskick. En PDF räknas sida för sida.`, `Meddelandet får vara högst 2000 tecken.` |
| 403 | `Du kan bara skicka in för dina egna besättningar.` |
| 413 | `Filen är för stor. Max 10 MB.`, `Bilden har för många pixlar. Max 40 megapixlar.` |
| 415 | `Otillåten filtyp. Bara JPEG, PNG, WebP, HEIC och PDF.` |
| 422 | `Filen kunde inte läsas. Den kan vara skadad.` |
| 429 | för många inskick den senaste timmen |

Ett fel på en fil stoppar hela inskicket: ingenting sparas.

## Kön

Alla endpoints från och med det här avsnittet till och med originalet under [Bilderna](#bilderna)
kräver att anroparen arbetar i kön (annars 403).

### `GET /api/v2/inkorg`

Kölistan, äldst först (`received_at`).

| Parameter | |
|---|---|
| `scope=mina` | poster i de genbanker där anroparen är genbanksansvarig eller hjälpare, och poster utan genbank. Standard för genbanksansvariga och hjälpare |
| `scope=alla` | alla poster. Standard för admin |
| `mine=1` | poster där anroparen är handläggare |
| `untaken=1` | poster utan handläggare |
| `assigned_to=<user id>` | en viss handläggares poster |
| `genebank_id=<id>` | en genbank |
| `herd=<besättningsnummer>` | en besättning |
| `state=<läge>[,<läge>…]` | ett eller flera lägen; utelämnad: alla öppna lägen; `state=alla`: alla lägen |
| `kind=<typ>` | posttyp |
| `limit`, `offset` | sidindelning; `limit` 1–200, standard 50 |

**Svar 200:**

```json
{
  "items": [ { "…": "poster i listform" } ],
  "total": 17,
  "counts": {"ny": 9, "tagen": 6, "klar": 2},
  "interpretation": {"interpreter": "gemma", "waiting": 3, "last_done_at": "2026-11-14T08:01:02+00:00", "alarm": false},
  "scope": "mina",
  "my_genebanks": [1]
}
```

`scope` är den avgränsning som användes och `my_genebanks` id:na för de genbanker där anroparen är
genbanksansvarig eller hjälpare (tom för en admin utan sådana roller), oberoende av filtren, så att
`GET /api/v2/inkorg?limit=1` räcker för att läsa dem. `scope` avgränsar bara listan: alla som arbetar
i kön kan öppna och läsa varje post, och reglerna för att skriva är desamma. `total` är antalet poster
med alla filter. `counts` är antalet per läge med alla filter utom `state` (också `scope`), så att
flikar per läge kan visa sina antal. Ett läge utan poster saknas i `counts`.
`interpretation` är tolkningens läge, oberoende av filtren: `interpreter` (`av` när den är
avstängd), `waiting` (intyg i kö), `last_done_at` (när det senaste förslaget blev klart) och
`alarm`, som är `true` när de tre senast tolkade dokumenten alla misslyckades (till exempel när
tolkningen inte är igång eller har slut på minne). Se [Tolkning](#tolkning).

**Fel:** 400 för ett okänt läge, en okänd `scope` eller ett id som inte är ett heltal.

### `GET /api/v2/inkorg/handlaggare`

De som kan arbeta med poster, för personväljare och tilldelning: varje aktiv admin,
genbanksansvarig och genbankshjälpare, sorterade efter namn. Bara id och namn (namnet som i
`sender`), aldrig e-postadress eller användarnamn. Posten kan ändå bara tilldelas den som får
arbeta i postens genbank (se [Ta, ta över och tilldela](#ta-ta-över-och-tilldela)).

**Svar 200:** `{"people": [{"id": 7, "name": "Test Hjälpare"}]}`

### `GET /api/v2/inkorg/{id}`

Posten i detaljform med dokument och historik. Öppnandet loggas som händelsen `oppnad` (vem och
när), högst en gång i timmen per person och post så att en omladdning inte fyller historiken. Ett
öppnande efter en timme loggas igen. Anroparens notiser om posten blir lästa varje gång.

## Ta, ta över och tilldela

Svaren är posten i listform.

### `POST /api/v2/inkorg/{id}/ta`

"Jag tar den": posten blir `tagen` med anroparen som handläggare. Har anroparen redan posten i
läget `tagen` händer ingenting. **409** när någon annan har posten
(`"<namn> har posten. Ta över den för att arbeta med den."`) eller posten är stängd.

### `POST /api/v2/inkorg/{id}/ta-over`

"Ta över": som `…/ta`, men också när någon annan har posten. Den som hade posten får notisen
`overtagen`. Posten blir `tagen` också om den väntade. **409** när posten är stängd.

### `POST /api/v2/inkorg/{id}/tilldela`

```json
{"user_id": 7}
```

**Vem:** genbanksansvarig för postens genbank, eller admin (en post utan genbank: alla
genbanksansvariga). Mottagaren måste vara aktiv och admin, eller genbanksansvarig eller hjälpare
i postens genbank. `ny` och `hos_genbanksansvarig` blir `tagen`; en väntande post behåller sitt
läge och får bara en ny handläggare. Mottagaren får notisen `tilldelad`, utom när hen tilldelar
sig själv.

**Fel:** 400 utan giltigt `user_id` eller när mottagaren inte kan få posten, 403 utan rätt att
tilldela, 409 när posten är stängd.

### `POST /api/v2/inkorg/tilldela`

Alla öppna poster för en besättning till en person.

```json
{"herd": "G1", "user_id": 7}
```

**Svar 200:** `{"assigned": [12, 15]}`, postnumren som tilldelades. Samma regler och fel som
ovan; ett fel på någon post stoppar alla.

## Byta läge

### `POST /api/v2/inkorg/{id}/lage`

```json
{"state": "ofullstandig", "note": "Pappersintyget till beviset saknas"}
```

| Fält | |
|---|---|
| `state` | `tagen`, `vantar_foralder`, `hos_genbanksansvarig`, `ofullstandig`, `dubblett`, `skrap`, eller `klar` för ett meddelande |
| `note` | text, högst 2000 tecken; krävs för `ofullstandig`, valfri annars; sparas i händelsen |
| `duplicate_of` | krävs för `dubblett`: id för den andra posten |

Reglerna står i [Lägen](#lägen). Vid `hos_genbanksansvarig` tas handläggaren bort och
genbanksansvariga i postens genbank får notisen `lamnad`. Vid `ofullstandig` köas mejlet
`inlasning.ofullstandig` till avsändaren (se [Mejl](#mejl)). Ett meddelande som stängs som `klar` ger
inget mejl. Öppnar genbanksansvarig eller admin en stängd post blir hen handläggare.

**Svar 200:** posten i listform.

**Fel:** 400 för ett okänt läge, `klar` för en post som inte är ett meddelande, `ofullstandig` utan
`note`, `dubblett` utan en annan post, `vantar_foralder` när inget dokument har `waiting_for`; 403 när
någon annan än genbanksansvarig eller admin öppnar en stängd post; 409 när anroparen inte är
handläggare, övergången inte finns eller ett meddelande har dokument som inte är klara (`Gör klart
eller avfärda dokumenten först.`).

## Dokument

### `PATCH /api/v2/inkorg/{id}/dokument/{dok}`

**Vem:** handläggaren (posten i ett läge med handläggare). Skicka bara fälten som ändras.

```json
{"doc_type": "intyg", "cert_format": "handskrivet", "rotation": 90, "mask_rects": [{"x": 0, "y": 0.66, "w": 1, "h": 0.34}]}
```

| Fält | |
|---|---|
| `doc_type` | `intyg`, `bevis`, `arsblankett` eller `annat`. Blir dokumentet ett intyg läggs det i tolkningens kö (när tolkningen är på); andra typer tolkas inte (`interpretation_status: "av"`) |
| `cert_format` | `null` eller ett av formaten under [Dokument](#dokument) i objekten |
| `rotation` | 0, 90, 180 eller 270 (grader medurs) |
| `mask_rects` | `null` eller en lista med högst 20 rektanglar, se [Maskning](#maskning-och-kopian-på-kaninen) |
| `waiting_for` | `null`, `[]` eller en lista med ett eller två individnummer (till exempel `G1-2431`) som inte finns i Stamboken än |
| `dismissed` | `true` avfärdar dokumentet (klart utan att något sparas, till exempel ett foto som inte är ett intyg); `false` ångrar det, om inget har sparats från dokumentet |

När dokumentet har en kopia nekas `rotation`, `mask_rects` och `doc_type` (409): kopian görs bara om
med `…/maskning`. `doc_type` nekas också när något har sparats från dokumentet (en kanin eller en
försäljning). Blir det sista dokumentet avfärdat blir posten `klar`.

**Svar 200:** `{"item": <post i listform>, "document": <dokument>}`.

**Fel:** 400 för ett okänt fält, ett ogiltigt värde, ett nummer som inte går att läsa eller som
redan finns i Stamboken (`"G1-2111 finns redan i Stamboken."`); 404 när dokumentet inte hör till
posten; 409 när anroparen inte är handläggare, när kopian är gjord och anropet ändrar `rotation`,
`mask_rects` eller `doc_type`, eller när typen ändras på ett dokument som något har sparats från.

**Väntar på förälder.** Saknas en förälder i Stamboken: ange förälderns nummer i `waiting_for`
och byt läge till `vantar_foralder`. När en kanin med det numret läggs in, var som helst i
Stamboken, tas numret bort ur `waiting_for` i samma transaktion. Väntar posten inte längre på
någon förälder blir den `tagen` igen, och handläggaren får notisen `foralder_inlagd` (har posten
ingen handläggare får genbanksansvariga den).

### `POST /api/v2/inkorg/{id}/dokument/{dok}/tolka-igen`

"Tolka igen", till exempel när fotot har vridits rätt: dokumentet väntar på tolkningen igen
(`interpretation_status: "vantar"`), med två nya försök, och det gamla förslaget tas bort. Se
[Tolkning](#tolkning). Händelsen `tolka_igen` loggas.

**Vem:** handläggaren (posten i ett läge med handläggare).

**Svar 200:** `{"item": <post i listform>, "document": <dokument>}`.

**Fel:** 404 när dokumentet inte hör till posten; 409 när anroparen inte är handläggare, när
tolkningen är avstängd (`Bildtolkningen är avstängd.`), när dokumentet inte är ett intyg som
inte sparats än (`Bara ett intyg som inte är sparat kan tolkas.`) eller när originalet är raderat.

## Spara det intyget visar

### `POST /api/v2/inkorg/{id}/dokument/{dok}/spara`

**Vem:** handläggaren, med posten i läget `tagen`, posten utan `ref_type` och dokumentet av typen
`intyg`, inte sparat än. Rätten att skriva prövas som i [Roller](#roller).

Två sorters anrop, valda med `action`.

#### `"action": "ny_kanin"`: en ny kanin

Registrerar kaninen precis som `POST /api/v2/individual` gör (samma regler och felsvar), alltid
med pappersintyg. Kullen anges med föräldrarna och födelsedatumet; finns den inte skapas den.

```json
{
  "action": "ny_kanin",
  "mother": "G1-1911",
  "father": "G2-1711",
  "birth_date": "2025-05-10",
  "litter_size": 5,
  "litter_size6w": 4,
  "paper_number": "G1-2511",
  "paper_certificate": "123456",
  "name": "Stina",
  "sex": "female",
  "color": "viltgrå"
}
```

Vad på intyget som hör till vilket fält:

| På intyget | Fält |
|---|---|
| Kaninens nummer (individnumret) | `paper_number`, krävs, till exempel `G1-2511` |
| Intygsnummer | `paper_certificate`, krävs, högst 20 tecken |
| Namn | `name`, högst 50 tecken |
| Kön | `sex`: `female`, `male` |
| Födelsedatum | `birth_date`, krävs om `breeding_id` saknas |
| Färg | `color`: färgens namn som det står i genbankens färglista |
| Kullstorlek (antal födda) | `litter_size`, krävs när kullen skapas, minst 1 |
| Antal levande vid 6 veckor | `litter_size6w`, krävs när kullen skapas, minst 1 och högst `litter_size`; står inte alltid på intyget |
| Mor: nummer | `mother`, krävs om `breeding_id` saknas: en registrerad kanin |
| Far: nummer | `father`, som `mother`; samma genbank som modern |
| Mor och far: namn och färg; far- och morföräldrarna (nummer, namn och färg) | skickas inte. De följer av mor och far i registret. Visa registrets uppgifter bredvid fotot så att handläggaren kan jämföra. |

Valfria fält i övrigt: `breeding_id` (en känd kull, i stället för `mother`, `father` och
`birth_date`), `breed_date` (parningsdatum; standard 31 dagar före födseln), `position` (platsen i
kullen), `color_note`, `eye_color`, `claw_color`, `belly_color`, `hair_notes` och `resolution`.

Kullen skapas i moderns besättning, och kaninen föds där. Kaninen måste vara minst 42 dagar.

**Svar 201:** svaret från `POST /api/v2/individual` och dessutom posten och dokumentet:

```json
{
  "individual": { "…": "kaninen, som GET /api/v2/individual/{nummer}" },
  "certificate": "123456",
  "certificate_error": null,
  "breeding": {"id": 88, "litter_number": 1, "created": true},
  "item": { "…": "posten i listform" },
  "document": { "…": "dokumentet, status sparad" }
}
```

**Fel:** som `POST /api/v2/individual`, bland annat:

| Status | När |
|---|---|
| 400 | `Välj mor och far bland registrerade kaniner.` (en unge utan föräldrar), ett datum, en kullstorlek eller ett individnummer som saknas eller är fel |
| 403 | anroparen får inte registrera i moderns besättning (`Modern finns inte i en besättning där du får registrera kaniner.` eller `Åtkomst nekad`) |
| 409, `title: "number_conflict"` | pappersintygets individnummer stämmer inte med det Stamboken ger. Svaret har kontrollens fält: `stamboken_number`, `paper_number`, `check_status`, `conflicts`, `choices`, `actions`. Inget sparas. Visa skillnaden; väljer handläggaren Stambokens nummer, skicka samma anrop med `"resolution": {"expected_number": "<stamboken_number>", "choice": "use_stamboken_number"}`. Stämmer pappret, lämna posten till genbanksansvarig. |
| 409, `title: "litter_order_conflict"` | kullen är född före en kull som redan har kullnummer det året |
| 409, `title: "Conflict"` | intygsnumret används redan |
| 422, `title: "too_young"` | kaninen är yngre än 42 dagar |

`POST /api/v2/individual/number-check` och `GET /api/v2/individual/suggest-number` prövar ägarens
och genbanksansvarigs rätt, inte hjälparens. En hjälpare får därför kontrollen genom 409-svaret från `…/spara`.

#### `"action": "pappersintyg"`: pappersintyget på en kanin som finns

```json
{"action": "pappersintyg", "individual": "G1-2511", "paper_certificate": "123456", "paper_number": "G1-2511"}
```

`individual` är kaninens nummer i Stamboken, `paper_number` numret som står på intyget. En
hjälpare får bara sätta intyget på en kanin som saknar intyg.

**Svar 200:** `{"individual": <kaninen>, "item": <post>, "document": <dokument>}`.

**Fel:** 400 utan intygsnummer eller individnummer, eller när intygsnumret redan finns
(`Individual certificate already exists`); 403 när anroparen inte får ändra kaninen eller kaninen
redan har intyg och anroparen inte är genbanksansvarig eller admin; 404 när kaninen inte finns;
409 `number_conflict` när `paper_number` inte är kaninens nummer i Stamboken (eller finns på en annan
kanin), med samma fält som ovan. `resolution` läses inte här: kaninens nummer är redan satt och
pappret kan inte rätta det, så ett intyg med ett annat nummer lämnar handläggaren till
genbanksansvarig (`hos_genbanksansvarig`).

**För båda:** 409 när posten inte är anroparens, inte är `tagen`, har `ref_type`, eller
dokumentet inte är ett osparat intyg, och när dokumentet redan gäller en annan kanin (se nedan);
400 för okänd `action`.

**Ett dokument, en kanin.** Det första som sparas genom ett dokument (en ny kanin, ett
pappersintyg eller en försäljning) binder dokumentet till den kaninen. Allt som sparas genom det
sedan måste gälla samma kanin (409 `Dokumentet gäller G1-2111. …`), och ett dokument bär högst en
registrering och en försäljning. Är en kanin såld genom dokumentet kan en ny kanin inte sparas från
det. Efter sparandet har dokumentet
`status: "sparad"`. Det blir klart först när maskningen är bekräftad.

## Registrera en försäljning

### `POST /api/v2/inkorg/{id}/dokument/{dok}/overlat`

Registrerar att kaninen sålts, med samma regler som försäljningen på kaninens sida.

```json
{"individual": "G1-2511", "herd": "G2", "date": "2026-10-03"}
```

| Fält | |
|---|---|
| `individual` | kaninens nummer |
| `herd` | köparens besättningsnummer. En köpare utanför föreningen: genbankens besättning för kaniner sålda utanför genbanken, `GX1` (gotlandskanin) eller `MX1` (mellerudskanin). Köparens namn och adress sparas inte; de finns bara på originalfotot. |
| `date` | försäljningsdatumet |

**Vem:** handläggaren, med samma krav på posten som för `…/spara` men för alla dokumenttyper.
En hjälpare får sälja kaniner i sin genbank som en ägare får.

**Bevis.** Är dokumentet ett överlåtelsebevis (`doc_type: "bevis"`) blir det klart och kopplas
till försäljningens rad (`herd_tracking_id`). Annars registreras försäljningen ändå, och posten
får `missing_proof: true` ("bevis saknas"). Kommer beviset senare till samma post skickas det med
`…/overlat` med samma kanin, köpare och datum: det kopplas då till försäljningen som redan finns,
utan att den registreras igen, och `missing_proof` blir `false` när ingen försäljning i posten
längre saknar bevis. Den som kopplar måste få sälja kaninen, som för en försäljning.

**Korrigering.** Ligger datumet före kaninens senaste händelse är det en korrigering. Den gör
bara genbanksansvarig för kaninens genbank och admin, och anropet skriver då in försäljningen på
sin plats i historiken. Alla andra får 400.

**Svar 200:**

```json
{"individual": { "…": "kaninen" }, "herd_tracking_id": 512, "item": { "…": "posten" }, "document": { "…": "dokumentet" }}
```

**Fel:**

| Status | När |
|---|---|
| 400 | besättning eller datum saknas eller är okänd; `title: "Ogiltig försäljning"` med försäljningens regler: datumet i framtiden, före 43 dagars ålder eller före kaninens senaste händelse, en annan genbank, en kanin utan intyg till en annan besättning än GX1/MX1, kaninen finns redan där |
| 403 | anroparen får inte sälja kaninen |
| 404 | kaninen finns inte |
| 409 | som för `…/spara`; en försäljning är redan registrerad genom dokumentet; eller besättningshistoriken skulle bli motsägelsefull (med `rows`) |

## Maskning och kopian på kaninen

Kopian på kaninen är originalet vridet `rotation` grader medurs, med svarta rektanglar över
säljarens och köparens uppgifter. Den ska inte visa andra personuppgifter än uppfödarens.

**Rektanglarna** anges i bråkdelar av bilden *efter* vridningen: `x` och `y` är det övre vänstra
hörnet, `w` och `h` bredd och höjd, alla mellan 0 och 1, och rektangeln måste ligga inom bilden.
`{"x": 0, "y": 0.5, "w": 1, "h": 0.5}` täcker den nedre halvan. Gränssnittet kan förhandsvisa
kopian genom att rita rektanglarna över det vridna originalet.

### `POST /api/v2/inkorg/{id}/dokument/{dok}/maskning`

Bekräftar vridningen och maskningen tillsammans och gör kopian av just det paret.

```json
{"rotation": 90, "mask_rects": [{"x": 0, "y": 0.6667, "w": 1, "h": 0.3333}]}
```

| Fält | |
|---|---|
| `rotation` | krävs: 0, 90, 180 eller 270 grader medurs |
| `mask_rects` | krävs: rektanglarna i bråkdelar av bilden vriden `rotation` grader. Får inte vara `null` |
| `no_personal_data` | `true` krävs när `mask_rects` är en tom lista: intyget visar ingen säljare eller köpare |

Båda värdena sparas på dokumentet i samma transaktion som kopian görs. Det som redan står på
dokumentet (från `PATCH`) används inte: kopian visar exakt det paret som skickades.

**Vem:** handläggaren medan posten är öppen. Har dokumentet redan en kopia får också
genbanksansvarig för postens genbank och admin göra om den, i alla lägen och också när posten är
stängd eller någon annan har den, så att en felaktig kopia kan rättas. Dokumentet måste vara ett
sparat intyg (`individual` satt).

Dokumentet blir klart (`status: "klar"`, `has_copy: true`). Är alla dokument i posten klara
eller avfärdade blir posten `klar`, uppladdaren får notisen `klar` och mejlet `inlasning.klar`.
Varje anrop loggas som händelsen `kopia`.

**Svar 200:** `{"item": <post>, "document": <dokument>}`.

**Fel:** 400 när `rotation` eller `mask_rects` saknas eller är ogiltiga, eller när `mask_rects` är tom
utan `"no_personal_data": true`; 409 när dokumentet inte är ett sparat intyg, anroparen inte får göra
kopian eller originalet är raderat.

## Bilderna

Båda svarar med `image/jpeg` och `Cache-Control: no-store, private`. Bilderna ligger utanför den
publika uppladdningskatalogen och nås bara genom de här endpointsen.

### `GET /api/v2/inkorg/{id}/dokument/{dok}/original`

Originalet. **Vem:** de som arbetar i kön. Varje hämtning loggas som händelsen `original_visat`.
**404** (`Originalet är raderat.`) när originalet är gallrat eller raderat på begäran; inget loggas då.

### `GET /api/v2/individual/{nummer}/paper-certificate`

Kaninens pappersintyg: den senaste kopian som gjorts från ett intyg för kaninen. **Vem:** den som
får hämta kaninens intyg i dag, alltså ägaren, uppfödaren (ursprungsbesättningen),
genbanksansvarig och admin. En genbankshjälpare ser originalet i kön men inte den här.

**Fel:** 403 för den som inte får se intyget; 404 när kaninen inte finns eller inte är
tillgänglig, eller saknar ett inläst pappersintyg (`Kaninen har inget inläst pappersintyg.`).
Gränssnittet kan använda 404 för att dölja "Pappersintyg" på kaninens sida.

## Fråga uppfödaren

### `POST /api/v2/inkorg/{id}/fraga`

**Vem:** handläggaren, med posten i läget `tagen`.

```json
{"text": "Står det G1-2112 eller G1-2113?", "document": 31, "crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.25}}
```

| Fält | |
|---|---|
| `text` | krävs, högst 2000 tecken |
| `crop` | valfritt: utsnittet av fotot som frågan gäller, en rektangel som i [Maskning](#maskning-och-kopian-på-kaninen) (bråkdelar av bilden efter dokumentets vridning) |
| `document` | krävs med `crop`: dokumentet som utsnittet är ur |

Frågan sparas som händelsen `fraga`, och mejlet `inlasning.fraga` köas till besättningens
innehavare enligt matrikeln (medlemskapets huvudmedlem). Ämnesraden slutar med "(ärende 12)".
Med `crop` bifogas utsnittet som JPEG, skuret ur originalet när mejlet skickas, utom när originalet
hunnit raderas. Är frågans text gallrad när mejlet ska gå stoppas det. Posten blir
`vantar_uppfodare`.

Svaret kommer till föreningens brevlåda. Det läggs på posten som händelsen `svar`, med svarets
foton som nya dokument, bara när Gmail har godkänt avsändarens domän och avsändaren är den som
fick frågan, postens avsändare eller besättningens innehavare. Väntade posten på svaret
(`vantar_uppfodare`) eller var den `ofullstandig` blir den `tagen` igen, och handläggaren får notisen
`svar`. Mejlen om en ofullständig post ber avsändaren svara med det som saknas. Annars blir svaret en egen post med `maybe_item` (se
[Mejlade poster](#mejlade-poster)).

**Svar 200:** posten i listform.

**Fel:** 400 utan text eller med för lång text, med `crop` utan `document` eller med en
rektangel utanför bilden; 403 när anroparen inte arbetar i kön; 404 när dokumentet inte hör
till posten; 409 när anroparen inte är handläggare, posten inte är `tagen`, eller besättningen
saknar innehavare med e-post i matrikeln.

## Mejlade poster

Jobbet `inbox_gmail` läser föreningens brevlåda var femte minut när `INLASNING_GMAIL=on` (drift
och inställningar: [inkorg-gmail.md](inkorg-gmail.md)). Varje mejl i inkorgen blir en av:

- en studs: mejlkön markerar mejlet som `bounced` ([mejl.md](mejl.md)). En studs som inte går
  att koppla till ett mejl blir en post av typen `meddelande`;
- ett autosvar: ingenting;
- ett svar på ett mejl om en post: läggs på posten (se [Fråga uppfödaren](#fråga-uppfödaren));
- en ny post, `mail` med bilagor och `meddelande` utan.

En ny post får avsändarens adress i `sender_address`, mejlets text i `message` (en HTML-text
utan taggar; bara de första 200 000 tecknen läses och högst 10 000 sparas) och en gissad besättning. Bilagorna går genom samma kontroller som en uppladdning
([Ladda upp](#ladda-upp)): JPEG, PNG, WebP, HEIC och PDF, högst 10 MB styck och högst 10 bilder
per mejl. En bild vars kortaste sida är under 200 bildpunkter (en logotyp i signaturen, en
spårningspixel) är inget dokument. Övriga bilagor sparas inte, men deras namn står i händelsen `inkommen`. Ett foto som
skickats inbäddat i texten räknas som en bilaga. Genbanksansvarig och hjälpare i postens
genbank får notisen `ny_post`, alla i kön när genbanken är okänd.

Ett mejl som ser ut som ett svar men inte får läggas på posten (avsändaren är inte godkänd, är
någon annan, eller posten är stängd) blir en ny post med `maybe_item` i händelsen `inkommen`.
Gränssnittet visar "Gäller kanske ärende 12". Handläggaren avgör.

### `GET /api/v2/inkorg/status`

**Vem:** de som arbetar i kön. För larmet överst i kön.

```json
{"gmail": {"enabled": true, "last_run_at": "2026-11-14T08:05:00+00:00", "last_error": null, "alarm": false}}
```

`last_run_at` är den senaste körningen som gick igenom, och `last_error` felet från den senaste
körningen: ett mejl som inte gick att läsa (efter tre körningar i rad får det etiketten "Fel vid
inläsning" i brevlådan) eller en körning som avbröts. `alarm` är sant när `last_error` finns, eller när
läsningen är på och inte har gått igenom de senaste 20 minuterna. Gränssnittet visar då en rad
överst i kön.

## Mina inskick

### `GET /api/v2/inkorg/mina-inskick`

**Vem:** inloggad. Anroparens egna inskick, nyast först, i klartext. Anropet läser också
anroparens notiser av typen `klar`.

```json
{
  "items": [
    {"id": 12, "status": "klart", "received_at": "2026-11-14T08:01:02+00:00", "herd": "G1", "documents": 2, "individuals": ["G1-2511"]}
  ]
}
```

| `status` | Visa | Postens läge |
|---|---|---|
| `mottaget` | Mottaget | `ny` |
| `under_arbete` | Under arbete | `tagen`, `vantar_foralder`, `hos_genbanksansvarig` |
| `fragat` | Vi har frågat dig något | `vantar_uppfodare`, `ofullstandig` |
| `klart` | Klart | `klar` |
| `avslutat` | Avslutat | `dubblett`, `skrap` |

`individuals` är numren på kaninerna som sparats från inskicket; länka till kaninens sida.
Handläggare och historik visas inte för uppladdaren.

## Notiser

Alla har notiser, också den som bara laddar upp. Notiserna gäller poster och nyast kommer först.

| `kind` | `text` | Till |
|---|---|---|
| `ny_post` | Ny post i inläsningskön | genbanksansvarig och hjälpare i postens genbank (alla i kön när genbanken är okänd) |
| `tilldelad` | En post har tilldelats dig | den som får posten |
| `overtagen` | Någon har tagit över din post | den som hade posten |
| `lamnad` | En post har lämnats till genbanksansvarig | genbanksansvariga i postens genbank |
| `foralder_inlagd` | Föräldern är inlagd, och posten väntar inte längre | handläggaren |
| `svar` | Uppfödaren har svarat | handläggaren; genbanksansvariga i postens genbank när posten saknar handläggare |
| `klar` | Ditt inskick är klart | uppladdaren; länka till Mina inskick, inte till kön |
| `star_still` | En post har stått still i 14 dagar | genbanksansvariga i postens genbank (alla genbanksansvariga och admin när genbanken är okänd) |

En notis blir läst när posten öppnas (`GET /api/v2/inkorg/{id}`), när Mina inskick öppnas
(notiser av typen `klar`) eller genom `…/notiser/las`.

### `GET /api/v2/inkorg/notiser`

Parametrar: `unread=1` bara olästa; `limit` (1–200, standard 50) och `offset`.

```json
{
  "notices": [
    {"id": 40, "kind": "ny_post", "text": "Ny post i inläsningskön", "item_id": 12, "created_at": "2026-11-14T08:01:02+00:00", "read_at": null}
  ],
  "unread": 3
}
```

### `GET /api/v2/inkorg/notiser/antal`

För räknaren i menyn: `{"unread": 3, "works_in_queue": true}`.

### `POST /api/v2/inkorg/notiser/las`

`{"ids": [40, 41]}` läser de notiserna, `{"all": true}` alla. Andras notiser påverkas aldrig.
**Svar 200:** `{"read": 2, "unread": 1}`. **400** utan `ids` eller `all`.

### `GET` och `PUT /api/v2/inkorg/notiser/installning`

Om notiserna också ska komma per mejl, i det dagliga sammandraget. `PUT` med
`{"mail_enabled": false}`. **Svar 200:** `{"mail_enabled": false}`. Standard är `true`. Notiserna
syns i Stamboken oavsett.

## Mejl

Mejlen går genom mejlkön ([mejl.md](mejl.md)) och köas i samma transaktion som ändringen.

- **`inlasning.klar`** till uppladdaren när posten blir `klar`. Ämnesraden är
  "G1-2511 är inlagd i Stamboken (ärende 12)", "Dina kaniner är inlagda i Stamboken
  (ärende 12)" eller "Ditt inskick är klart (ärende 12)", och mejlet listar kaninernas nummer
  och länkar till `/stamboken/inskick`. Öppnas posten igen innan mejlet gått stoppas det; blir
  en öppnad post klar igen går ett nytt mejl. En mejlad post har ingen uppladdare: mejlet går
  då till avsändarens adress, utan länken, men bara när Gmail har godkänt avsändaren
  (`sender_authenticated`). Det gäller också de två mejlen nedan.
- **`inlasning.kvitto`** till avsändaren av ett mejl med bilder: "Vi har fått 2 bilder.
  Genbanksansvarig lägger in dem." med ämnesraden "Vi har fått dina bilder (ärende 12)". Bara
  när Gmail har godkänt avsändarens domän (SPF eller DKIM), och högst ett per avsändare och dygn.
- **`inlasning.fraga`** till besättningens innehavare, se [Fråga uppfödaren](#fråga-uppfödaren).
- **`inlasning.ofullstandig`** till uppladdaren, eller till avsändarens adress för en mejlad post,
  när posten markeras `ofullstandig`. Ämnesraden är "Något saknas i ditt inskick (ärende 12)", och
  mejlet har handläggarens anteckning och datumet då posten tas bort (se [Gallring](#gallring)).
  Raden i mejlkön har bara postens och händelsens id; anteckningen läses ur händelsen när mejlet går,
  och är den gallrad går mejlet utan den. Mejlet stoppas om posten inte längre är `ofullstandig`.
- **`inlasning.paminnelse`** till samma mottagare, en gång, när posten fortfarande är `ofullstandig`
  11 månader efter att den kom in: "Påminnelse: något saknas i ditt inskick (ärende 12)", med samma
  anteckning, om den finns kvar, och datum. Nattjobbet `inbox_purge` köar det.
- **`notis.sammandrag`** kl. 07 varje dag till var och en som har olästa notiser som inget
  sammandrag tagit med och som inte stängt av mejlet. Det listar de olästa notiserna med
  ärendenummer och länkar till `/stamboken/inkorg`. Notiser av typen `klar` tas aldrig med:
  de har sitt eget mejl.

Gränssnittet ska därför ha Mina inskick på `/stamboken/inskick` och kön på `/stamboken/inkorg`.

## Tolkning

Fotot av ett intyg kan läsas av en bildmodell på servern, och handläggaren får ett förslag i
formuläret. Förslaget är bara ifyllda fält: inget sparas förrän handläggaren klickar Spara.

**Gången.**

- Ett nytt dokument av typen `intyg` väntar (`vantar`) när tolkningen är på, liksom ett dokument
  som byter typ till `intyg` och ett som får "Tolka igen".
- Schemaläggarens jobb `inbox_interpret` tar varje minut det äldsta väntande intyget i en öppen
  post, om inget sparats från det: ett dokument per körning. Fotot vrids som handläggaren vridit
  det, skalas ned till högst 2 000 bildpunkter på längsta sidan och förstärks (grön kanal, delad
  med bakgrunden, sträckt kontrast). Ingen databastransaktion eller -anslutning hålls medan
  modellen läser.
- Svaret hålls först mot schemat: okända nycklar tas bort, ett värde av fel typ räknas som saknat,
  en text kortas till 200 tecken och förlorar NUL-tecken. Det sparas sedan i `interpretation`,
  förslaget i `proposal`, tolkaren i `interpreter` och tiden i `interpreted_at`. Ett dokument får två försök, sedan är det `misslyckad`.
- Vrids, köas om eller ändras dokumentet medan modellen läser kastas svaret, och dokumentet
  väntar kvar.

**Kontrollerna** (`app/utils/inbox_proposal.py`). Modellen gissar hellre än lämnar ett fält tomt,
så hur säkert ett fält är avgörs av kontrollerna mot registret, aldrig av modellen:

1. Nummer, datum och antal normaliseras: nummer med och utan mellanslag och bokstav, datum som
   ÅÅMMDD, D/M-ÅÅ och ÅÅÅÅ-MM-DD, "st" i antal. En bokstav läst som siffra (S för 5, O för 0, l för
   1) ger aldrig `läst`.
2. Bara postens genbank söks: kaniner byter aldrig genbank.
3. En förälder är bekräftad när numret finns och förälderns egna föräldrar i registret stämmer
   med intyget, minst en av dem och ingen emot. Fel kön eller ett annat namn i registret gör
   föräldern osäker. Kullsyskon har samma föräldrar och födelsedatum, och en felläst siffra landar
   på ett av dem: en förälder med ett kullsyskon av samma kön är bekräftad bara när namnet på
   intyget är dess eget. Far- och morföräldrar föreslås bara under en bekräftad förälder. Står något
   annat på intyget markeras hela grenen, eftersom det lika gärna kan vara föräldern som är fel
   läst.
4. Ett nummer ett tecken fel ger registrets nummer som `härlett`, om bara en kanin passar.
5. Kaninens eget nummer: årssiffrorna mot födelsedatumet och numret mot kullen (samma kontroll
   som pappersnumret vid registreringen), och intygsnumret ska vara ledigt.
6. Där intyget och registret skiljer sig blir fältet `avviker`, med båda värdena. Förslaget
   väljer aldrig.

Ett värde som är överstruket eller rättat på intyget är alltid `osäker`. Finns kaninen redan i
Stamboken prövas den på samma sätt: föräldrarna mot registret, kön och namn, och namnet när kaninen
har ett kullsyskon av samma kön. Ett annat födelsedatum än kullens gör den `avviker`, utan värde.
Har den digitalt intyg och går allt igenom blir förslaget bara "finns redan med digitalt intyg". Ger tolkningen inte två
bekräftade föräldrar hjälper registret: en förälder som hittats, eller uppladdarens besättning när
ingen förälder gick att läsa, ger sina kullar. En enda kull född det lästa datumet fyller i mor och
far som `härlett`; annars listas kullarna i `checks`.

**Inställningar** (`.docker/api-variables.env`):

| Variabel | Värde | Standard |
|---|---|---|
| `INLASNING_TOLKARE` | `av` (ingen tolkning) eller `gemma` (Gemma i Ollama) | `av` |
| `INLASNING_MODELL` | modellens namn i Ollama | `gemma4` |
| `OLLAMA_URL` | Ollama-servern | `http://ollama:11434` |

**Driften.** Modellen körs i tjänsten `ollama` i `docker-compose.production.yml` och
`docker-compose.local-production.yml`. Den startar bara med profilen `tolkning`, så varken en vanlig
`up`, e2e-stacken eller pytest-stacken startar den. Tjänsten publicerar ingen port: bara `api` når
den, på `http://ollama:11434`. Den får högst 6 processorer, laddar ur modellen efter fem minuter
utan arbete (`OLLAMA_KEEP_ALIVE=5m`) och sparar modellerna i volymen `ollama_models`. Att slå på
tolkningen:

1. Starta tjänsten: `docker compose -f docker-compose.production.yml --profile tolkning up -d ollama`.
2. Hämta modellen en gång: `docker compose -f docker-compose.production.yml exec ollama ollama pull gemma4`.
3. Sätt `INLASNING_TOLKARE=gemma` i `.docker/api-variables.env` och starta om `api`.

Medan modellen läser behöver Ollama omkring 8,5 GB minne, utöver resten av stacken; mät med
`docker stats` att allt ryms innan tolkningen slås på. Ett foto tar minuter utan grafikkort, så
kön tolkas i bakgrunden och förslaget är bara handläggarens.

Med `av` kommer dokumenten in med `interpretation_status: "av"`, och kön fungerar som utan
tolkning. Ett okänt värde räknas som `av`. Tolkaren är ett gränssnitt, `interpret(bild, schema) ->
dict` i `app/utils/inbox_interpreter.py`, och en andra tolkare läggs till i `INTERPRETERS`. En
tolkare som skickar foton från servern kräver styrelsens beslut och ett avtal först.

## Gallring

Nattjobbet `inbox_purge` (kl. 03:45 i schemaläggarens ledare, `app/utils/inbox_purge.py`) gallrar kön.
Varje regel körs för sig, så att en regel som fallerar inte hoppar över de andra, och en regel som körs
igen ändrar ingenting. En månad är 365,25/12 dagar avrundat uppåt till hela dagar, som i
kommandologgen: 12 månader är 366 dagar och 13 månader 396.

| Vad | Gallras |
|---|---|
| Originalet till ett intyg eller bevis (`doc_type` `intyg`, `bevis`) | `INLASNING_ORIGINAL_MANADER` månader (standard 12) efter att posten kom in, i alla lägen |
| Bevisets original | också när kaninen sålts vidare: en senare `TRANSFER` från köparens besättning som inte är makulerad. Försäljningens rad i besättningshistoriken står kvar |
| Postens text: `message` och `text`, `note` och `not_saved` i händelserna | samtidigt som originalen, för en post som har dokument. Händelserna står kvar med typ, tid och person |
| Händelsen `oppnad` | 13 månader efter händelsen |
| Ett stängt meddelande (`kind: "meddelande"`) utan dokument | 13 månader efter stängningen |
| En post i läget `skrap` | 30 dagar efter stängningen |
| En post i läget `ofullstandig` | 12 månader efter att den kom in eller efter avsändarens senaste svar på den; mejl när den markeras och efter 11 månader (se [Mejl](#mejl)) |
| `sender_address` på en stängd post | när inget mejl till avsändaren väntar, senast 30 dagar efter stängningen, också när Gmail-läsningen är avstängd |
| `gmail_processed` | 60 dagar |
| Kopian på kaninen och spåret i `inbox_operation` | aldrig |

- En post raderas med sina dokument, händelser, notiser och original, och mejlkön glömmer avsändarens
  adress (`forget_recipient("inbox_sender", id)`). En post där något dokument har lagts på en kanin (en
  kopia, en registrering, en försäljning, eller någon skrivning som har en rad i `inbox_operation`)
  raderas aldrig, så att spåret "inlagd från foto av" behåller sitt dokument. När en sådan post skulle
  ha raderats gallras i stället alla dess original och dess text.
- Originalen till andra dokumenttyper (`arsblankett`, `annat`) gallras bara med sin post.
- `original_path` släpps i databasen innan filen tas bort, och bara filer direkt i `inkorg/original/`
  under `PRIVATE_UPLOAD_FOLDER` tas bort. Loggen visar antal, aldrig namn eller sökvägar.
- En fil direkt i `inkorg/original/` eller `inkorg/kopia/` som ingen rad pekar på och som är äldre än
  ett dygn tas bort av nattjobbet: en borttagning som misslyckades efter commit, ett inskick som
  rullades tillbaka eller en halvskriven fil. Ett dygn, så att ett inskick som pågår aldrig rörs.
- När originalet är borta har dokumentet `has_original: false`, `…/original` svarar 404 och kopian kan
  inte göras om. Kopian på kaninen visas som förut. Tolkningens svar (`interpretation`) och förslaget
  (`proposal`) är en avskrift av fotot och raderas med originalet, också vid radering på begäran.

**Inställning** (`.docker/api-variables.env`): `INLASNING_ORIGINAL_MANADER`, hela månader, minst 1,
standard 12.

### En person raderas

När en person anonymiseras i matrikeln (`anonymize_person`) raderas originalen till de dokument där
personen är sparad som säljare eller köpare, och texten i deras poster. Säljaren är innehavaren av
kaninens besättning när ett intyg sparas, och av säljarens besättning vid en försäljning; köparen är
innehavaren av köparens besättning vid en försäljning till en medlem. Innehavaren är medlemskapets
huvudmedlem i matrikeln. Finns en kopia är den det enda som blir kvar, med säljar- och köparblocket
täckt.

Det personen själv har skickat in raderas också: poster där personen är den matchade avsändaren av ett
mejl (`member`) och poster som personens konto har laddat upp. En sådan post som inte har lagt något på
en kanin raderas med sina filer. En post som har det står kvar utan original, text och
`sender_address`, och mejl till avsändaren som ännu inte har gått stoppas (`cancelled`), och mejlkön
glömmer adressen.

### `POST /api/v2/inkorg/{id}/dokument/{dok}/radera-original`

Samma sak för ett dokument på begäran, till exempel när en köpare utanför föreningen ber om det.
Originalet raderas, postens text också, och händelsen `original_raderat` loggas. Ett nytt anrop loggas
igen men har inget mer att radera.

**Vem:** genbanksansvarig för postens genbank och admin (en post utan genbank: alla
genbanksansvariga), i alla lägen.

**Svar 200:** `{"item": <post i listform>, "document": <dokument>}`.

**Fel:** 403 för en hjälpare och för den som inte arbetar i kön; 404 när posten inte finns eller
dokumentet inte hör till den.

## Gränser och sådant gränssnittet behöver veta

- Uppladdningen tar emot högst 10 filer à 10 MB i en begäran. Resten av API:t tar högst 11 MB.
  nginx tar i dag emot högst 10 MB per begäran på de publika värdnamnen, så ett större inskick
  måste antingen få en egen gräns i nginx eller skickas som flera inskick.
- Telefonens filväljare: `<input type="file" accept="image/*,application/pdf" multiple>` ger både
  kamera och bildbibliotek.
- Bilderna kräver inloggningens cookie. Använd dem som `src` i samma ursprung, eller hämta dem
  genom servern.
- Ordlistans termer gäller i gränssnittet: "Uppfödare", "Genbanksansvarig", "Pappersintyg",
  "Intygsnummer". Endpointen heter `…/overlat`, men i gränssnittet är det en försäljning.
