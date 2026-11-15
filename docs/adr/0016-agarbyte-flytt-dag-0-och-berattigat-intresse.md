---
status: "proposed"
date: 2026-11-06
decision-makers: Jonas Hagberg; styrelsen per capsulam för köparens uppgifter
consulted: styrelsen, genbanksansvariga
informed: medlemmarna, genom styrelseförslaget om intyg och överlåtelsebevis
---

# ADR-0016: Ägarbyte flyttas dag 0 med avvisa, och köparen sparas på berättigat intresse

## Kontext och problem

Stamboken 2 flyttar en kanin till köparens besättning i samma ögonblick som
säljaren registrerar försäljningen ("flytt dag 0"). Överlåtelseflödet var
specat i två steg, där köparen bekräftar med en engångskod, och specen för
ägarhistoriken (beslut 2026-10-02) sa att en köpare utanför föreningen bara
får sparas med köparens eget samtycke, fångat när koden löses in. När
styrelseförslaget om intyg och överlåtelsebevis arbetades om i oktober 2026
öppnades två frågor:

1. Ska kaninen ligga i ett väntläge tills köparen bekräftat, så att en
   säljare inte kan lägga in kaniner i andras besättningar?
2. Måste föreningen ha köparens samtycke för att spara namn och kontakt?

## Beslutsdrivare

* Ett ägarbyte ska gå igenom utan att någon loggar in. 2025 gick 394 av 655
  ägarbyten till köpare utanför föreningen, som inte har något konto att
  bekräfta med.
* Så lite manuellt arbete som möjligt. Av 186 ägarbyten mellan medlemmar
  2025 lade genbanksansvarig in 132 från papper, och köparen registrerade
  inga.
* Registret ska veta vem som håller varje genbanksdjur, för smittskydd och
  för återköp till genbanken, 75 kaniner om året.
* Allt som går att göra i Stamboken ska gå att göra på papper, och registret
  är sanningen.
* Felplaceringar är sällsynta: två flyttar gick tillbaka inom 30 dagar 2025.
  Det är ett golv, eftersom rättelser som raderar raden inte syns.
* En dataskyddsutredning (2026-10-26) visade att både samtycke och berättigat
  intresse (art. 6.1 f) är möjliga grunder, men inte avtal (art. 6.1 b).

Siffrorna är sammanräknade ur registret och innehåller inga uppgifter om
enskilda djur eller personer.

## Alternativ

Flytten:

* Väntläge tills köparen bekräftar
* Flytt dag 0 med avisering och avvisa

Köparens uppgifter:

* Samtycke, som specen för ägarhistoriken sa tidigare
* Berättigat intresse för namn och ort, kryss för kontaktuppgifter

## Beslut

Valda alternativ: "Flytt dag 0 med avisering och avvisa", eftersom ägarbytet
går igenom utan att någon loggar in och mottagaren ändå kan vända en
felplacering; och "Berättigat intresse för namn och ort, kryss för
kontaktuppgifter", eftersom registret då vet vem som håller varje
genbanksdjur även när köparen aldrig kontaktar föreningen.

Konkret:

* Ett ägarbyte är registrerat eller ogiltigförklarat (void). Det finns inget
  tillstånd "bekräftad". Kontrollsidan är öppen för alla och visar att
  intyget är äkta och "överlåten <månad och år>", aldrig dag och aldrig
  namn. Uppfödarens namn visas bara om uppfödaren valt det.
* Mottagande besättning aviseras och kan avvisa inom 30 dagar från
  registreringen. Avvisa är en void av raden, med behörigheten knuten till
  mottagande besättning, och med samma villkor som säljarens ångra inom 7
  dagar: ingen senare aktiv rad, ingen parning eller kull registrerad på
  kaninen. Efter det ändrar bara genbanksansvarig. Ångra och avvisa är
  regler i registret, inte styrelsebeslut.
* Säljaren, eller den som lägger in en inskickad blankett från
  granskningskön, skapar `BuyerContact` med namn och ort. Postadress, e-post
  och telefon sparas bara om köparen kryssat "Ja, föreningen får spara min
  adress, e-post och telefon så länge jag har kaninen". Rutan står före
  raderna på beviset, och raderna fylls i bara efter kryss. Ifyllda rader
  utan kryss registreras inte, eftersom pärmen hos genbanksansvarig också är
  ett register.
