# Mejl till inläsningskön (Gmail): drift

Stamboken läser föreningens brevlåda genom Gmail API och gör varje mejl till en post i
inläsningskön, ett svar på en post, en studs i mejlkön eller ingenting. Läsningen flyttar det
lästa till papperskorgen, så den körs i en enda miljö och aldrig på demon. Det här dokumentet
beskriver inställningarna, hur brevlådan godkänns en gång, vad jobbet gör och vad larmet
betyder. Postens API står i [inkorg.md](inkorg.md), mejlkön i [mejl.md](mejl.md). Koden finns
i `app/utils/gmail.py` (anropen), `app/utils/inbox_gmail.py` (läsningen och frågan till
uppfödaren) och `app/cli/gmail.py` (godkännandet).

## Innehåll

1. [Inställningar](#inställningar)
2. [Godkänna brevlådan en gång](#godkänna-brevlådan-en-gång)
3. [Innan läsningen slås på](#innan-läsningen-slås-på)
4. [Vad jobbet gör](#vad-jobbet-gör)
5. [Etiketterna i brevlådan](#etiketterna-i-brevlådan)
6. [Larmet](#larmet)

## Inställningar

| Variabel | |
|---|---|
| `INLASNING_GMAIL` | `on` eller `off` (standard). Med `on` läser jobbet `inbox_gmail` brevlådan var femte minut i schemaläggarens ledare. |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | OAuth-klienten i föreningens Google Cloud-projekt. |
| `GMAIL_REFRESH_TOKEN` | Uppdateringstoken från `flask gmail consent`, med behörigheten `gmail.modify`. |
| `LINK_SECRET` | Krävs. Ett svar kopplas till sin fråga genom frågans `Message-ID`, som bygger på samma hemlighet ([mejl.md](mejl.md)). |

Starten stoppas när `INLASNING_GMAIL=on` och `DEMO_INSTANCE=true`, när något av de tre
`GMAIL_`-värdena eller `LINK_SECRET` saknas, och när värdet inte är `on` eller `off`.
Hemligheterna förvaras som de andra hemligheterna på servern och skrivs aldrig in i ett repo.

## Godkänna brevlådan en gång

1. Skapa i föreningens Google Cloud-projekt en OAuth-klient av typen Skrivbordsapp, med
   samtyckesskärmen Intern och Gmail API påslaget. En app med samtyckesskärmen Extern i
   läget Testning får en token som slutar gälla efter sju dagar.
2. Sätt `GMAIL_CLIENT_ID` och `GMAIL_CLIENT_SECRET` i API:ts miljö, med
   `INLASNING_GMAIL=off`, och starta om API:t.
3. Kör kommandot i API-containern:

   ```bash
   docker exec -it <api-containern> flask gmail consent
   ```

   Kommandot skriver en adress. Öppna den, logga in som brevlådans konto och godkänn.
   Webbläsaren hamnar sedan på `http://127.0.0.1:8765/?code=…`, en sida som inte går att nå.
   Kopiera hela adressen och klistra in den i kommandot.
4. Kommandot skriver uppdateringstoken på standard ut och ingen annanstans: inte i loggen och
   inte i någon fil. Lägg den i `GMAIL_REFRESH_TOKEN` bland serverns hemligheter.

Tokenen gäller tills brevlådans konto återkallar den, lösenordet byts eller den inte har
använts på sex månader. Gör då om stegen.

## Innan läsningen slås på

Den första körningen har inget `historyId` att utgå från och läser därför **hela inkorgen**.
Varje mejl där blir en post i kön och flyttas till papperskorgen. Arkivera därför först det i
inkorgen som inte ska bli poster. Sätt sedan `INLASNING_GMAIL=on` och starta om API:t.

Mejlen som Stamboken skickar har brevlådans adress som avsändare, så att svar och studsar
kommer hit. Brevlådan ska därför vara samma adress som `MAIL_FROM`.

## Vad jobbet gör

- **Hämtningen.** Jobbet läser de meddelanden som har kommit till inkorgen sedan senaste
  `historyId` (`users.history.list`). Har Gmail inte kvar den historiken läses hela inkorgen,
  utom det som redan har etiketten "Inläst". Bara INBOX läses, aldrig skräpposten.
- **En gång per mejl.** Varje behandlat mejl får en rad i `gmail_processed` i samma
  transaktion som posten, svaret eller studsen och mejlen de köar. Efter commit får mejlet
  etiketten "Inläst" och läggs i papperskorgen, som Gmail tömmer efter 30 dagar. Dör jobbet
  mellan commit och etikett, eller mellan etikett och papperskorg, görs vid nästa körning bara de
  steg i Gmail som fattas. Ett mejl i inkorgen med etiketten "Inläst" räknas som läst också när
  dess rad har gallrats. `historyId` flyttas fram först när alla mejl i körningen är klara.
- **Fel.** Ett fel i databasen, filsystemet eller Gmail avbryter körningen utan etikett och utan
  att `historyId` flyttas fram, så att nästa körning läser samma mejl igen. Ett fel i ett mejls
  innehåll räknas i `gmail_processed` (`kind` `retry`, `failures`), och mejlet läses igen vid
  nästa körning också när `historyId` har flyttats fram. Efter tre körningar i rad med fel får
  det etiketten "Fel vid inläsning", raden blir `failed` och mejlet läses inte mer. Ett mejl kan
  aldrig stoppa de andra. Texten sparas utan NUL-tecken.
- **Sorteringen**, i den här ordningen:
  1. En leveransrapport (`multipart/report; report-type=delivery-status`) går till mejlkön,
     som markerar mejlet som studsat. En rapport om ett mejl från en annan miljö (ett annat
     värdnamn i `Message-ID`) får etiketten "Demo" och rörs inte mer. En rapport som inte går
     att koppla till något mejl blir en post, så att en människa ser den.
  2. Ett autosvar (`Auto-Submitted` annat än `no`, `X-Autoreply`, `Precedence: auto_reply`)
     tas inte med.
  3. Ett svar på en annan miljös mejl får etiketten "Demo" och rörs inte mer.
  4. Ett svar på ett av Stambokens mejl om en post (`In-Reply-To`, annars "(ärende 12)" sist i
     ämnesraden) läggs på posten, om posten är öppen, Gmail har godkänt avsändarens domän och
     avsändaren är den som fick frågan, postens avsändare eller besättningens innehavare enligt
     matrikeln. Annars blir svaret en ny post som visar "Gäller kanske ärende 12".
  5. Allt annat blir en ny post: `mail` med bilagor, `meddelande` utan.
- **Avsändarens domän.** Bara det översta `Authentication-Results`, det som Googles server
  lägger till, räknas. Det måste visa `spf=pass` eller `dkim=pass` för avsändaradressens
  domän; ett godkännande för en annan domän räknas inte.
- **Kvittot** `inlasning.kvitto` går bara till en godkänd avsändare av ett mejl med bilder, och
  högst ett per avsändare och dygn, så att brevlådan inte kan användas för att skicka mejl till
  andra.
- **Avsändarens adress** sparas på posten och nollas när posten är stängd och inget mejl till
  avsändaren väntar, senast 30 dagar efter stängningen.

## Etiketterna i brevlådan

Jobbet skapar etiketterna första gången det behöver dem.

| Etikett | Betyder | Mejlet ligger |
|---|---|---|
| Inläst | behandlat | i papperskorgen |
| Fel vid inläsning | gick inte att läsa | kvar i inkorgen |
| Demo | hör till en annan miljö | kvar i inkorgen |

## Larmet

`GET /api/v2/inkorg/status` ([inkorg.md](inkorg.md)) visar senaste körning och fel, och kön
visar en rad överst när läsningen är på men inte har gått igenom på 20 minuter, eller när
senaste körningen hade ett fel.

- **Läsningen står still:** schemaläggaren går inte, eller körningen avbryts varje gång (till
  exempel en återkallad token). Felet står i larmet och i API:ts logg.
- **Fel vid inläsning:** ett mejl gick inte att läsa tre körningar i rad, och larmet ligger kvar
  så länge något mejl har etiketten. Ett mejl som ännu inte har nått tre fel står i `last_error`
  för den körning där det felade. Ta hand om mejlet i Gmail och lägg det i papperskorgen, eller ta bort
  etiketten. Ska Stamboken läsa det igen efter en rättning: nollställ `history_id` i
  `gmail_sync` och ta bort mejlets rad (`failed`) i `gmail_processed`. Nästa körning läser då hela
inkorgen, utom det som har etiketten "Inläst".
