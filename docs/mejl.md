# Utgående e-post (mejlkön)

Allt e-post som Flask-API:et skickar går genom en kö i Postgres. En funktion
lägger mejlet i kön i samma transaktion som skrivningen det hör till, och
schemaläggaren skickar det efter commit. Koden finns i `app/utils/mail.py`,
mallarna i `app/templates/email/` och statusvyns API i
`app/blueprints/mail.py`.

## Regeln: köa i transaktionen, skicka efter commit

```python
from utils.database import DB_PROXY
from utils.mail import enqueue_mail

with DB_PROXY.atomic():
    application = MemberApplication.create(...)
    enqueue_mail(
        "ansokan.mottagen",
        "application",
        application.id,
        {"application_id": application.id},
        ref=("member_application", application.id),
    )
```

- `enqueue_mail` lägger raden i samma transaktion som anroparen. En rollback,
  också av ett nästlat `atomic()`, tar bort mejlet med resten.
- En webbförfrågan skickar aldrig själv. Jobbet `mail_send` körs var 30:e
  sekund i schemaläggarens ledare och tar bara committade rader, så ett fel i
  utskicket kan inte fälla den skrivning som köade mejlet.
- Kod som bara provar eller visar en förhandsgranskning köar inget.
- `dedupe_key` gör schemalagda utskick idempotenta: finns nyckeln redan blir
  det ingen ny rad, och anropet returnerar `None`.
- `not_before` fördröjer ett mejl. `herd` och `genebank` används för filtren i
  statusvyn, och `genebank` styr vilka genbanksansvariga som ser raden.

## Vad en rad får innehålla

En rad i kön har mallens namn, parametrar och var mottagaren finns
(`recipient_kind`, `recipient_id`). Adresser, färdiga texter och fungerande
länkar hamnar aldrig där: allt sådant tas fram först vid utskicket, och
mejlet går då till den adress som är aktuell just då.

- `params` får bara innehålla heltal (id:n), booleska flaggor och `None`.
  Allt annat, också strängar, ger `ValueError`. Fritext ligger i funktionens
  egen tabell och hänvisas med id.
- Innan `last_error` eller ett försöks `detail` sparas byts varje ord med
  `@` ut mot `<adress>`, eftersom SMTP-fel gärna citerar mottagaren.
- `address_hash` (HMAC med `LINK_SECRET`) visar vilken adress ett skickat mejl
  gick till, så att en studs kan kopplas till adressen. Jobb som raderar en
  mottagares rad anropar `forget_recipient(kind, id)`, som tömmer fältet och
  `dedupe_key` och avbryter mejl till mottagaren som inte har gått (`cancelled`,
  "mottagaren är raderad"). Ett mejl som håller på att byggas eller skickas
  just då förlorar sitt anspråk på raden, så sändaren skickar det inte och
  skriver inte tillbaka någon adresshash. Sändaren frågar efter anspråket när
  anslutningen till reläet är uppe, omedelbart före själva mejlet. Raderas
  mottagaren medan mejlet lämnas över till reläet går det ändå: det är redan
  på väg, som ett mejl som skickades sekunden innan.
- Den publika ansökan tar emot vilken adress som helst, så kvittot
  `ansokan.mottagen` går högst en gång per adress och dag: `dedupe_key` är
  adressens HMAC och datumet, aldrig adressen.
- Raderna raderas efter 396 dagar (`purge_old_mail`, nattjobbet kl. 03:30).

## Lägga till en mejltyp

1. Skriv mallen `app/templates/email/<typ>.txt` med blocken `subject` och
   `body`. Texten är ren text (UTF-8), på svenska, i du-form och kort. Foten
   `_fot.txt` läggs till automatiskt. Ämnesraden blir alltid en rad. Mallen
   får variabeln `base_url` (`HERDBOOK_HOST`) och det byggfunktionen ger.

   ```jinja
   {% block subject %}Vi har tagit emot din ansökan om medlemskap{% endblock %}

   {% block body %}
   Hej!

   Tack för din ansökan om medlemskap i Föreningen Gotlandskaninen.
   {% endblock %}
   ```

