# Ordlista – Stamboken Online

Ordlistan ger alla som arbetar med Stamboken samma ord för samma sak och samma förklaring av varje ord.
Referens är gamla Stamboken: dess manual och dess skärmar. Nya Stamboken ska använda samma ord, och
UI-texterna i nya Stamboken kontrolleras av `scripts/check-ui-terms.sh`.
Ett ord byts här först, sedan i grindens lista och i texterna.

Källor och förkortningar:

- **Legacy-manual** – "DRAFT: Användarmanual för Stamboken Online" (Google-dokument, 6 sidor). PDF och
  textutdrag (`pdftotext -layout`) ligger i stamboken-drift under `docs/legacy-manual/`; `manual:25` är
  rad 25 i `legacy-manual.txt`, vars ordlista står på rad 14–35.
- **Legacy** – gamla React-appen, filer under `stamboken-legacy/frontend/src/`.
- **Nytt UI** – nya Stamboken: nycklar i `next-app/messages/sv.json` (skrivs som `nyckel`) och filer
  under `next-app/src/` (filnamnen är unika).
- **Kod** – fält eller modell i `app/utils/database.py` eller i koden som nämns.

I raden `Kod:` betyder "samma" att gränssnittet använder uppslagsordet och "–" att gränssnittet saknar
etikett för begreppet. Källhänvisningarna står i inventeringen längre ned.

## Ordlista

**Administratör**\
Sköter hela systemet: ger och tar bort roller, skapar besättningar, byter ägare på besättningar
och ger användare tillgång till riktiga stamboken. Kan se och ändra allt i båda genbankerna.\
Kod: `admin` · Legacy-manual: – · Legacy: "Admin", "administratör" · Nytt UI: samma

**Aktiv kanin / inaktiv kanin**\
Gamla manualen: aktiva djur är kaniner som är registrerade och årsrapporterade, i aktiva besättningar.
Inaktiva är kaniner som inte årsrapporterats, kaniner i inaktiva besättningar, döda kaniner och
oregistrerade kaniner. Nya Stamboken räknar en kanin som aktiv när den har intyg, lever, inte är
kastrerad, står i en aktiv besättning i genbanken (inte GX1/MX1) och har fötts, sålts eller
årsrapporterats de senaste 13 månaderna. Död är en egen status: en död kanin är inte inaktiv.\
Kod: `Individual.active` (`is_active`) · Legacy-manual: "Aktiva djur", "Inaktiva djur" · Legacy: "Aktiv", "Inaktiv" · Nytt UI: "Aktiv", "Inaktiv", "Död", "Aktiva kaniner"

**Avelsdjur**\
En aktiv kanin som inte är kastrerad och har känt kön. Antalet visas på översikten i Min besättning.\
Kod: aktiv + `castration_date` tom + `sex` · Legacy-manual: – · Legacy: – · Nytt UI: samma

**Benring**\
Ringen runt kaninens ben, med serie och löpnummer (till exempel GKF 123). De flesta kaniner tatueras
inte längre i örat; de märks med benring och chip.\
Kod: `Individual.foot_ring` · Legacy-manual: – · Legacy: – · Nytt UI: "Fotring" (auditLabels.ts), "Fotringsnr" (pappersintygets PDF-mall)

**Besättning / inaktiv besättning**\
Din del i en genbank: dina registrerade och oregistrerade kaniner, och kontaktuppgifterna som andra
uppfödare ser. En inaktiv besättning har upphört, tillfälligt eller för gott. GX1 och MX1 räknas
också som inaktiva besättningar.\
Kod: `Herd` (`Herd.is_active`) · Legacy-manual: "Besättning", "Inaktiv besättning" · Legacy: samma, "Aktiv" · Nytt UI: samma, "Besättningen är aktiv", "Min besättning" (menyn)

**Besättningshistorik**\
Listan på kaninens sida över var kaninen har funnits, med datum. Varje rad är en händelse: Född,
Flytt (försäljning eller annat byte av besättning), Årsrapport eller Korrigering. En felaktig rad
ångras och finns kvar; kryssrutan Visa ångrade visar den.\
Kod: `HerdTracking` (`kind`: BIRTH, TRANSFER, ATTESTATION, CORRECTION) · Legacy-manual: "besättningshistoria" · Legacy: "Besättningshistoria" · Nytt UI: samma

**Besättningsnummer**\
Besättningens nummer, till exempel G1274: rasens bokstav (G för gotlandskanin, M för mellerudskanin)
och medlemsnumret. Det står först i individnumret på varje kanin som föds i besättningen.\
Kod: `Herd.herd` · Legacy-manual: samma · Legacy: samma, "Besättnings-ID", "Genbanksnummer" · Nytt UI: samma

**Brokig**\
Vit kanin med färgade fläckar. Färgatlasen använder brokig för hela gruppen, och färgnamnen följer
den: svartbrokig, gulbrokig, viltgråbrokig. Scheck, mantel och dalmatiner är varianter av brokig
teckning, inte andra ord för samma sak. Skriv brokig i löptext, inte scheck. Rasramarnas text
ändras inte.\
Kod: färgnamnen i `Color` · Legacy-manual: – · Legacy: "Svartbrokig" med flera · Nytt UI: samma

**Chipnummer**\
Numret i kaninens chip: 15 siffror enligt ISO 11784, i Sverige börjar det på 752. En kanin kan ha
både chip och benring.\
Kod: `Individual.microchip` · Legacy-manual: – · Legacy: – · Nytt UI: –

**Demo**\
Kodens namn på testmiljön. Uppfödare ser bara ordet testmiljö. Administratören ser ordet demo under
Demosynkronisering, som visar när testmiljön senast fylldes med en kopia av riktiga stamboken.\
Kod: `sb_mode=demo`, `demo_sync_status` · Legacy-manual: – · Legacy: – · Nytt UI: "Demosynkronisering", "Demoversionen"

