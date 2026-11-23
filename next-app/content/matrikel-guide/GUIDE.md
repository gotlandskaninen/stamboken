# Guide för matrikeln

Den här guiden är för dig som sköter föreningens medlemsregister i Stamboken:
ansökningar, medlemskap, adresser, avgifter och export. Den syns bara för
matrikeladministratörer och administratörer. Allt annat i Stamboken beskrivs i
[manualen](https://gotlandskaninen.se/stamboken-online/manual).

Bilderna är tagna med påhittade personer.

## Innan du börjar

- **Rollen.** Du behöver rollen **Matrikeladministratör**. Den ger
  administratören dig under **Ge eller ta bort en roll** i adminpanelen.
- **Riktiga stamboken.** Utan tillgång till riktiga stamboken hamnar du i
  testmiljön. Där kan du öva, men allt du gör där försvinner nästa natt. Be
  administratören om tillgång.
- **Hitta sidorna.** Klicka på din bild uppe till höger. Längre ner i menyn
  finns **Medlemsansökningar**, **Matrikel** och **Statistik**. Står
  det en siffra efter Medlemsansökningar väntar så många ansökningar. Överst på
  de tre sidorna finns länken **Guide** hit.

![Menyn under din bild](meny.png)

## Ansökningar

<!-- route: /medlem/ansokningar -->

Den som vill bli medlem fyller i ansökan på
[gotlandskaninen.se/ansok](https://gotlandskaninen.se/ansok) och får där veta
hur stor årsavgiften är och hur den betalas. Ansökan hamnar sedan under
**Medlemsansökningar**, med namn, e-post och när den skickades in.

När en ansökan kommer in mejlar Stamboken:

- **den som ansöker** ett kvitto: att ansökan har kommit in, hur årsavgiften
  betalas och att ansökan behandlas när avgiften har kommit in.
- **varje matrikeladministratör** att en ny ansökan väntar, med en länk till
  listan. Administratörer utan rollen Matrikeladministratör får inget mejl.

![Medlemsansökningar](ansokningar.png)

### Läsa en ansökan

<!-- route: /medlem/ansokningar/[id] -->

Klicka på namnet. Under **Uppgifter** står allt den sökande fyllt i: namn,
e-post, telefon, adress, fakturaadress om den är en annan, och vad hen har
berättat om sig själv. Under **Granskning** finns knapparna **Godkänn** och
**Avslå**.

![En ansökan](ansokan.png)

### Godkänna en ansökan

Godkänn ansökan när årsavgiften har kommit in. Stamboken kontrollerar inte
betalningen, det gör du.

1. Klicka **Godkänn**.
2. Stamboken frågar "Godkänna ansökan?". Klicka **Godkänn** igen.

Medlemskapet skapas med status Aktiv, nästa lediga medlemsnummer och dagens
datum som medlem sedan. Det går inte att ångra. Stamboken mejlar den nya
medlemmen att ansökan är godkänd och att årsavgiften har kommit in, och att
föreningen hör av sig om hur hen kommer åt Stamboken. Skriv sedan in
betalningen i medlemskapets **Betalningsnotering** (se [Notera betald
avgift](#notera-betald-avgift)).

Används e-postadressen redan av en annan aktiv person i matrikeln visar
Stamboken en varning efter godkännandet. Kontrollera då att personen inte redan
är medlem.

![Godkänna ansökan?](ansokan-godkann.png)

### Avslå en ansökan

Klicka **Avslå**, skriv en **Motivering för avslag** (minst tre tecken) och
klicka **Avslå**. Den som ansökte får inget besked från Stamboken, så meddela
hen själv.

En ansökan som inte har lett till ett medlemskap, alltså en avslagen eller en som
fortfarande väntar, tas bort automatiskt när det har gått ett år sedan den
skickades in. Den nattliga rensningen kan ta bort den redan dagen före årsdagen,
så en väntande ansökan behöver godkännas senast två dagar före.

## Matrikeln

<!-- route: /medlem/matrikel -->

**Matrikel** listar alla medlemskap: nummer, status, huvudmedlem, kontakt,
adress och hur många personer som ingår.

- **Söka:** skriv namn, e-post eller medlemsnummer i sökrutan och klicka
  **Filtrera**.
- **Status:** välj en status i listan och klicka **Filtrera**. **Alla** visar
  alla.
- **Bläddra:** **Föregående** och **Nästa** längst ner.
- **Öppna ett medlemskap:** klicka på raden.

![Matrikeln](matrikel.png)

Ett medlemskap är ett hushåll. Det har en huvudmedlem och kan ha
familjemedlemmar och skötare. Adressen hör till medlemskapet, inte till
personen.

Statusarna:

| Status | Betyder |
|---|---|
| Aktiv | Medlem. |
| Inaktiv | Inte medlem. Status Inaktiv avslutar inte personerna; det gör **Avsluta medlemskap**. |
| Väntar | Inlagt men ännu inte aktivt. |
| Friexemplar | Får Koharen utan att vara medlem, till exempel tidningsutbyten. Räknas inte i medlemsantalen. |

### Lägga in ett medlemskap utan ansökan

Använd det här för den som har blivit medlem på annat sätt än via
ansökningsformuläret.

1. Klicka **Nytt medlemskap** uppe till höger.
2. Fyll i **Förnamn** och **Efternamn** (måste fyllas i), och gärna **E-post**,
   **Telefon**, **Gatuadress**, **Postnummer** och **Postort**.
3. Välj **Status**.
4. Låt **Tilldela medlemsnummer automatiskt** vara ikryssad så får medlemskapet
   nästa lediga nummer. Kryssar du ur den får medlemskapet inget nummer. Ett
   nummer kan du skriva in senare på medlemskapets sida. Lägger du in ett
   friexemplar, kryssa ur rutan: då får det nummer 0 i exporten, som i den
   gamla matrikelfilen.
5. Klicka **Skapa**.

Personen blir huvudmedlem i det nya medlemskapet.

![Nytt medlemskap](nytt-medlemskap.png)

## Ett medlemskap

<!-- route: /medlem/matrikel/[id] -->

Överst på medlemskapets sida står status, huvudmedlem och sedan när hushållet
är medlem. Raden under visar **Betalningsnotering**, vad som får **Publiceras i
Koharen**, hushållets **Besättningar** och hur många personer som har ett
konto i Stamboken (**Kopplade konton**).

Därunder finns **Personer** och **Medlemskap**.

![Ett medlemskap](medlemskap.png)

### Ändra adress

1. Skriv den nya adressen i **Gatuadress**, **Postnummer** och **Postort** under
   **Medlemskap**. Postnumret ska vara fem siffror.
2. Klicka **Spara**.

Ska fakturan till en annan mottagare, till exempel en djurpark eller ett
företag, kryssa i **Annan fakturaadress** och fyll i **Fakturamottagare**,
**Fakturaadress**, **Fakturapostnummer**, **Fakturapostort** och vid behov
**E-post för faktura** och **Fakturareferens**. Kryssar du ur rutan och sparar
tas fakturaadressen bort, och fakturan går till postadressen.

Är huvudmedlemmens konto kopplat till medlemskapet (se [Koppla ett
konto](#koppla-ett-konto)) kan huvudmedlemmen själv ändra hushållets adress
under **Profil** i Stamboken. Ändringen syns då här. Andra personer i hushållet
kan bara läsa uppgifterna.

![Medlemskap](medlemskap-formular.png)

### Notera betald avgift

**Betalningsnotering** är ett fritt textfält, som kolumnen för betalning i den
gamla matrikelfilen. Skriv till exempel "Betalt 2026-11-16 Swish" och klicka
**Spara**. Noteringen syns överst på medlemskapets sida och följer med i
exporten.

Stamboken har inget eget fält för om avgiften är betald eller inte. Det är bara
den här texten.

**Anteckningar** är för annat du vill komma ihåg om medlemskapet.

### Status och medlemsnummer

Under **Medlemskap** kan du byta **Status** och skriva in eller ändra
**Medlemsnummer**. Klicka **Spara**. Alla ändringar sparas i en logg. Skriver
du ett nummer som är högre än något som har delats ut, fortsätter nästa
automatiska nummer efter det. Ge inte ett nummer som har använts tidigare:
Stamboken kontrollerar bara att inget annat medlemskap har numret just nu.

### Personer i medlemskapet

Under **Personer** står hushållets personer med roll, kontakt, konto och
åtkomster till besättningar.

- **Lägga till en familjemedlem:** klicka **Lägg till person**, fyll i
  **Förnamn** och **Efternamn**, gärna **E-post** och **Telefon**, välj **Roll**
  (**Familjemedlem** eller **Skötare**) och klicka **Spara**. Har personen en
  e-postadress mejlar Stamboken hen att hen har lagts in, vem som är
  huvudmedlem och var föreningens dataskyddspolicy finns.
- **Ändra en person:** klicka **Redigera** på personens rad.
- **Fler åtgärder:** klicka **⋯** på personens rad:
  - **Ge åtkomst** låter personen sköta en av hushållets besättningar i
    Stamboken. Välj **Besättning** och vid behov **Giltig till**. Lämnas datumet
    tomt gäller åtkomsten tills vidare för en familjemedlem och ett år för en
    skötare.
  - **Gör till huvudmedlem** byter huvudmedlem i hushållet.
  - **Ta bort** avslutar personen i medlemskapet och drar in hens åtkomster.
  - **Anonymisera** ersätter personens namn med en platshållare, tar bort
    kontaktuppgifterna och drar in åtkomsterna. Det går inte att ångra.
- **Åtkomster:** i kolumnen **Åtkomster** drar **Återkalla** in en åtkomst, och
  **Förnya** förlänger en skötares tidsbegränsade åtkomst.

![Lägg till person](lagg-till-person.png)

![Fler åtgärder för en person](person-atgarder.png)

### Koppla ett konto

En person i matrikeln och ett konto i Stamboken är två olika saker. Klicka
**Koppla konto…** på personens rad, sök fram kontot och klicka **Koppla konto**.
Då ser personen medlemskapet under **Profil**. Är personen huvudmedlem kan hen
där också ändra hushållets adress och vad som får publiceras i Koharen. Andra
personer i hushållet kan bara läsa. **Koppla bort** tar bort kopplingen.

### Avsluta ett medlemskap

Klicka **Avsluta medlemskap** under **Medlemskap** och sedan **Bekräfta**.
Medlemskapet blir inaktivt, alla personer i det avslutas och deras åtkomster
dras in. Ett avslutat medlemskap kan inte göras aktivt igen. Kommer medlemmen
tillbaka lägger du in ett nytt medlemskap och låter Stamboken tilldela nästa
nummer automatiskt. Ett medlemsnummer som har använts ska inte ges till någon
annan.

### Anonymisering efter 12 månader

Stamboken anonymiserar personer automatiskt: namnen ersätts med en platshållare
och kontaktuppgifterna tas bort. Tiden räknas från när personerna avslutades,
alltså från **Avsluta medlemskap** eller **Ta bort**. Att bara välja status
Inaktiv avslutar ingen, och då börjar ingen tid räknas.

- **Ett avslutat medlemskap** anonymiseras när det har gått 12 månader sedan den
  sista personen i det avslutades. Alla personer anonymiseras då samtidigt, och
  hushållets adress, fakturaadress och anteckningar töms. Medlemsnumret står
  kvar på medlemskapet.
- **En familjemedlem eller skötare** som har tagits bort ur ett medlemskap där
  någon annan fortfarande är kvar anonymiseras 12 månader efter att hen togs
  bort. Hushållets adress står kvar.

Stamboken hoppar över ett avslutat medlemskap där någon av personerna har
rollen administratör, matrikeladministratör eller genbanksansvarig eller äger
en aktiv besättning, eller där en av hushållets besättningar fortfarande är
aktiv. En borttagen person hoppas över om hens eget konto har en sådan roll
eller äger en aktiv besättning. Undantaget gäller bara så länge rollen eller
den aktiva besättningen finns. Försvinner den anonymiseras uppgifterna vid nästa
nattliga körning. Systemansvarig kan bedöma fallen medan undantaget gäller.

Besättningens egna kontaktuppgifter tas inte bort av den här regeln.

![Avsluta medlemskap?](avsluta-medlemskap.png)

## Statistik

<!-- route: /medlem/statistik -->

**Statistik** visar hur många medlemskap och personer som finns, uppdelat på
aktiva, inaktiva och väntande, hur många friexemplar som går ut och hur många
medlemskap som är nya i år. Friexemplar ingår inte i de andra talen.

![Statistik](statistik.png)

## Exportera

Knapparna finns överst i **Matrikel** och på **Statistik**. Båda laddar ner en
CSV-fil som går att öppna i Excel.

- **Exportera MATR** ger aktiva medlemskap och friexemplar med samma kolumner
  som den gamla matrikelfilen: en rad per person, med adress, betalningsnotering
  och anteckningar på huvudmedlemmens rad och fakturaadressen sist.
  Friexemplar utan medlemsnummer får nummer 0, men ett friexemplar som har
  fått ett nummer står med det numret. Filen har ingen kolumn för status, så
  kontrollera status i matrikeln innan du följer upp avgifter. Använd filen som
  adresslista för Koharen och för avgiftsuppföljning.
- **Exportera Koharen** ger personerna i aktiva medlemskap, med bara de
  uppgifter hushållet har sagt ja till att publicera: namn, telefon, e-post och
  adress. Valet gäller hela hushållet och görs av huvudmedlemmen under
  **Profil**, och syns som **Publiceras i Koharen** på medlemskapets sida. Har
  hushållet inte svarat är uppgifterna tomma och det står "ej angivet". Filen är
  underlaget till medlemsförteckningen i Koharen.

Filerna innehåller personuppgifter. Spara dem inte där andra kommer åt dem, och
ta bort dem när du inte behöver dem längre.
