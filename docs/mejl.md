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
  `dedupe_key`.
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
   har tagits bort, stoppas mejlet med status `cancelled`.

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
av `(filnamn, mime-typ, bytes)`. Bilagan byggs när mejlet skickas.

## Mottagare

`recipient_kind` säger var adressen finns. Inbyggda: `member`
(`Member.email`), `user` (`hbuser.email`), `application` (ansökan om
medlemskap), `inbox_sender` (avsändaren av en mejlad post i
inläsningskön, [inkorg-gmail.md](inkorg-gmail.md)) och `buyer_contact`
(köparen utanför föreningen, `BuyerContact.email`, i statusvyn
`Köpare <id>`). En ny sort registreras med
`@recipient_kind("<namn>")` och en funktion som tar id:t och returnerar
`Recipient(address, label)` eller `None`. `label` är det statusvyn visar, ett
namn, aldrig adressen. Saknas mottagaren, adressen eller
sorten blir mejlet `cancelled` med ett felmeddelande som säger varför.

## Länkar i mejl

`link_token(syfte, rad_id)` ger en länkkod `<rad_id>.<mac>`, där `mac` är
base64url av HMAC-SHA256(`LINK_SECRET`, `"<syfte>:<rad_id>"`), avkortad till
128 bitar. Ingen kod och ingen hash av den sparas; byggfunktionen räknar fram
koden när mejlet skickas, så en påminnelse kan skicka samma länk igen.
`verify_link(syfte, token)` ger rad-id:t om koden är äkta, annars `None`.
Funktionen som tar emot länken hämtar raden och kontrollerar själv
`expires_at` och `revoked_at`. Byts `LINK_SECRET` slutar alla skickade länkar
att fungera. Den första länken är [raderingslänken](#raderingslänken).

## Mejl till en köpare utanför föreningen

En köpare utanför föreningen (`BuyerContact`,
[ADR-0016](adr/0016-agarbyte-flytt-dag-0-och-berattigat-intresse.md)) kan få
två mejl. `utils/buyer_mail.py` köar dem i samma transaktion som köparen
skapas, från försäljningen (`record_herd_tracking`) och från en korrigering
som skriver in en ny köpare (`correct_herd_tracking`), och bara när köparen
har lämnat sin e-post. En korrigering som behåller köparen köar inget, och
`dedupe_key` (`<typ>:<köparens id>`) gör att samma köpare aldrig får samma
mejl två gånger. Är köparen raderad när mejlet ska gå blir det `cancelled`.

- **`kopare.information`** berättar vad föreningen sparar om köparen och
  varför, och till vilket datum namn och ort sparas: radens `purge_at` som
  svenskt datum. Mejlet har [raderingslänken](#raderingslänken). Har kaninen
  ett digitalt intyg ligger det som PDF, hämtat när mejlet går, på samma sätt
  som när intyget laddas ner; annars går mejlet utan bilaga och utan meningen
  om den. Går intyget inte att hämta räknas det som ett tillfälligt fel, och
  mejlet går inte utan bilagan. Utan `LINK_SECRET` kan mejlet inte byggas.
- **`kopare.medlemskap`** går när köparen har sagt ja till att föreningen
  hör av sig om medlemskap (`membership_optin_at`). Är ja:et gallrat när
  mejlet ska gå blir det `cancelled`.

### Raderingslänken

`<HERDBOOK_HOST>/kopare/ta-bort#<länkkod>`, med
`link_token("kopare_invandning", <köparens id>)`. Koden står efter `#`, så
webbläsaren skickar den aldrig till någon server, och ingen åtkomstlogg kan
få med den. Sidan tar koden ur adressfältet och historiken direkt och
raderar inget förrän köparen trycker på knappen, så att en förhandsvisning
av länken i mejlprogrammet inte raderar köparen. Knappen skickar koden i
kroppen:

```text
POST /api/v2/kopare/ta-bort
{"token": "<länkkod>"}
```

Ingen inloggning; högst 10 anrop i timmen från en IP-adress. En äkta kod
raderar köparen med samma funktion som när genbanksansvarig raderar
(`delete_buyer_contacts` med åtgärden `invandning` och utan användare):
bevisets original, adressen i mejlkön (`forget_recipient`) och en rad i
`audit_log` följer med.

| Svar | När |
|---|---|
| 200 `{"result": "removed"}` | köparen raderades nu |
| 200 `{"result": "already_removed"}` | koden är äkta men köparen finns inte längre |
| 404 med `detail` "Länken gäller inte längre. Skriv till `dataskydd@gotlandskaninen.se`." | allt annat: förfalskad, trasig eller saknad kod, eller en kod för ett annat syfte. Svaret är detsamma vilket id koden än nämner |
| 429 | för många anrop |

Både sidan och API:ts svar har `Cache-Control: no-store` och
`Referrer-Policy: no-referrer`. `app/tests/test_buyer_mail.py` kontrollerar
att koden inte hamnar i appens loggar eller i gunicorns åtkomstlogg.

## Utskicksläge

| `MAIL_MODE` | Effekt |
|---|---|
| `log` (standard) | Ingen SMTP-anslutning. Raden får `logged`, och loggen visar typ, id och mottagarens hänvisning, med den färdiga texten, länkkoderna maskerade, när `FLASK_ENV` inte är `production`. |
| `allowlist` | `MAIL_ALLOWLIST` är en kommaseparerad lista med adresser och `@domän`. Mejl till något i listan skickas, med `[Demo]` och ett mellanslag först i ämnesraden; resten får `blocked`. |
| `live` | Skickar. |

Starten stoppas om `MAIL_MODE=live` och `DEMO_INSTANCE=true`, om
`LINK_SECRET` saknas när läget inte är `log`, eller om läget är okänt.
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
kod det än har. Ett relä som nekar alla mottagare fäller därför mejlen ett i
taget. Får samma rad `systemic` en tredje gång och annan post har gått fram
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
  emot, kön står still (`last_run_at` äldre än 5 minuter), senaste lyckade
  utskick.
- `POST /messages/<id>/retry`: `failed` eller `bounced` tillbaka till kön.
- `POST /messages/<id>/cancel`: stoppar ett köat mejl.