**Digitalt intyg**\
Ett intyg som Stamboken utfärdar som en signerad PDF. Uppfödaren skapar det själv i programmet och
det är gratis. Det har en QR-kod som vem som helst kan skanna för att se att intyget är äkta. I nya
Stamboken utfärdas det när du registrerar ungen från kullistan.\
Kod: `digital_certificate`, `DigitalCertificateV2` · Legacy-manual: "digitalt intyg" · Legacy: "Digital", "Digitalt intyg" · Nytt UI: "Digitalt" (valet), "Digitalt intyg"

**Död / dödsdatum / dödsorsak**\
En kanin som rapporterats död får ett dödsdatum och gärna en orsak i fritext, till exempel sjukdom
eller numret på en obduktionsrapport. Död är en egen status; kaninen räknas sedan varken som aktiv
eller som inaktiv. I nya Stamboken kan en dödsrapportering ångras.\
Kod: `death_date`, `death_note` · Legacy-manual: "Döda djur", "Anteckningar om kaninens död" · Legacy: "Rapportera som död", "Dödsdatum", "Dödsnotering" · Nytt UI: "Rapportera död", "Dödsdatum", "Dödsorsak"

**Färg / färganteckning**\
Färgen väljs ur genbankens lista med godkända färger; saknas färgen kontaktar du genbanksansvarig.
I färganteckning kompletterar du med fritext när färgen i listan inte stämmer helt, till exempel
efter "brokad på annat sätt", eller "sv/v" för mellerudskanin med holländarteckning. Ögonfärg,
klofärg, bukfärg och avvikande hårlag är egna fält.\
Kod: `color` (`Color`), `color_note`, `eye_color`, `claw_color`, `belly_color`, `hair_notes` · Legacy-manual: "Färganteckning" · Legacy: "Färg", "Färganteckning" · Nytt UI: samma

**Genbank**\
Alla besättningar och alla kaniner av en ras i föreningens bevarandeprogram. Föreningen har två
genbanker: gotlandskanin (besättningsnummer på G) och mellerudskanin (M).\
Kod: `Genebank` · Legacy-manual: samma · Legacy: "Genbank", "Genbanker" · Nytt UI: samma

**Genbanksansvarig**\
Föreningens ansvariga för en ras. Ser och kan rätta alla kaniner och besättningar i sin genbank,
rättar besättningshistorik, numrerar om kullar och lägger in kaniner som köpts från en besättning
utanför genbanken. Tar emot pappersintyg och årsrapporter.\
Kod: `manager` · Legacy-manual: samma · Legacy: samma, "Manager" · Nytt UI: samma

**Granskare**\
Ser allt i en genbank men kan inte ändra något.\
Kod: `viewer` · Legacy-manual: – · Legacy: "Viewer" · Nytt UI: samma

**GX1 / MX1**\
Två påhittade besättningar för kaniner som sålts till någon utanför genbanken, till exempel som
sällskapsdjur: GX1 för gotlandskanin, MX1 för mellerudskanin. En kanin utan intyg kan bara säljas
hit. Kaniner i GX1 och MX1 är inaktiva.\
Kod: `OUTSIDE_GENEBANK_HERDS` · Legacy-manual: "GX1/MX1" · Legacy: "Utanför genbanken" · Nytt UI: "Utanför genbanken", "Såld utanför genbanken"

**Inavelskoefficient (F)**\
Hur inavlad en kanin är, i procent. Den blir högre ju närmare släkt föräldrarna är. Vid provparning
visas den för den tänkta avkomman, så att du kan välja ett par som inte är för nära släkt.\
Kod: `inbreeding` · Legacy-manual: "inavelskoefficient" · Legacy: "Inavelskoefficient" · Nytt UI: "F — Inavelskoefficient", "inavelsgrad"

**Individ / kanin**\
Ett djur i stamboken. Orden betyder samma sak: individ står oftast i knappar och rubriker
(Sälj individ), kanin i löptext.\
Kod: `Individual` · Legacy-manual: "kanin", "individ" · Legacy: samma · Nytt UI: samma, "Kaniner" (fliken), "Alla kaniner" (menyn)

**Individnummer**\
Kaninens unika nummer, till exempel G1274-2312: besättningen där den föddes (G1274), födelseåret (23),
kullnumret (1) och platsen i kullen (2). Numret står på intyget och ändras inte när kaninen säljs.
En unge i kullistan har bara ett preliminärt nummer tills den registreras.\
Kod: `Individual.number` · Legacy-manual: "individnummer", "genbanksnummer" · Legacy: samma, "Nummer" · Nytt UI: samma

**Intyg**\
Kaninens stamtavla och beviset på att den är registrerad i genbanken. Det finns pappersintyg och
digitala intyg. En kanin registreras alltid med intyg och får då sitt individnummer; utan intyg kan
den inte registreras. Intyget följer med kaninen när den säljs. Kallas också genbanksintyg.\
Kod: `certificate`, `digital_certificate` · Legacy-manual: "intyg", "genbanksintyg" · Legacy: samma · Nytt UI: samma, "stamtavleintyg"

**Intygsnummer**\
Numret på kaninens intyg. På ett pappersintyg är det numret som står tryckt; ett digitalt intyg får
sitt nummer av Stamboken. När kaninen har ett intygsnummer kan uppfödaren inte längre ändra
individnummer eller härstamning, bara namn, färg, kön och anteckningar.\
Kod: `certificate` (papper), `digital_certificate` (digitalt) · Legacy-manual: "intygsnummer" · Legacy: "Intygsnummer", "Nummer på pappersintyg" · Nytt UI: "Intygsnummer"

**Kastrerad**\
En kastrerad kanin har ett kastreringsdatum. Den räknas inte som aktiv och inte som avelsdjur,
även om den lever.\
Kod: `castration_date` · Legacy-manual: – · Legacy: – · Nytt UI: "Kastrerad"