* Kontaktuppgifterna gallras när kaninen byter ägare igen, namn och ort fem
  år efter att de lades in. En separat ruta ger samtycke till kontakt om
  medlemskap.
* Det tidigare kravet på samtycke innan genbanksansvarig får se köparen
  utgår. Kvar står att köparen aldrig skrivs i fritext och aldrig på
  intyget. Köparen informeras enligt art. 14 på överlåtelsebeviset; en
  medlem har redan godkänt behandlingen i medlemsansökan, och en köpare med
  konto ser ägarbytet i aviseringen. Vid invändning raderas alla köparens
  uppgifter.
* En köpare med konto behöver inget papper: säljaren väljer köparens
  besättning, och köparen aviseras och kan avvisa. Vill någon ha papper
  skriver den ut beviset ur Stamboken.
* Intyget får bara laddas ner och förhandsvisas av nuvarande ägare,
  uppfödaren (ursprungsbesättningen), genbanksansvarig och admin. Intyget
  är ingen värdehandling: registret gäller, och beviset bevisar köpet.
* Ur överlåtelseflödet utgår överlåtelsekoden (TransferToken, aldrig
  byggd), engångslösenordet, inlösen, tillstånden CONFIRMED och STALE och
  eskaleringen. Kvar blir `BuyerContact` med gallring efter fem år,
  kontrollsidan, aviseringen, granskningskön för inskickade blanketter och
  rollen för den som lägger in blanketter åt andra.

### Konsekvenser

* Bra, eftersom ett ägarbyte aldrig kräver att köparen loggar in. Målet att
  fler ska använda Stamboken skadas inte av att köparen står utanför.
* Bra, eftersom överlåtelseflödet krymper till `BuyerContact`,
  kontrollsidan, aviseringen, granskningskön och rollen för den som lägger
  in blanketter. Inga koder, inget engångslösenord, ingen eskalering.
* Bra, eftersom pappersvägen och den digitala vägen har samma uppgifter och
  samma regler; pärmen hos genbanksansvarig omfattas av samma avvägning och
  samma lag.
* Neutralt, eftersom specen för ägarhistoriken ändras: samtyckeskravet och
  fältet manager_disclosure_consent utgår, och specen för
  överlåtelseflödet ersätts i de delar som rör bekräftelse och inlösen. Båda
  är bara spec; ingen kod behöver tas bort.
* Neutralt, eftersom granskningskön bara får skriva det den centrala
  skrivaren godtar ([ADR-0015](0015-individual-write-commands.md)). Sena
  blanketter med datum före senaste rad går till genbanksansvarigs kommando
  för rättelser.
* Dåligt, eftersom reglerna för ägarhistoriken får två nya undantag: en
  överlåtelse från GX1 till GX1 utan besättningsbyte, när någon utanför
  föreningen säljer till någon annan utanför föreningen (GX1 är besättningen
  för kaniner sålda utanför föreningen), och void med behörigheten knuten
  till mottagande besättning.
* Dåligt, eftersom intresseavvägningen aldrig prövas av någon utanför
  föreningen förrän en köpare invänder eller klagar.
* Dåligt, eftersom ett nedladdat bevis med förfalskad underskrift kan flytta
  en kanin via granskningskön. Säljarens besättning aviseras när kön skriver
  raden, så det upptäcks inom säljarens ångrafönster, men bara om säljaren
  har konto. Saknar säljaren konto går aviseringen till kön, och
  genbanksansvarig hör av sig.

### Bekräftelse

* Nedladdning och förhandsvisning av intyget går genom
  `User.can_view_certificate`. Det är genomfört och prövas av testerna
  `test_viewer_cannot_download_or_preview` och
  `test_breeder_manager_admin_can_preview` i
  `app/tests/test_certificates_v2_api.py`.
* Avvisa och granskningsköns skrivningar byggs som kommandon genom den
  centrala skrivaren ([ADR-0015](0015-individual-write-commands.md)), med
  behörigheten enligt [ADR-0014](0014-authorization-model.md), och får tester
  för villkoren ovan när de byggs.
* Styrelsen stämmer av intresseavvägningen mot Integritetsskyddsmyndighetens
  vägledning innan beslut, och behandlingen förs in i förteckningen över
  behandlingar (art. 30).
