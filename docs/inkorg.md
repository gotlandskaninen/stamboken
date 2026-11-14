# Inläsningskön (inkorgen): API

Inläsningskön är en gemensam inkorg i Stamboken. En medlem fotograferar sina pappersintyg och
laddar upp fotona, och den som arbetar i kön tar posten, lägger in kaninerna och lägger en
maskerad kopia av intyget på kaninen. Det här dokumentet beskriver Flask-API:t som gränssnittet
bygger på: varje endpoint, vem som får anropa den, vad den tar emot och svarar, och lägena en
post går igenom. Reglerna finns i `app/utils/inbox.py` och endpointsen i `app/blueprints/inbox.py`.

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
16. [Mina inskick](#mina-inskick)
17. [Notiser](#notiser)
18. [Mejl](#mejl)
19. [Gränser och sådant gränssnittet behöver veta](#gränser-och-sådant-gränssnittet-behöver-veta)

## Begrepp

- **Post** (`item`): det som kom in i ett svep, i dag en uppladdning. Postens id visas som
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
| `vantar_uppfodare` | en fråga till uppfödaren är skickad (en senare del, kan inte nås i dag) | ja |
| `vantar_foralder` | ett intyg kan inte sparas förrän en förälder finns | ja |
| `hos_genbanksansvarig` | lämnad till genbanksansvarig för korrigering eller beslut | nej |
| `ofullstandig` | något saknas; handläggaren har skrivit vad | ja |
| `klar` | alla dokument är klara eller avfärdade | (den sista) |
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
| `vantar_foralder` | `…/lage`; något dokument måste ha `waiting_for` | `tagen` | handläggaren |
| `hos_genbanksansvarig` | `…/lage`; handläggaren tas bort | `tagen` | handläggaren |
| `ofullstandig` | `…/lage` med `note` (vad som saknas) | `tagen` | handläggaren |
| `dubblett` | `…/lage` med `duplicate_of` | `tagen`, `vantar_uppfodare`, `vantar_foralder`, `ofullstandig` | handläggaren |
| `skrap` | `…/lage` | `tagen`, `vantar_uppfodare`, `vantar_foralder`, `ofullstandig` | handläggaren |
| `klar` | det sista dokumentet blir klart eller avfärdat | alla öppna lägen | systemet |

Allt annat nekas med 409. `ny`, `klar` och `vantar_uppfodare` kan inte sättas med `…/lage` (400).

## Arbetsgången

1. Ta posten (`…/ta`), eller få den tilldelad.
2. Gå igenom dokumenten: vrid dem rätt och ange typ och format (`PATCH …/dokument/{dok}`).
3. Ett intyg: spara det intyget visar (`…/spara`), en ny kanin eller pappersintyget på en kanin
   som finns. Visar intyget också en försäljning, registrera den nu (`…/overlat`): ett dokument som
   är klart går inte att spara eller sälja från.
4. Bekräfta maskningen (`…/maskning`). Kopian läggs på kaninen och dokumentet blir klart.
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
endpoint. Gemensamt för alla endpoints:

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
  "has_message": true,
  "documents": 2,
  "documents_done": 1
}
```

- `kind`: `upload` i dag; `mail`, `meddelande`, `kontroll` och `avisering` kommer med senare delar.
- `herd`: besättningsnumret uppladdaren valde.
- `sender` och `assigned_to`: `null` eller `{id, name}`. `name` är kontots fullständiga namn, och
  `"Konto <id>"` när namnet saknas. E-postadressen visas aldrig.
- `missing_proof`: en försäljning har registrerats utan överlåtelsebevis ("bevis saknas").
- `stalled`: sätts av en senare del (en post som stått still i 14 dagar); alltid `false` i dag.
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

`sender_address` gäller mejlade poster (en senare del) och är `null` för uppladdningar.

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
- `interpretation_status` och `proposal`: bildtolkningen är en senare del. I dag är
  `interpretation_status` alltid `"av"` och `proposal` alltid `null`; handläggaren skriver av
  fälten själv.
- `individual`: kaninens nummer när dokumentet är sparat, annars `null`.
- `herd_tracking_id`: försäljningens rad i besättningshistoriken, för ett bevis.
- `has_copy`: kopian finns.

### Händelser

`events` är postens historik, äldst först. `user` är `null` för systemets händelser.

| `kind` | `detail` |
|---|---|
| `inkommen` | `{"documents": 2}` |
| `oppnad` | `null`; någon i kön öppnade posten |
| `tagen` | `null` |
| `overtagen` | `{"from_user": 7}` |
| `tilldelad` | `{"to_user": 7, "from_user": null}` |
| `lage` | `{"from": "tagen", "to": "ofullstandig", "note": "Pappersintyget saknas"}`; `note` bara när den gavs, `duplicate_of` vid `dubblett` |
| `dokument` | `{"document": 31, "fields": ["mask_rects", "rotation"]}` |
| `sparad` | `{"document": 31, "action": "ny_kanin" \| "pappersintyg", "individual": "G1-2511"}`, eller vid en försäljning `{"document": 31, "action": "overlatelse", "individual": "G1-2111", "herd": "G2", "missing_proof": true}` |
| `kopia` | `{"document": 31, "rects": 1}` |
| `original_visat` | `{"document": 31}` |
| `foralder_inlagd` | `{"individual": "G1-2431"}` |

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
{"items": [ { "…": "poster i listform" } ], "total": 17, "counts": {"ny": 9, "tagen": 6, "klar": 2}}
```

`total` är antalet poster med alla filter. `counts` är antalet per läge med alla filter utom
`state`, så att flikar per läge kan visa sina antal. Ett läge utan poster saknas i `counts`.

**Fel:** 400 för ett okänt läge eller ett id som inte är ett heltal.

### `GET /api/v2/inkorg/{id}`

Posten i detaljform med dokument och historik. Varje anrop loggas som händelsen `oppnad` (vem
och när), och anroparens notiser om posten blir lästa.

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
| `state` | `tagen`, `vantar_foralder`, `hos_genbanksansvarig`, `ofullstandig`, `dubblett` eller `skrap` |
| `note` | text, högst 2000 tecken; krävs för `ofullstandig`, valfri annars; sparas i händelsen |
| `duplicate_of` | krävs för `dubblett`: id för den andra posten |

Reglerna står i [Lägen](#lägen). Vid `hos_genbanksansvarig` tas handläggaren bort och
genbanksansvariga i postens genbank får notisen `lamnad`. Öppnar genbanksansvarig eller admin en
stängd post blir hen handläggare.

**Svar 200:** posten i listform.

**Fel:** 400 för ett okänt läge, `ofullstandig` utan `note`, `dubblett` utan en annan post,
`vantar_foralder` när inget dokument har `waiting_for`; 403 när någon annan än genbanksansvarig
eller admin öppnar en stängd post; 409 när anroparen inte är handläggare eller övergången inte
finns.

## Dokument

### `PATCH /api/v2/inkorg/{id}/dokument/{dok}`

**Vem:** handläggaren (posten i ett läge med handläggare). Skicka bara fälten som ändras.

```json
{"doc_type": "intyg", "cert_format": "handskrivet", "rotation": 90, "mask_rects": [{"x": 0, "y": 0.66, "w": 1, "h": 0.34}]}
```

| Fält | |
|---|---|
| `doc_type` | `intyg`, `bevis`, `arsblankett` eller `annat` |
| `cert_format` | `null` eller ett av formaten under [Dokument](#dokument) i objekten |
| `rotation` | 0, 90, 180 eller 270 (grader medurs) |
| `mask_rects` | `null` eller en lista med högst 20 rektanglar, se [Maskning](#maskning-och-kopian-på-kaninen) |
| `waiting_for` | `null`, `[]` eller en lista med ett eller två individnummer (till exempel `G1-2431`) som inte finns i Stamboken än |
| `dismissed` | `true` avfärdar dokumentet (klart utan att något sparas, till exempel ett foto som inte är ett intyg); `false` ångrar det, om inget har sparats från dokumentet |

Ändras `rotation` eller `mask_rects` på ett dokument som redan har en kopia görs kopian om. Blir
det sista dokumentet avfärdat blir posten `klar`.

**Svar 200:** `{"item": <post i listform>, "document": <dokument>}`.

**Fel:** 400 för ett okänt fält, ett ogiltigt värde, ett nummer som inte går att läsa eller som
redan finns i Stamboken (`"G1-2111 finns redan i Stamboken."`); 404 när dokumentet inte hör till
posten; 409 när anroparen inte är handläggare.

**Väntar på förälder.** Saknas en förälder i Stamboken: ange förälderns nummer i `waiting_for`
och byt läge till `vantar_foralder`. När en kanin med det numret läggs in, var som helst i
Stamboken, tas numret bort ur `waiting_for` i samma transaktion. Väntar posten inte längre på
någon förälder blir den `tagen` igen, och handläggaren får notisen `foralder_inlagd` (har posten
ingen handläggare får genbanksansvariga den).

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
409 `number_conflict` som ovan.

**För båda:** 409 när posten inte är anroparens, inte är `tagen`, har `ref_type`, eller
dokumentet inte är ett osparat intyg; 400 för okänd `action`. Efter sparandet har dokumentet
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
får `missing_proof: true` ("bevis saknas").

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
| 409 | som för `…/spara`; eller besättningshistoriken skulle bli motsägelsefull (med `rows`) |

## Maskning och kopian på kaninen

Kopian på kaninen är originalet vridet `rotation` grader medurs, med svarta rektanglar över
säljarens och köparens uppgifter. Den ska inte visa andra personuppgifter än uppfödarens.

**Rektanglarna** anges i bråkdelar av bilden *efter* vridningen: `x` och `y` är det övre vänstra
hörnet, `w` och `h` bredd och höjd, alla mellan 0 och 1, och rektangeln måste ligga inom bilden.
`{"x": 0, "y": 0.5, "w": 1, "h": 0.5}` täcker den nedre halvan. Gränssnittet kan förhandsvisa
kopian genom att rita rektanglarna över det vridna originalet.

### `POST /api/v2/inkorg/{id}/dokument/{dok}/maskning`

Bekräftar maskningen och gör kopian.

```json
{"mask_rects": [{"x": 0, "y": 0.6667, "w": 1, "h": 0.3333}]}
```

`mask_rects` kan utelämnas om de redan är sparade på dokumentet. En tom lista bekräftar att
intyget inte visar någon säljare eller köpare.

**Vem:** handläggaren. Dokumentet måste vara ett sparat intyg (`individual` satt).

Dokumentet blir klart (`status: "klar"`, `has_copy: true`). Är alla dokument i posten klara
eller avfärdade blir posten `klar`, uppladdaren får notisen `klar` och mejlet `inlasning.klar`.
Kopian görs om från originalet varje gång rektanglarna eller vridningen ändras.

**Svar 200:** `{"item": <post>, "document": <dokument>}`.

**Fel:** 400 när `mask_rects` saknas både i anropet och på dokumentet, eller är ogiltiga; 409 när
dokumentet inte är ett sparat intyg eller anroparen inte är handläggare.

## Bilderna

Båda svarar med `image/jpeg` och `Cache-Control: no-store, private`. Bilderna ligger utanför den
publika uppladdningskatalogen och nås bara genom de här endpointsen.

### `GET /api/v2/inkorg/{id}/dokument/{dok}/original`

Originalet. **Vem:** de som arbetar i kön. Varje hämtning loggas som händelsen `original_visat`.

### `GET /api/v2/individual/{nummer}/paper-certificate`

Kaninens pappersintyg: den senaste kopian som gjorts från ett intyg för kaninen. **Vem:** den som
får hämta kaninens intyg i dag, alltså ägaren, uppfödaren (ursprungsbesättningen),
genbanksansvarig och admin. En genbankshjälpare ser originalet i kön men inte den här.

**Fel:** 403 för den som inte får se intyget; 404 när kaninen inte finns eller inte är
tillgänglig, eller saknar ett inläst pappersintyg (`Kaninen har inget inläst pappersintyg.`).
Gränssnittet kan använda 404 för att dölja "Pappersintyg" på kaninens sida.

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
| `klar` | Ditt inskick är klart | uppladdaren; länka till Mina inskick, inte till kön |

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
  en öppnad post klar igen går ett nytt mejl.
- **`notis.sammandrag`** kl. 07 varje dag till var och en som har olästa notiser som inget
  sammandrag tagit med och som inte stängt av mejlet. Det listar de olästa notiserna med
  ärendenummer och länkar till `/stamboken/inkorg`. Notiser av typen `klar` tas aldrig med:
  de har sitt eget mejl.

Gränssnittet ska därför ha Mina inskick på `/stamboken/inskick` och kön på `/stamboken/inkorg`.

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