**Kull**\
Ungarna från en födsel. Parning och kull är samma post: först registreras parningen, sedan födseln
med antal födda och antal levande vid 6 veckor. Högst 9 kaniner per kull kan registreras, och inte
fler intyg än antalet levande vid 6 veckor. Lägger du till en kanin med **+ Lägg till kanin** utan
att kullen finns skapar Stamboken parningen och kullen automatiskt.\
Kod: `Breeding` (`litter_size`, `litter_size6w`) · Legacy-manual: "kull" · Legacy: "Kull", "Kullstorlek" · Nytt UI: "Kull", "Kullar och parningar" (fliken), "Antal födda", "Antal vid 6 veckor"

**Kullista**\
Listan över ungarna i en kull innan de registrerats. När du registrerar födseln skapas en rad per
född unge. Där för du kön, färg och anteckningar medan ungarna växer och anger vad som händer med
varje unge. Från 6 veckors ålder registrerar du ungarna härifrån.\
Kod: `Bunny` · Legacy-manual: – · Legacy: – · Nytt UI: samma

**Kullnummer**\
Kullens ordningsnummer i besättningen under ett år; årets första kull är kull 1. Kullnumret ingår
i ungarnas individnummer, så kullarna ska registreras i den ordning de föddes. Blir det fel kan
kullarna numreras om; påverkar det redan registrerade kaniner krävs genbanksansvarig.\
Kod: `Breeding.litter_number` · Legacy-manual: "kullnummer" · Legacy: "kullnummer" (felmeddelande) · Nytt UI: "Kullnummer", "Kull 1"

**Kön (hona / hane)**\
Hona eller hane. För en unge i kullistan kan könet vara okänt, men det måste anges innan ungen
registreras. Kön är ett t-ord, så okänt kön heter Okänt; Okänd gäller en-ord som okänd mor.\
Kod: `sex` (`female`, `male`) · Legacy-manual: "honan", "hane" · Legacy: "Kön", "Hona", "Hane", "Okänd" · Nytt UI: "Kön", "Hona", "Hane", "Okänt"

**Köpt / ursprungsbesättning**\
Ursprungsbesättningen är besättningen där kaninen föddes, alltså där modern fanns vid födseln.
Den står först i individnumret och ändras inte när kaninen säljs. En kanin som står i en annan
besättning än sin ursprungsbesättning märks Köpt på kaninens kort. Köparen registrerar ingenting;
det gör säljaren eller genbanksansvarig.\
Kod: `origin_herd` · Legacy-manual: "köpt" · Legacy: "Ursprungsbesättning" · Nytt UI: "Köpt", "Ursprungsbesättning" (ändringsloggen)

**Matrikeladministratör**\
Sköter medlemsregistret: medlemskap, medlemsnummer, personer och medlemsansökningar.\
Kod: `matrikel_admin` · Legacy-manual: – · Legacy: – · Nytt UI: samma

**Medlem / medlemsnummer / matrikel**\
Medlem i Föreningen Gotlandskaninen. Matrikeln är föreningens medlemsregister. Varje medlemskap
har ett medlemsnummer och kan omfatta en huvudmedlem, familjemedlemmar och skötare.
Besättningsnumret är medlemsnumret med rasens bokstav framför.\
Kod: `Membership`, `member_number`, `Member` · Legacy-manual: "medlemsregistret" · Legacy: "medlemsmatrikeln" · Nytt UI: "Matrikel", "Medlemsmatrikel", "Medlemsnummer"

**Oregistrerad unge**\
Gamla manualen: en unge som ännu inte fått ett intyg. I nya Stamboken är det en rad i kullistan
som inte registrerats än; den har bara ett preliminärt individnummer.\
Kod: `Bunny` · Legacy-manual: "Oregistrerade djur" · Legacy: "Oregistrerade djur", "oregistrerade kaniner" · Nytt UI: "unge", "Behålls oreg."

**Pappersintyg**\
Ett tryckt intyg som skickas med posten. Numret som står tryckt på det skrivs in när kaninen
registreras. Ändras uppgifter om kaninen rättar du på papperet; skapa inte ett nytt intyg.
Pappersintyg för sålda, köpta och nya kaniner skickas till genbanksansvarig.\
Kod: `certificate` · Legacy-manual: "pappersintyg" · Legacy: "Papper" · Nytt UI: "Papper" (valet), "Pappersintyg"

**Parning**\
När en hona och en hane parats. Du registrerar parningen med datum; när honan fått ungar lägger du
till födseln på samma post, och då blir den en kull. Tills dess står parningen som Väntar på kull.\
Kod: `Breeding` (`breed_date`) · Legacy-manual: "parning" · Legacy: "Parning", "Parningsdatum" · Nytt UI: samma

**Provparning / provpara**\
Att räkna ut, innan du parar, vilken inavelskoefficient en tänkt avkomma skulle få och vilka
gemensamma förfäder föräldrarna har. Är en förälder inte registrerad väljer du dess mor och far i
stället. Nya Stamboken kan jämföra flera hanar mot samma hona.\
Kod: `testbreed` · Legacy-manual: "Provparning", "provpara" · Legacy: "Provparning" · Nytt UI: samma, "Provpara"

**Registrera / registrerad kanin**\
En registrerad kanin är inskriven i stamboken med intyg, pappersintyg eller digitalt intyg, och har
därmed fått sitt individnummer. Att registrera är att skriva in kaninen med intyg; utan intyg går det
inte. I nya Stamboken gör du det från kullistan när ungen är 6 veckor.\
Kod: `Individual`, `Bunny.fate` (`registered`) · Legacy-manual: "Registrerade djur", "registrera" · Legacy: "Registrera", "Registrerad" · Nytt UI: samma, "Skriv in"

**Riktiga stamboken / testmiljön**\
Riktiga stamboken är den som gäller; det du sparar där syns för alla. Testmiljön är en kopia där du
kan öva fritt. Den skrivs över varje natt, och en gul rad överst visar att du är där. Nya användare
börjar i testmiljön och byter i avatarmenyn när administratören gett dem tillgång.\
Kod: `sb_mode` (`prod`, `demo`), `v2_prod_access` · Legacy-manual: "den skarpa sidan", "Testsystemet" · Legacy: "TESTSYSTEMET" · Nytt UI: "riktiga stamboken", "testmiljön"