2. Registrera typen med en byggfunktion som tar `params` och returnerar
   mallens variabler. Returnerar den `None`, till exempel för att ansökan
   har tagits bort, stoppas mejlet med status `cancelled`. Kastar den
   `Later(tid, skäl)` läggs mejlet tillbaka i kön till den tiden, utan att
   räknas som ett försök.

   ```python
   from utils.mail import mail_kind

   @mail_kind("ansokan.mottagen", priority=1, category="T")
   def _application_received(params):
       found = MemberApplication.select().where(MemberApplication.id == params["application_id"]).exists()
       return {} if found else None
   ```

   Modulen med byggfunktionen måste importeras av appen, annars får mejlet
   status `cancelled` med felet "okänd mejltyp".

3. Köa mejlet med `enqueue_mail` i transaktionen som utlöser det.
4. Skriv ett test som köar, kör `send_pending` i läget `log` eller mot en
   fejkad SMTP-server och kontrollerar status och text
   (`app/tests/test_mail_queue.py` har en fejk).

**Prioritet:** 0 när användaren väntar eller mejlet är ett skydd, 1 för vanliga
mejl, 2 för massutskick. **Kategori:** `T` (transaktion) eller `N` (notis).

**Bilagor:** byggfunktionen kan returnera nyckeln `attachments` med en lista
av `(filnamn, mime-typ, bytes)`. Bilagan byggs när mejlet skickas. Nyckeln
`reply_to` sätter `Reply-To` till en annan adress än avsändarens.

## Mejltyper om medlemskap

- `ansokan.mottagen`, `ansokan.ny` och `ansokan.godkand` följer en ansökan om
  medlemskap: kvitto till den sökande, besked till matrikelansvariga och
  välkomst till den nya medlemmen.
- `medlemskap.tillagd` går till en person som någon annan har lagt in i ett
  medlemskap, alltså en familjemedlem eller skötare som huvudmedlemmen eller
  matrikelansvarig lägger till (`add_person`), när personen har en
  e-postadress. Det är informationen enligt dataskyddsförordningen artikel 14:
  vad som sparas, vem som lade in uppgifterna, länken `/dataskydd` och adressen
  att skriva till. En huvudmedlem får det inte, och inte heller den som kommer
  in med importen av matrikeln, som skriver sina rader själv. Får någon som
  `add_person` lade in en adress senare (`set_member_email`) köas mejlet då.
  Personen har en enda rad i kön, och den visar att mejlet har gått. En rad
  som aldrig nådde fram (`failed`, `bounced`, `cancelled` för att adressen
  saknades, eller som skickas till adressen som just byttes) köas igen när
  adressen ändras. Studsar mejlet efter att adressen har rättats köas det
  igen till den nya adressen. En rad som har gått eller som stoppats i
  statusvyn köas inte igen. Har personen lämnat medlemskapet eller blivit huvudmedlem när
  mejlet ska gå blir det `cancelled`. Huvudmedlemmen väljer adressen, så
  mejlet får inte bli ett sätt att överösa någon. Ett medlemskaps mejl sprids
  över dygnen, högst tio om dagen, när de köas. En adress får högst tre om
  dagen, räknat på mejl som har gått när nästa ska skickas, och ett mejl över
  gränsen väntar tills det äldsta av dem är ett dygn gammalt. Inget mejl
  stryks för en gräns.
- `konto.kod` (prioritet 0) har en engångskod. Hittills finns bara texten för
  en ny adress (`purpose = ny_adress`): mottagaren har bett om att byta
  e-postadress, och mejlet har koden men ingen länk. En rad för inloggning
  stoppas tills inloggningssidan finns.
- `kontakt.epost_besked` (prioritet 0) går till adressen som byts ut när en
  inloggningsadress byts, och under en väntan också till den första tidigare
  adressen: att adressen är bytt och av vem (medlemmen själv, matrikelansvarig
  eller någon annan). Den som inte känner igen bytet svarar på mejlet, som
  hamnar i brevlådan som inläsningskön läser. Ingen adress står i mejlet.

## Engångskoder och inloggningsadresser

Koden finns i `app/utils/login_code.py` och `set_member_email` i
`app/utils/matrikel.py`.

- **Koden** är åtta siffror, en sträng med inledande nollor, och visas som
  `4827 1953`. Raden i `login_code` har ett slumptal; koden är
  HMAC-SHA256(`LINK_SECRET`, `"code:<värdnamn>:<rad-id>:<slumptal>"`) modulo
  10^8 och lagras aldrig. Inmatningen bortser från mellanslag och bindestreck.
