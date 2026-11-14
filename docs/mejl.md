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
  mottagares rad anropar `forget_recipient(kind, id)`, som tömmer fältet.
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
(`Member.email`), `user` (`hbuser.email`) och `application` (ansökan om
medlemskap). En ny sort registreras med
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
att fungera.

## Utskicksläge

| `MAIL_MODE` | Effekt |
|---|---|
| `log` (standard) | Ingen SMTP-anslutning. Raden får `logged`, och loggen visar typ, id och mottagarens hänvisning, med den färdiga texten när `FLASK_ENV` inte är `production`. |
| `allowlist` | `MAIL_ALLOWLIST` är en kommaseparerad lista med adresser och `@domän`. Mejl till något i listan skickas, med `[Demo] ` först i ämnesraden; resten får `blocked`. |
| `live` | Skickar. |

Starten stoppas om `MAIL_MODE=live` och `DEMO_INSTANCE=true`, om
`LINK_SECRET` saknas när läget inte är `log`, eller om läget är okänt.
Övriga inställningar: `SMTP_HOST`, `SMTP_PORT` och `MAIL_FROM`. Appen har
inget användarnamn eller lösenord för SMTP.

## Sändaren

- Varje körning stämplar `mail_sender.last_run_at`, också när kön är tom.
- En sändare tar en rad åt gången (`FOR UPDATE SKIP LOCKED`) och märker den
  med en ny `claim_token`. Resultatet skrivs med villkoret att märket är
  oförändrat. Två sändare får därför aldrig samma rad, och den som tappat en
  rad kan inte skriva över resultatet från den som tog den.
- Har en rad varit `sending` i över 10 minuter (sändaren dog) blir den
  `queued` igen.
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
som `bounced`. Ett `Message-ID` med en annan miljös värdnamn eller fel HMAC
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