**Skötare**\
En person som får sköta en annan medlems besättning. Åtkomsten gäller ett år och kan förnyas. En
skötare kan inte sälja kaniner.\
Kod: `caretaker` (`HerdAccessGrant`) · Legacy-manual: – · Legacy: – · Nytt UI: samma

**Slaktad / avlivad / försvunnen**\
Sätt att dö som visas som egen status. Slaktad kryssar du i när du rapporterar döden, om kaninen
dödats för kött eller på grund av platsbrist. Avlivad och Försvunnen visas när dödsorsaken
innehåller ord som "avlivad", "rymt" eller "försvann". Alla tre räknas som döda.\
Kod: `butchered`, `death_note` · Legacy-manual: "slaktats" · Legacy: "slaktats" (frågan) · Nytt UI: "Slaktad", "Avlivad", "Försvunnen"

**Släktskapskoefficient / medelsläktskap (MK)**\
Hur nära släkt två kaniner är, i procent. En avkommas inavelskoefficient är lika med släktskapen
mellan föräldrarna. Medelsläktskap (MK) är en kanins genomsnittliga släktskap med de aktiva djuren
i genbanken; ett lågt värde betyder att kaninen bär ovanliga gener som är viktiga att föra vidare.\
Kod: `mean_kinship`, `inbreeding` · Legacy-manual: "släkt" · Legacy: "Genomsnittligt släktskap" · Nytt UI: "MK — Genomsnittlig medelkinship", "kinship-koefficient"

**Släktträd / härstamning**\
Släktträdet visar kaninens föräldrar, mor- och farföräldrar och längre bakåt. Härstamningen är
kaninens mor och far; den anges när kaninen läggs in och kan inte ändras av uppfödaren när kaninen
har intyg. På de publika sidorna används stamtavla i samma mening.\
Kod: `Breeding.mother`, `Breeding.father` · Legacy-manual: "Släktträd", "härstamning" · Legacy: samma · Nytt UI: "Släktträd", "stamtavla", "Mor", "Far"

**Sälja / säljdatum / såld**\
När en kanin byter besättning registrerar säljaren försäljningen: ny besättning (eller GX1/MX1) och
säljdatum. Datumet får inte ligga i framtiden och tidigast 43 dagar efter födseln. Kaninen flyttas
till köparens besättning, och säljaren kan sedan inte ändra den. Samma väg används när kaninen byter
besättning utan att säljas, till exempel när en hona lånas ut för avel.\
Kod: `HerdTracking` (`kind` TRANSFER) · Legacy-manual: "sälja", "försäljningsdatum" · Legacy: "Sälj individ", "Sälj", "Köpdatum" · Nytt UI: "Sälj individ", "Säljdatum", "Försäljning", "är såld till"

**Testmiljön**\
Se riktiga stamboken / testmiljön.\
Kod: `sb_mode=demo` · Legacy-manual: "Testsystemet" · Legacy: "TESTSYSTEMET" · Nytt UI: "testmiljön"

**Uppfödare / besättningsägare**\
Den som äger en besättning och för in sina kaniner, parningar och kullar. Uppfödare används när texten
vänder sig till personen, i löptext och rubriker. Besättningsägare är bara rollens namn i
adminpanelen (rollväljaren, rollsammanfattningen, användarsidorna). En besättning kan ha flera ägare.\
Kod: `owner` · Legacy-manual: "vanlig användare" · Legacy: "Owner" · Nytt UI: "Uppfödare", "Besättningsägare" (rollen), "Ägare"

**Verifiera intyg**\
Kontrollera att ett digitalt intyg är äkta och det senaste. I nya Stamboken skannar du QR-koden eller
öppnar länken på intyget; sidan visar Äkta genbanksintyg, Äkta men ersatt (det finns ett nyare intyg)
eller att intyget inte hittades. I gamla Stamboken laddade du upp PDF-filen på kaninens sida.\
Kod: `DigitalCertificateV2` (uuid) · Legacy-manual: "verifiera" · Legacy: "Verifiera intyg", "Verifiera" · Nytt UI: "Verifiera Genbanksintyg", "Äkta genbanksintyg"

**Vikt / hull**\
Kaninens vikt i kilo och dess hull, alltså hur fet eller mager den är (låg, normal eller hög), med
mätdatum. I gamla Stamboken rapporterades vikt och hull före årsrapporten. Nya Stamboken visar de
senaste värdena på kaninens sida men har ännu ingen knapp för att lägga till nya.\
Kod: `Weight`, `Bodyfat` · Legacy-manual: "vikt och hull" · Legacy: "Vikt", "Hull" · Nytt UI: "Senaste vikt", "Senaste hull"

**Webbkurs**\
Föreningens kurs för nya användare. Administratören markerar på kontot att kursen är genomförd.
Tillgång till riktiga stamboken är en separat markering.\
Kod: `validated` · Legacy-manual: – · Legacy: "Validerad" · Nytt UI: "Webbkurs genomförd (validerad)"

**Ångra**\
Ta tillbaka en åtgärd utan att något raderas: en försäljning, en dödsrapportering, en händelse i
besättningshistoriken eller en ändring i ändringshistoriken. Det ångrade finns kvar och kan visas.
En egen försäljning kan du ångra inom sju dagar; efter det hjälper genbanksansvarig.\
Kod: `voided_at`, `IndividualCommand` · Legacy-manual: – · Legacy: – · Nytt UI: "Ångra", "Ångra försäljning", "Ångra hela åtgärden"

**Årsrapport / årsrapportera**\
Varje år bekräftar du att varje registrerad kanin finns kvar i din besättning vid årets slut, och
besättningen lämnar en årsrapport (kullar, födda ungar, avelsdjur) som är grund för genbanksstödet.
En kanin som inte årsrapporterats inom 13 månader blir inaktiv. I nya Stamboken visar Årsrapportera
ännu "Kommer snart".\
Kod: `YearlyHerdReport`, `HerdTracking` (`kind` ATTESTATION) · Legacy-manual: "Årsrapportering", "Årsrapportera" · Legacy: "Årsrapport", "Årsrapportera" · Nytt UI: samma