- **Tio minuter, en gång, tre försök.** Försöket räknas upp i samma `UPDATE`
  som kontrollerar gränsen och sparas för sig, före jämförelsen. Koden
  förbrukas med en enda `UPDATE`, så av två samtidiga lyckas högst en, och
  försöket räknas då tillbaka.
- **Webbläsaren:** raden sparar en hash av en hemlighet som bara webbläsaren som
  bad om koden har. Vid byte av adress ligger hemligheten i sessionen
  (`login_request`). En ny begäran om en ny adress byter den och gör alla
  medlemmens tidigare oanvända koder för en ny adress ogiltiga, oavsett
  webbläsare; för inloggning gör en annans begäran aldrig medlemmens kod
  ogiltig. Utloggning och **Avbryt**
  (`DELETE /api/v2/members/me/contact/kod`) gör sessionens väntande kod
  ogiltig. Bytet görs bara om sessionen fortfarande gäller när kontots rad är
  låst. Den nya adressen prövas med samma kontroll som sändaren använder, så
  en adress som inget mejl kan gå till får samma fel som en ogiltig adress och
  kostar ingen kod. Demon vägrar bytet ("E-postadressen kan inte bytas i
  testmiljön.") och sparar resten, eftersom kontots märke aldrig byts där.
- **Gränser:** fem koder per person och dygn, 120 koder i timmen sammanlagt,
  och efter 50 felaktiga koder på en timme tas inga koder emot eller skickas
  förrän de har åldrats ut. Felen räknas på rader skapade den senaste timmen
  och tio minuter till, så ett fel räknas minst en timme. Statusvyn visar då
  `kodinloggning_stangd`.
- **Utan `LINK_SECRET`, och i produktion med `MAIL_MODE=log`,** vägrar
  koderna (503). I läget `log` utanför produktion står koden i loggen.
- **Gallring:** en kod som har gått ut tappar den nya adressen inom en minut
  (`login_code_expire`), och raderna raderas efter ett dygn i nattjobbet
  kl. 03:30, i samma transaktion som mejlkön glömmer vart deras mejl gick.
  Demokopian får inga rader ur `login_code` eller `member_previous_address`.
- **En adress, en person.** En adress som kan ta emot en kod hör till en
  person: `Member.email` och en tidigare adress som fortfarande gäller, för en
  person som inte är avslutad och är huvudmedlem eller har ett konto.
  `reserve_login_address` kontrollerar det under ett lås på adressen i varje
  skrivning som kan skapa en sådan adress (ändrad adress, nytt medlemskap, ny
  huvudmedlem, byte av huvudmedlem, koppling av konto, godkänd ansökan och
  importen). Blir en person innehavare igen (koppling av konto, byte av
  huvudmedlem) reserveras också hennes tidigare adresser som fortfarande
  gäller, med låsen i en fast ordning. Matrikelansvarig och den som godkänner en
  ansökan får 409
  "Adressen används redan av en annan medlem"; medlemmen själv får aldrig det
  beskedet. Två personer med samma adress räknas i nattjobbet och visas i
  statusvyn som `adresskrock`. En tom sträng är ingen adress.
- **Sju dagar.** All skrivning av en befintlig persons `Member.email` går
  genom `set_member_email`, utom anonymiseringen, som tömmer adressen själv och
  raderar personens tidigare adresser och kodrader. Byter medlemmen själv
  adress (efter en kod till den nya) gäller den gamla för inloggning i sju
  dagar till och den nya genast. Byte gjort av någon annan (gamla adressen sju
  dagar till, den nya först efter dem) finns i funktionen men har ingen
  anropare än; det kommer senare, med blankettvägen. Matrikelansvarigs byte
  gäller genast, och den gamla slutar gälla. Under en väntan ligger den första
  tidigare adressen fast: ett nytt byte startar om klockan, med låset på den
  gamla adressen, men gör aldrig adressen däremellan giltig; den får en rad som
  aldrig gäller för inloggning, så att beskedet har en mottagare. Ett byte
  tillbaka avslutar väntan. Varje byte gör personens oanvända koder ogiltiga
  och avslutar kontots sessioner. Raderna i `member_previous_address` raderas
  två dygn efter att adressen slutat gälla, och vid anonymisering.

## Mejltypen om Tyck till

`tyck_till.inskick` går till föreningens funktionsadress (mottagartypen
`tyck_till`, adressen ur `TYCK_TILL_MOTTAGARE`) när någon har skickat en
synpunkt med knappen "Tyck till" ([tyck-till.md](tyck-till.md)). Raden
har bara heltal (inskickets UUID som `UUID.int`, issuens nummer, vilket repo och
om issuen hamnade på tavlan). Texten, sidan, bilderna och kontaktuppgifterna
läses ur inskickets mapp när mejlet byggs, och finns mappen inte längre blir
mejlet `cancelled`. Bilderna är bilagor, och `Reply-To` är den adress medlemmen
vill ha svar till.

## Mottagare

`recipient_kind` säger var adressen finns. Inbyggda: `member`
(`Member.email`), `user` (`hbuser.email`), `application` (ansökan om
medlemskap), `inbox_sender` (avsändaren av en mejlad post i
inläsningskön, [inkorg-gmail.md](inkorg-gmail.md)), `login_code` (adressen en
kod går till, ingen när koden är använd, ogiltig eller för gammal),
`member_previous_address` (en tidigare adress) och `tyck_till`
(funktionsadressen för Tyck till, alltid samma). En ny sort registreras med
`@recipient_kind("<namn>")` och en funktion som tar id:t och returnerar
`Recipient(address, label)` eller `None`. `label` är det statusvyn visar, ett
namn, aldrig adressen. Saknas mottagaren, adressen eller
sorten blir mejlet `cancelled` med ett felmeddelande som säger varför.

## Länkar i mejl

`link_token(syfte, rad_id)` ger en länkkod `<rad_id>.<mac>`, där `mac` är
base64url av HMAC-SHA256(`LINK_SECRET`, `"link:<värdnamn>:<syfte>:<rad_id>"`),
avkortad till 128 bitar. Värdnamnet (ur `HERDBOOK_HOST`) binder länken till sin
miljö: demon är en kopia av produktionen med samma rad-id, och en länk från den
ena gäller inte i den andra, inte heller om de skulle dela `LINK_SECRET`. Ingen kod och ingen hash av den sparas; byggfunktionen räknar fram
koden när mejlet skickas, så en påminnelse kan skicka samma länk igen.
`verify_link(syfte, token)` ger rad-id:t om koden är äkta, annars `None`.
Funktionen som tar emot länken hämtar raden och kontrollerar själv
`expires_at` och `revoked_at`. Byts `LINK_SECRET` slutar alla skickade länkar
att fungera.

## Utskicksläge

| `MAIL_MODE` | Effekt |
|---|---|
| `log` (standard) | Ingen SMTP-anslutning. Raden får `logged`, och loggen visar typ, id och mottagarens hänvisning, med den färdiga texten, länkkoderna maskerade, när `FLASK_ENV` inte är `production`. |
| `allowlist` | `MAIL_ALLOWLIST` är en kommaseparerad lista med adresser och `@domän`. Mejl till något i listan skickas, med `[Demo]` och ett mellanslag först i ämnesraden; resten får `blocked`. |
| `live` | Skickar. |

Starten stoppas om `MAIL_MODE=live` och `DEMO_INSTANCE=true`, om
`LINK_SECRET` saknas när läget inte är `log`, eller om läget är okänt.
Samma kontroll görs vid varje körning av `send_pending`, som annars inte skickar.
Övriga inställningar: `SMTP_HOST`, `SMTP_PORT` och `MAIL_FROM`. Appen har
inget användarnamn eller lösenord för SMTP. Compose-filerna för dev och den
lokala produktionsstacken låser `MAIL_MODE=log`, också om `api-variables.env`
är en kopia av produktionens.

## Sändaren

- Varje körning stämplar `mail_sender.last_run_at`, också när kön är tom.
- En sändare tar en rad åt gången (`FOR UPDATE SKIP LOCKED`) och märker den
  med en ny `claim_token`. Resultatet skrivs med villkoret att märket är
  oförändrat. Två sändare får därför aldrig samma rad, och den som tappat en
  rad kan inte skriva över resultatet från den som tog den.
- Har en rad varit `sending` i över 10 minuter (sändaren dog) blir den
  `queued` igen.
- Precis före SMTP förnyar sändaren märket (`claimed_at` med villkoret att
  `claim_token` är oförändrad); har en annan sändare tagit raden under tiden
  skickas den inte. Hela samtalet med reläet för ett mejl, anslutningen
  inräknad, avbryts efter 120 sekunder. En rad kan därför inte tas över medan
  dess sändare fortfarande talar med reläet.
- Utskicket sker minst en gång, inte exakt en gång, i ett enda fall: reläet tog
  emot mejlet men statusen skrevs aldrig (svaret eller skrivningen gick
  förlorad), och raden skickas igen när den tas över. Därför handlar ett
  kvitto om en händelse som inte ändras, så att en dubblett säger samma sak.
- Högst 30 mejl per körning, över en SMTP-anslutning med STARTTLS (krävs) och
  60 sekunders tidsgräns per steg. Lägst prioritetsnummer först.
- `Message-ID` är `<mail-<id>.<16 hextecken HMAC>@<värdnamnet i HERDBOOK_HOST>>`,
  samma vid varje försök och olika per miljö.

| Svar | Klass | Följd |
|---|---|---|
| 250 | `sent` | `sent`, med `sent_at` och `address_hash` |
| 4xx vid RCPT eller DATA, avbruten anslutning eller annat fel under sändningen, fel när mejlet byggs | `temporary` | räknas; väntetiden före nästa försök växer från 1 min via 5 min, 30 min, 2 h och 6 h till 12 h, och det sjunde räknade felet ger `failed` |
| 5xx vid RCPT eller DATA, också 5.7.x (policy), och 552 (för stort) vid MAIL FROM | `permanent` | `failed` direkt |
| anslutningen nekas, ingen STARTTLS, EHLO nekas, 421, reläet nekar vår avsändare eller vår IP vid MAIL FROM, anslutningen bryts eller tar för lång tid för det andra mejlet i rad i samma körning | `systemic` | felet ligger hos reläet, inte hos mejlet: försöket räknas inte, sändaren vilar 5 minuter och raden väntar till en minut efter pausen, så att mejlen bakom den går först |

Ett avslag vid RCPT eller DATA gäller den mottagaren eller det mejlet, vilken
kod det än har. Ett relä som nekar alla mottagare (kvot, policy, vår IP)
skulle därför fälla mejlen ett i taget. Därför stoppas körningen efter tre
`permanent` i rad: sändaren vilar 5 minuter som vid `systemic`, statusvyn
visar larmet "Reläet tar inte emot e-post från servern", och de tre raderna
förblir `failed` ("Försök igen" skickar dem). Ett mejl som går fram nollställer
räkningen. Får samma rad `systemic` en tredje gång och annan post har gått fram
mellan gångerna, är felet mejlets eget och raden blir `failed`. "Försök igen"
börjar räkningen om.

## Studsar och statusvy

`record_bounce(message_id, diagnos)` markerar raden bakom en leveransrapport
som `bounced`, men bara om den är `sent`. Inläsningskön anropar den för varje
leveransrapport i brevlådan ([inkorg-gmail.md](inkorg-gmail.md)). Ett `Message-ID`
med en annan miljös värdnamn eller fel HMAC, eller en rad i någon annan status,
rör ingen rad, och funktionen returnerar `False`.

API:t under `/api/v2/mail` (admin ser allt, genbanksansvarig rader med sin
genbank):

- `GET /status?ref_type=…&ref_id=…`: senaste raden per typ för ett ärende.
- `GET /messages`: listan med filter (`status`, `kind`, `genebank_id`,
  `herd_id`, `from`, `to`, `limit`, `offset`) och larmen: reläet tar inte
  emot, kön står still (`last_run_at` äldre än 5 minuter), läget är `log` i
  produktion (ingen demo; raderna blir `logged` för gott), kodinloggningen är
  stängd (`kodinloggning_stangd`), en inloggningsadress hör till fler än en
  person (`adresskrock`), senaste lyckade utskick.
- `POST /messages/<id>/retry`: `failed`, `bounced` eller `logged` tillbaka till kön.
- `POST /messages/<id>/cancel`: stoppar ett köat mejl.
