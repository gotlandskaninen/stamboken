# Tyck till

Knappen "Tyck till" i Stamboken tar emot en synpunkt från en medlem eller en
besökare. Servern skapar en GitHub-issue (publik eller privat) medan
medlemmen väntar och lägger sedan ett mejl till föreningen i
[mejlkön](mejl.md) med bilder och kontaktuppgifter. Koden finns i
`app/blueprints/tyck_till.py`, texterna i `app/utils/tyck_till.py` och
GitHub-anropen i `app/utils/github_app.py`.

## Inställningar

| Miljövariabel | Standard | Vad |
|---|---|---|
| `TYCK_TILL_GITHUB` | `logg` | `app` skapar riktiga issues med GitHub-appen. `logg` är en låtsad GitHub som lyckas (utveckling, CI, e2e) och loggar bara repo, rubrik och etiketter. `docker-compose.production.yml` sätter `app` för både api och api-test. |
| `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID` | tomt | Appens id och installationens id. |
| `GITHUB_APP_KEY` | `/config/github_app_key.pem` | Sökvägen till appens privata nyckel (PEM). |
| `TYCK_TILL_PROJEKT` | `PVT_kwDOFJznr84Bq3Yo` | Organisationsprojektet "Stamboken" (GraphQL-id), dit publika issues läggs. |
| `TYCK_TILL_MOTTAGARE` | `admin@gotlandskaninen.se` | Adressen mejlet går till. |

Är `TYCK_TILL_GITHUB=app` men nyckeln eller id:n saknas svarar endpointen 503.
Det är grinden: ingen separat flagga slår funktionen på eller av.

## Flödet

`POST /api/v2/tyck-till` (multipart, öppen utan inloggning, fel som RFC 9457):

1. Hela anropet får vara högst 9 MB (nginx tar 10 MB), annars 413.
2. Fälten kontrolleras: `typ` (`fel` eller `onskemal`), `text` (1 till 5000
   tecken), `inskick_id` (UUID från webbläsaren), `email` (krävs när man inte är
   inloggad, och används om den fylls i). Utloggad blir alltid privat.
3. Finns ett sparat svar, eller en köpost för inskicket, returneras det. Annars
   reserveras mappen `PRIVATE_UPLOAD_FOLDER/tyck-till/<inskick_id>/` med ett
   `flock`; ett inskick som redan pågår ger 409. Inget av detta drar på gränserna.
4. Gränserna: inloggad 5 per timme och konto, utloggad 3 per timme och IP och
   30 per timme sammanlagt. De kontrolleras före arbetet men förbrukas först
   när inskicket lyckas (202), så ett avslag eller ett GitHub-fel kostar inget.
   Svarar räknaren inte blir det 503. Det dolda fältet `webbplats` ger samma
   202 men skapar inget, och räknas mot gränserna. Dessutom räknas varje anrop
   som kommer förbi låset: högst 20 per timme och IP, så att avvisade bilder
   inte kan avkodas obegränsat.
5. Ett inskick åt gången per gunicorn-process (annars 503). Bilderna (högst
   fyra, JPEG, PNG, WebP eller HEIC) kodas om utan EXIF.
6. Issuen skapas (efter ett uppslag i båda reposen, publikt först, på en issue
   vars sista rad är `Referens: tt-<8 hex>`, så att ett omförsök efter ett
   förlorat svar inte ger en dublett; hittas en issue gäller dess repo och
   synlighet, oavsett vad omförsöket valde), publika läggs i
   projektet, mejlet köas och svaret sparas. GitHub-anropen har tillsammans
   högst 10 sekunder. Går de inte tas mappen bort och svaret är 503; samma
   `inskick_id` kan skickas igen.

Mejlet (`tyck_till.inskick`) har ämnet `[Tyck till] <repo>#<nummer> <referens>`
och bilderna som bilagor. `Reply-To` är adressen medlemmen vill ha svar till.

## Vad som hamnar var

Fritext, typ, generell sida, vad man pekade på, version och enhet går till
issuen. Konto-id, namn, e-post och bilder går bara till mejlet, aldrig till
GitHub. Fritexten ligger i ett kodblock och det man pekade på i en kodrad, så att
`@namn` inte pingar någon. Det man pekade på är elementets text, utan länkkoder,
UUID och e-postadresser, och ett fält beskrivs med sin etikett. En publik issue
får texten bara för knappar, rubriker och fält; för rader, stycken, rutor och
länkar står bara ordet ("raden"), eftersom de visar sidans uppgifter, till
exempel ett namn. Den privata issuen och mejlet får hela texten.

## Gallring

Nattjobbet `tyck_till_purge` (03:55) tar bort en inskickets mapp 30 dagar efter
inskicket, och en mapp som aldrig fick en köpost efter ett dygn. Mejlen i
admin@ sparas 12 månader efter att synpunkten besvarats eller stängts. Issuen
stängs när synpunkten är besvarad eller klar, och fristen räknas från
stängningen. Manuell rutin, en gång i månaden, som utgår från mejlen: sök
`subject:"[Tyck till]" older_than:12m` i admin@, och för varje mejl kör
`gh issue view <länken i mejlet> --json state,closedAt` (GitHub följer en
flyttad issue). Radera mejlet om issuen stängdes för mer än 12 månader sedan.
Det som finns kvar styr rutinen, så ingen lista kan bli för lång och flyttade
issues kommer med.

## GitHub-appen

Appen ägs av organisationen och installeras på `stamboken` och
`stamboken-drift` med Issues: write och Metadata: read, och på organisationen
med Projects: write (för publika issues). Nyckeln ligger i driftens sops-filer
och monteras som `/config/github_app_key.pem`; den ligger aldrig i
webbläsaren eller i det här repot.