**Ändringshistorik**\
Listan längst ned på kaninens sida över varje ändring: när, av vem och vilka fält som ändrades
(gammalt värde överstruket, nytt bredvid). Poster från gamla Stamboken är märkta Gamla Stamboken.
Härifrån kan en ändring ångras eller posten återställas till läget före ändringen.\
Kod: `AuditLog` · Legacy-manual: – · Legacy: – · Nytt UI: samma

**Öde**\
Vad som händer med en unge i kullistan: Obestämd, Behålls oreg. (behålls utan att registreras),
Slaktad, Död eller Registrerad. En unge med ödet Slaktad eller Död registreras inte.\
Kod: `Bunny.fate` · Legacy-manual: – · Legacy: – · Nytt UI: samma

## Inventering: samma begrepp, olika ord

En rad per begrepp där källorna någon gång använt olika ord. "Nytt UI (före 2026-10-29)" är läget
före commit `9b95c79` (fix(ui): use the canonical Swedish terms in UI strings). Beslut är antingen det kanoniska
ordet i `scripts/check-ui-terms.sh`, med datum om det beslutades 2026-10-30 (se Beslut), eller
"Öppen fråga" (se sist).

| Begrepp | Legacy-manual | Legacy | Nytt UI (före 2026-10-29) | Nytt UI (nu) | Beslut |
| --- | --- | --- | --- | --- | --- |
| Kaninens nummer | "individnumret" (manual:147), "individ-nummer" (manual:184), "genbanksnummer" (manual:200, 214) | "Individnummer" (individual_form.tsx:177), "Nummer" (filter_table.tsx:222, individual_view.tsx:222) | "Genbanksnummer" (`certificate.individualNumber`, RabbitExplorer.tsx:127, `explorer.search`) | "Individnummer" (samma ställen) | Individnummer |
| Besättningens nummer | "besättningsnummer" (manual:166, 219) | "Besättningsnummer" (individual_certificate.tsx:439), "Besättnings-ID" (herdForm.tsx:392), "Genbanksnummer" (YearlyReportForm.tsx:384) | "genbanksnummer" (bli-genbank/page.tsx:103), "Besättningsnummer" (CreateHerdForm.tsx:131) | "Besättningsnummer" (bli-genbank/page.tsx:103, CreateHerdForm.tsx:131), "Besättnings-ID" (BesattningsuppgifterCard.tsx:98) | Besättningsnummer |
| Intygets nummer | "intygsnummer" (manual:187) | "Intygsnummer" (individual_view.tsx:371, individual_form.tsx:193), "Nummer på pappersintyg" (cert_autocomplete.tsx:104) | "Certifikatnummer" (`certificate.number`), "Certifikatnr" (verifiera/[uuid]/page.tsx:107) | "Intygsnummer" (`certificate.number`, `addRabbit.paperCertificateNumber`, verifiera/[uuid]/page.tsx:107) | Intygsnummer |
| Dokumentet | "genbanksintyg" (manual:28, 64), "intyg" (manual:30) | "intyg", "genbanksintyg" (YearlyReportForm.tsx:523), "stamtavlor (genbanksintyg)" (static_pages.tsx:210) | "certifikat v2" (`addRabbit.certificateDigitalDisabled`) | "intyg", "genbanksintyg" (`certificate.verified`), "stamtavleintyg" (IndividualCard.tsx:404) | intyg, aldrig certifikat |
| Intygstyp | "pappersintyg" (manual:116), "digitalt intyg" (manual:165) | "Papper", "Digital", "Inget intyg" (cert_autocomplete.tsx:31–33), "Typ av intyg" (cert_autocomplete.tsx:73) | samma som nu | "Papper", "Digitalt" (`addRabbit.certificatePaper`, `addRabbit.certificateDigital`); "Pappersintyg", "Digitalt intyg" (KaninerTab.tsx:92–93) | Pappersintyg, Digitalt intyg (valet ej ändrat) |
| Utfärda digitalt intyg | "Skapa nytt intyg" (manual:147), "Beställ intyg" (manual:167) | "Skapa nytt intyg" (individual_view.tsx:338), "Beställ intyg" (individual_certificate.tsx:485) | samma som nu | "Digitalt" i Registrera (BunnyPromoteDialog.tsx:598), "Skapa genbanksintyg" (OversiktTab.tsx:220, avstängd), "Utfärda digitalt intyg" (`addRabbit.issueCertificate`, används inte) | Öppen fråga |
| Sälja: rubrik | "Rapportera som död eller sälja kanin" (manual:211) | "Sälja {namn} {nummer}" (individual_sell.tsx:168) | "{{name}} byter hem" (`individual.sell.title`), "Flytta eller sälja" (`individual.sell.badge`) | "Sälj {{name}}", "Försäljning" (samma nycklar) | Sälj |
| Sälja: menyval | "sälj individ" (manual:216), "Sälj kanin" (manual:218) | "Sälj individ" (individual_view.tsx:467) | samma som nu | "Sälj individ" (`individual.edit.sellIndividual`) | Öppen fråga |
| Sälja: knapp | "Sälj" (manual:222) | "Sälj" (individual_sell.tsx:233) | "Bekräfta flytt" (`individual.sell.confirmButton`) | "Bekräfta försäljning" (`individual.sell.confirmButton`) | Sälj |
| Säljdatum | "försäljningsdatum" (manual:219) | "Köpdatum" (individual_sellingform.tsx:101), "Säljdatum" (felmeddelande, individual_add.tsx:428) | "Försäljningsdatum" (`individual.sell.dateLabel`) | "Säljdatum" (`individual.sell.dateLabel`) | Säljdatum (beslut 2026-10-30) |
| Såld | "dit kaninen ska flytta", "flyttat" (manual:219–220) | "Individen har flyttats till besättning" (individual_sell.tsx:249), "flyttas till ... för flytten" (individual_sell.tsx:174–175) | "{{name}} har flyttats till {{herd}}." (`individual.sell.moved`) | "{{name}} är såld till {{herd}}." (`individual.sell.moved`); "Flytt", "Flyttad hit" i historiken (herdTracking.ts:58, 65) | Såld; flytt bara i historiken |
| Försäljning i ändringsloggen | – | – | "Överlåtelse" (auditLabels.ts:158) | "Försäljning" (auditLabels.ts:158) | Försäljning |
| Rollen genbanksansvarig | "genbanksansvarig" (manual:178, 201) | "Manager" (userForm.tsx:83, individual_view.tsx:453), "Endast Manager" (field_with_permission.tsx:73), "genbanksansvarig" (individual_form.tsx:131) | "Manager" (KontoCard.tsx:124), "Genbanksansvarig" (RolePicker.tsx:76) | "Genbanksansvarig" (KontoCard.tsx:124, RolePicker.tsx:76), "Endast genbanksansvarig" (min-besattning-ui.tsx:244) | Genbanksansvarig |
| Övriga roller | "vanlig användare" (manual:188) | "Owner", "Viewer" (userForm.tsx:82, 84) | samma som nu | "Besättningsägare", "Granskare", "Administratör", "Matrikeladministratör" (RolePicker.tsx:74–78) | Besättningsägare bara som rollnamn i admin, Uppfödare i text (beslut 2026-10-30) |
| Fliken med kullar | "Kullar och parningar" (manual:125, 128) | "Kullar och parningar" (herd_view.tsx:141, individual_form.tsx:290) | "Kullar & parningar" (min-besattning-ui.tsx:13), "Kullar & Parningar" (`breeding.listTitle`, används inte) | "Kullar och parningar" (min-besattning-ui.tsx:13, `breeding.listTitle`, används inte) | Kullar och parningar (beslut 2026-10-30) |
| Fliken med kaniner | "Lista över individer" (manual:126) | "Lista över individer" (herd_view.tsx:134) | samma som nu | "Kaniner" (min-besattning-ui.tsx:12) | Kaniner (beslut 2026-10-30) |
| Min besättning | "Min besättning" (manual:78) | "Min besättning", "Mina besättningar" (navigation.tsx:207–208) | "Min Besättning" (`sidebar.minBesattning`), "Min besättning" (`individual.breadcrumb.myHerd`) | "Min besättning" (`sidebar.minBesattning`, `individual.breadcrumb.myHerd`) | Min besättning (beslut 2026-10-30) |
| Alla kaniner | "Genbanker" (manual:38) | "Genbanker" (navigation.tsx:183), "Individer i {genbank}" (genebank_view.tsx:42) | "Alla Kaniner" (`sidebar.allaKaniner`, `explorer.title`), "Alla kaniner" (`individual.breadcrumb.allRabbits`) | "Alla kaniner" (`sidebar.allaKaniner`, `explorer.title`, `individual.breadcrumb.allRabbits`) | Alla kaniner (beslut 2026-10-30) |
| Besättningshistorik | "besättningshistoria" (manual:216) | "Besättningshistoria" (individual_view.tsx:416) | "Besättningshistoria" (HerdHistorySection.tsx:36), "Besättningshistorik" (auditLabels.ts:10) | "Besättningshistorik" (HerdHistorySection.tsx:36, auditLabels.ts:10) | Besättningshistorik (beslut 2026-10-30) |
| Rapportera död | "Rapportera som död" (manual:216, 228) | "Rapportera som död", "Uppdatera dödsdatum" (individual_view.tsx:502, 501) | samma som nu | "Rapportera död" (`individual.death.reportAction`) | Rapportera död (beslut 2026-10-30) |
| Dödsorsak | "Anteckningar om kaninens död" (manual:232) | "Anteckningar om kaninens död" (individual_death.tsx:220), "Dödsnotering" (individual_view.tsx:307), "Dödsanteckning" (filter_table.tsx:366) | "Dödsorsak" (`individual.edit.deathNote`), "Dödsnotering" (`individual.edit.deathNoteLabel`) | "Dödsorsak" (`individual.edit.deathNote`, `individual.edit.deathNoteLabel`, NotesSection.tsx:65) | Dödsorsak (beslut 2026-10-30) |
| Kullens storlek | – | "Kullstorlek" (breeding_form.tsx:823), "Antal födda i kullen" (individual_form.tsx:375), "Levande i kullen efter 6v" (breeding_form.tsx:837) | samma som nu | "Antal födda", "Antal vid 6 veckor" (`breeding.totalBorn`, `breeding.aliveAt6w`), "Levande i kullen efter 6 veckor" (`addRabbit.litterSize6w`), "Kullstorlek 6v" (RabbitExplorer.tsx:257) | Öppen fråga |
| Okänt kön | – | "Okänd" (individual_form.tsx:104) | "Okänt" (`bunnyEdit.sexUnknown`, IndividualCard.tsx:356), "Okänd" (`addRabbit.sexUnknown`) | "Okänt" (`bunnyEdit.sexUnknown`, `addRabbit.sexUnknown`, IndividualCard.tsx:356) | Okänt (beslut 2026-10-30) |
| Avkomma | – | "Avkomma", "Avkomma i genbanken" (individual_view.tsx:553–554) | samma som nu | "Avkommor" (`breeding.offspring`) | Öppen fråga |
| Färgfält | "Färganteckning" (manual:148) | "Färg på buken" (individual_form.tsx:472), "Klofärg(er)" (individual_form.tsx:509), "Avvikande hårlag" (individual_form.tsx:549) | samma som nu | "Bukfärg", "Klofärg", "Avvikande hårlag" (`addRabbit.bellyColor`, `addRabbit.clawColor`, `addRabbit.hairNotes`), "Hårlag" (`individual.edit.hairNotes`) | Öppen fråga |
| Föräldrar | "mor", "far" (manual:70) | "Mor", "Far" (breeding_form.tsx:720, 755), "Moder", "Fader" (filter_table.tsx:308, 327) | "Moder", "Fader" (`breeding.mother`, `breeding.father`), "Mor", "Far" (PedigreeTree.tsx:171) | "Mor", "Far" (`breeding.mother`, `breeding.father`, RabbitExplorer.tsx:218, 234, PedigreeTree.tsx:171) | Mor, Far (beslut 2026-10-30) |
| Provparning | "Provparning", "provpara" (manual:68, 61) | "Provparning" (navigation.tsx:194) | samma som nu | "Provparning" (`sidebar.provparning`), "Provpara" (`individual.edit.testMate`), "testparning" (bli-genbank/page.tsx:112, stamboken-online/page.tsx:45) | Öppen fråga |
| Registrera | "registrera/skapa intyg" (manual:145) | "Registrera" (navigation.tsx:248) | samma som nu | "Registrera" (`litterRoster.registerButton`), "Skriv in ungen i stamboken" (`litterRoster.registerTooltip`) | Öppen fråga |
| Oregistrerade ungar | "Oregistrerade djur" (manual:30), "Skapa oregistrerade kaniner" (manual:141) | "Visa oregistrerade djur" (herd_view.tsx:184), "Skapa oregistrerade kaniner" (breeding_form.tsx:890) | samma som nu | "Kullista" (`litterRoster.title`), "Lägg till ungar" (`litterRoster.add`), "Behålls oreg." (`bunny.fate.kept_unregistered`) | Öppen fråga |
| Släktskap | "släkt" (manual:61) | "Genomsnittligt släktskap/ Mean Kinship" (individual_view.tsx:255) | samma som nu | "MK — Genomsnittlig medelkinship", "kinship-koefficienten" (GeneticsInfoPanel.tsx:34, 80) | Öppen fråga |
| Testmiljön | "Testsystemet", "den skarpa sidan" (manual:238–239) | "OBS DETTA ÄR TESTSYSTEMET!" (navigation.tsx:345) | samma som nu | "testmiljön", "riktiga stamboken" (AvatarMenu.tsx:199–200), "TESTMILJÖ" (DemoBanner.client.tsx:21), "Demosynkronisering" (SystemPillNav.tsx:23) | Öppen fråga |
| Webbkurs | – | "Validerad" (userForm.tsx:353) | samma som nu | "Webbkurs genomförd (validerad)" (UserEditClient.tsx:366) | Öppen fråga |
| Administrationen | – | "Administrera" (navigation.tsx:259) | samma som nu | "Administration" (`sidebar.adminSection`) | Öppen fråga |
| Medlemsregistret | "medlemsregistret" (manual:91) | "medlemsmatrikeln" (herdForm.tsx:472) | samma som nu | "Matrikel" (`sidebar.matrikel`), "Medlemsmatrikel" (matrikel/page.tsx:61) | Öppen fråga |
| Raserna i löptext | "gotlandskaninen och mellerudskaninen" (manual:17), "Gotlandskaninen" (manual:62), "Gotlandkanin" (manual:219) | "genbanksbesättning för Gotlandskanin" (static_pages.tsx:215) | "Gotlandskanin och Mellerudskanin" (`landing.heroSubtitle`) | "gotlandskanin och mellerudskanin" (`landing.heroSubtitle`) | gemener i löptext |