* `scripts/check-adr-refs.py` kontrollerar att identifierare som nämns här
  finns i koden.

## För- och nackdelar med alternativen

### Väntläge tills köparen bekräftar

* Bra, eftersom inget fel kommer in tyst. En felskriven besättning, till
  exempel två omkastade siffror, upptäcks innan kaninen syns hos en
  främling.
* Dåligt, eftersom 60 % av köparna inte har något konto att bekräfta med, så
  flytten till GX1 måste ske direkt ändå. Kvar att skydda är 54
  försäljningar mellan medlemmar om året.
* Dåligt, eftersom kaninen inte tillhör någon under väntan: köparen kan inte
  registrera parning, kull eller årsrapport, till exempel för en hona som
  köps dräktig.
* Dåligt, eftersom den som aldrig loggar in låser kaninen tills
  genbanksansvarig tömmer en kö. Det bygger om papperskön till en kö för
  digitala försäljningar.

### Flytt dag 0 med avisering och avvisa

* Bra, eftersom skyddet mot felplacering blir detsamma utan väntläge:
  mottagaren ser kaninen, får ett meddelande och kan vända flytten med ett
  klick.
* Bra, eftersom säljarens namn står på raden, så allt är spårbart. Flytt dag
  0 och säljarens ångra inom 7 dagar gäller oförändrade, och `transfer_id`
  förblir NULL.
* Dåligt, eftersom en kanin kan ligga i fel besättning i upp till 30 dagar om
  mottagaren inte reagerar.
* Dåligt, eftersom en medlem utan konto inte aviseras; hon får höra av sig
  till genbanksansvarig.

### Samtycke, som specen för ägarhistoriken sa tidigare

* Bra, eftersom det inte finns några invändningar att pröva; köparen har
  själv valt.
* Dåligt, eftersom samtycke bara kan ges av köparen själv, vilket kräver att
  köparen löser in en kod. De flesta köpare utanför föreningen gör det
  aldrig, så registret får hål precis där spårbarheten behövs.
* Dåligt, eftersom hela kodkedjan måste byggas och underhållas innan ett
  enda namn kan sparas.

### Berättigat intresse för namn och ort, kryss för kontaktuppgifter

* Bra, eftersom säljaren skriver in köparen som på pappret i dag, med samma
  fält på skärm och blankett och utan kodmaskineri.
* Bra, eftersom intresseavvägningen håller: fyra fält, synliga för ett
  fåtal, fem år, rätt att invända, rätta och radera. Köparen informeras på
  det papper hon får i handen.
* Dåligt, eftersom föreningen måste kunna visa avvägningen och hantera
  invändningar; en köpare kan tvinga bort sina uppgifter.
* Dåligt, eftersom informationen enligt art. 14 måste nå köparen inom en
  månad, vilket kräver att säljaren ger beviset vid överlämningen.

## Mer information

Delarna om köparens uppgifter väntar på styrelsens beslut per capsulam.
Säger styrelsen nej faller de tillbaka till samtycke som tidigare, medan
flytt dag 0 med avvisa står kvar. Det enda styrelsen beslutat tidigare i
frågan är att föreningen har digitala intyg.

Relaterade beslut: [ADR-0014](0014-authorization-model.md)
(behörighetsmodell) och [ADR-0015](0015-individual-write-commands.md)
(kommandon per avsikt). Specen för ägarhistoriken (2026-04-11, beslut
2026-10-02), specen för överlåtelseflödet (2026-07-06), helhetsdesignen
"Ägarbyte och intyg" (2026-10-28) och dataskyddsutredningen om intyg och
överlåtelse (2026-10-26) ligger i föreningens privata driftrepo.

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-10-28 | Jonas Hagberg | Skapad |
| 2026-10-29 | Jonas Hagberg | Två rättsliga grunder (namn och ort 6.1 f, kontakt 6.1 a med kryss före raderna), månad på kontrollsidan, utskriftsrätt för intyget, ångra och avvisa som registerregler |
| 2026-11-06 | Jonas Hagberg | MADR-format inför publikt repo, interna beteckningar förklarade, månad och år på kontrollsidan, spärren för nedladdning av intyget genomförd |