## Ord som bara finns i ett av systemen

Varje påstående är kontrollerat med sökning i det andra gränssnittet.

Bara i gamla Stamboken:

- Rapportera vikt och hull: "Rapportera vikt och hull", "Lägg till viktmätning", "Lägg till hullmätning" (individual_weighthull.tsx:325, 417, 505). Nya UI visar bara "Senaste vikt" och "Senaste hull" (HealthSection.tsx:84, 109); vikt och hull som ord finns alltså i båda.
- Årsrapportens formulär: "Avelsår", "Jag uppfyller villkoren för genbanksstöd", "Sjukdomsfall" (YearlyReportForm.tsx:425, 651, 677). Nya UI har bara menyvalet "Årsrapportera" med "Kommer snart" (`individual.edit.annualReport`, `individual.edit.comingSoon`).
- Kryssrutorna "Visa aktiva djur", "Visa inaktiva djur", "Visa djur i inaktiva besättningar", "Visa döda djur" (genebank_view.tsx:46–68). Nya UI filtrerar med "Status" (`explorer.status`).
- "Uppdatera dödsdatum" (individual_view.tsx:501). Nya UI ångrar i stället dödsrapporteringen.
- Provparningens omdöme "Föreningen rekommenderar parningen" / "EJ parningen" (testbreed_recommendation.tsx:150, 155). Nya UI säger "Bra", "Utred närmare", "Hög inavel" (provparning.ts:461–463).

Bara i nya Stamboken:

- Kullista, Öde, Preliminärt nummer (`litterRoster.title`, `litterRoster.fateLabel`, `litterRoster.provisionalNumber`). Gamla Stambokens motsvarighet var "Skapa oregistrerade kaniner".
- Ändringshistorik, Ångra, Återställ, Visa ångrade, Korrigera historik (individual-detail.tsx:733, AuditTimeline.tsx:201, HerdHistorySection.tsx:98, HerdTrackingCorrectionDialog.tsx:152).
- Statusarna Slaktad, Avlivad, Försvunnen (RabbitExplorer.tsx:50–52) och märkena Kastrerad och Köpt (KaninerTab.tsx:102, IndividualCard.tsx:467). Gamla UI visar bara Aktiv, Inaktiv och Död (individual_view.tsx:554–555).
- Rollerna Skötare, Matrikeladministratör, Huvudmedlem, Familjemedlem (PersonerClient.tsx:296, RolePicker.tsx:75, matrikel/types.ts:85–86) och genetiksidans mått (Ne, FGE, ΔF i GeneticsInfoPanel.tsx).
- Flera hanar i samma provparning: "Lägg till en hane till" (ProvparningClient.tsx:483).

Finns i båda, trots att det kan se nytt ut: **Verifiera intyg** (gamla: ladda upp PDF-filen,
certificate_verification.tsx:155; nya: QR-kod eller länk, verifiera/[uuid]/page.tsx:145),
**Provparning** (navigation.tsx:194, `sidebar.provparning`) och **Ögonfärg** (individual_form.tsx:499,
`addRabbit.eyeColor`).

## Beslut

Projektägaren beslutade 2026-10-30:

1. **Död** är en egen status; en död kanin är inte inaktiv.
2. **Säljdatum**, inte försäljningsdatum eller köpdatum.
3. **Kullar och parningar** med "och", aldrig "&", och kullar först.
4. **Uppfödare** när texten vänder sig till personen, i löptext och rubriker; **Besättningsägare** bara som rollens namn i adminpanelen.
5. **Rapportera död**, inte rapportera som död.
6. **Besättningshistorik**, inte besättningshistoria.
7. **Mor** och **Far** som etiketter (formulären för parning och kull, Alla kaniner, släktträdet), inte Moder och Fader; intygets PDF-mall följer pappersintyget och ändras inte.
8. Fliken **Kaniner** och menyvalet **Alla kaniner**; menyval skrivs med gemen efter första ordet: **Min besättning**, **Alla kaniner**.
9. **Dödsorsak**, inte dödsnotering eller dödsanteckning.
10. **Okänt** om kön, eftersom kön är ett t-ord; **Okänd** där ordet gäller ett en-ord, som okänd mor eller okänd kanin.
11. **Registrerad kanin** är en kanin som skrivits in i stamboken med intyg, pappersintyg eller digitalt intyg, och därmed fått sitt individnummer. Att registrera utan intyg går inte längre.

Projektägaren beslutade 2026-11-12:

12. **Brokig**, inte scheck, om vita kaniner med färgade fläckar, som i färgatlasen och färgnamnen.

## Öppna frågor

Inget av detta är beslutat. En rad per fråga med alternativen.

- **Aktiv**: gamla manualen nämner inte kastrering (manual:32); nya koden kräver att kaninen inte är kastrerad.
- **Kaninens nummer i gamla manualen**: "genbanksnummer" (manual:200, 214) mot "individnumret" (manual:147) och kanoniska Individnummer.
- **Besättningsnummer**: legacy-UI säger också "Genbanksnummer" (YearlyReportForm.tsx:384) och "Besättnings-ID" (herdForm.tsx:392); nya UI har kvar "Besättnings-ID" i ett felmeddelande (BesattningsuppgifterCard.tsx:98).
- **Menyvalet**: "Sälj individ" (båda UI) eller "Sälj kanin" (manual:218).
- **Flytta**: gamla manualen (manual:219–220) och gamla dialogen (individual_sell.tsx:174) säger flytta om en försäljning; kanon tillåter flytt bara i historiktext. USER_MANUAL.md har rubriken "Sälja eller flytta en kanin".
- **Intygsnummer**: ett ord för både pappersnumret och det digitala numret (nya UI) eller två ("Nummer på pappersintyg" mot "Intygsnummer", cert_autocomplete.tsx:104, individual_form.tsx:193).
- **Intygstyp i formuläret**: kanon säger Pappersintyg och Digitalt intyg, men valet under rubriken Intyg visar "Papper"/"Digitalt" i båda UI (cert_autocomplete.tsx:31–32, `addRabbit.certificatePaper`, `addRabbit.certificateDigital`): byta till de långa formerna eller godta kortformen i valet.
- **Synonymer till intyg**: genbanksintyg (båda UI och manualen), stamtavla, stamtavleintyg (IndividualCard.tsx:404, `addRabbit.certificateTooltip`).
- **Utfärda**: "Skapa nytt intyg", "Beställ intyg", "Skapa genbanksintyg" eller "Utfärda digitalt intyg".
- **Registrera** eller **Skriv in** (`litterRoster.registerTooltip`).
- **Kullens storlek**: "Antal födda" eller "Kullstorlek"; "Antal vid 6 veckor", "Levande i kullen efter 6 veckor" eller "Kullstorlek 6v".
- **Färgfält**: "Bukfärg" eller "Färg på buken"; "Klofärg" eller "Klofärg(er)"; "Hårlag" eller "Avvikande hårlag" (nya UI har båda).
- **Avkomma i genbanken** (legacy) eller **Avkommor** (nya UI).
- **Provparning** eller **testparning** (publika sidor).
- **Oregistrerade djur** (manual:30) eller **oregistrerad unge** och **kullista**.
- **Släktskap**: "Genomsnittligt släktskap", "MK — Genomsnittlig medelkinship" eller "släktskapskoefficient", som inget av gränssnitten använder.
- **Testmiljön**: "Testsystemet" och "den skarpa sidan" (manual:238–239, navigation.tsx:345) eller "testmiljön" och "riktiga stamboken"; ska admin säga "Demosynkronisering" eller "testmiljö"?
- **Webbkurs genomförd** eller **Validerad**.
- **Administration** eller **Administrera**.
- **Matrikel**, **medlemsmatrikel** eller **medlemsregistret** (manual:91).
- **GX1/MX1**: gamla manualen säger kaniner "som sålts med intyg" (manual:25); båda UI säger att en kanin utan intyg bara kan säljas dit (individual_sell.tsx:178, `individual.sell.unregisteredInfo`).
- **Hullskala**: "Låg/Normal/Hög" (individual_weighthull.tsx:178–180, HealthSection.tsx:20–22) eller "Under/Normal/Över" (BatchRabbitUpdateForm.tsx:468–478).
- **Rasnamn och stavning i gamla manualen**: versal i löptext (manual:62, 150, 219) och stavfel "genbaksansvarig" (manual:84, 119), "genbaknsansvarig" (manual:116), "innavelskoefficient" (manual:65), "Gotlandkanin" (manual:219).
- **DEVELOPMENT_GUIDE.md** kallar kaninens nummer "Genbanksnummer" (rad 95 och 115), mot kanoniska Individnummer.
