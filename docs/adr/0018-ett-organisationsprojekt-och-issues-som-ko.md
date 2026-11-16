---
status: "proposed"
date: 2026-11-10
decision-makers: Jonas
---

# ADR-0018: Ett publikt organisationsprojekt, med issues som enda kö

## Kontext och problem

Arbetet syns i dag på tre ställen. Det första är PR:erna: 52 i
stamboken-drift den senaste månaden, alla från samma konto. Det andra är 99
todo-filer i driftrepots planeringskatalog, och det tredje en
statusfil som bara finns på utvecklarens dator. Issues används nästan inte,
och organisationen har inget GitHub-projekt. Styrelsen och volontärerna ser
inte vad som pågår eller väntar på dem, och den som vill bidra hittar ingen
kö. Frågan är om ett projekt, två projekt (ett publikt och ett internt) eller
inget projekt ger minst dubbelarbete.

## Beslutsdrivare

* Varje sak förs in på ett enda ställe.
* Persondata och driftuppgifter blir aldrig publika
  ([ADR-0013](0013-public-code-private-operations.md), regel 1).
* Agenterna håller issues och projekt uppdaterade, inte människor.
* Organisationen har gratisplanen, som ger ett enda auto-add-flöde.

## Alternativ

* Ett publikt organisationsprojekt över alla repon, med issues som enda kö (valt)
* Två projekt, ett publikt och ett internt: avvisat. GitHub visar objekt
  från ett privat repo bara för den som har åtkomst till repot, så ett
  publikt projekt räcker. Två projekt betyder att allt läggs in och flyttas
  två gånger.
* Inget projekt, med todo-filerna och statusfilen som i dag: avvisat,
  eftersom kön då bara kan läsas av utvecklaren. Det är ändå rätt val om
  todo-filerna inte läggs ner, eftersom projektet annars blir ett fjärde
  ställe.
* Ett GitHub-projekt riktat till medlemmarna: avvisat, eftersom medlemmarna
  inte finns på GitHub.

## Beslut

Valt alternativ: "Ett publikt organisationsprojekt", eftersom det ger en kö
som andra kan läsa, utan att något förs in två gånger och utan att
driftrepots innehåll blir publikt. Beslutet förfinar ADR-0013, som lägger Project i det publika
repot. Projektet ligger på organisationen, så att det kan visa issues från
båda repona.

Regler:

1. Issues är den enda kön. Drift, datarättningar och allt som rör enskilda
   djur, uppfödare eller medlemmar blir issues i stamboken-drift. Kod och
   funktioner utan persondata blir issues i stamboken. Säkerhetshål blir
   issues i stamboken-drift tills de är rättade, eftersom ett publikt issue
   visar hur hålet utnyttjas. Kräver en driftfråga kod blir det två olika
   issues: drift-issuen länkar till kodissuen, som inte nämner datat.
2. Projektet "Stamboken" på organisationen är publikt och har bara fältet
   Status. Det har två vyer: en tavla per status, och "Väntar på beslut"
   med etiketten `beslut` för det som styrelsen eller en uppfödare ska
   avgöra.
3. Projektet har inga utkast. Ett utkast hör inte till något repo och syns
   troligen för alla som ser projektet. Det är inte provat, se Bekräftelse.
4. Dessa inbyggda flöden är på: stängd blir Klart, mergad blir Klart, nya
   objekt läggs i Att göra, stängda issues arkiveras två veckor efter
   senaste ändringen, och auto-add hämtar från stamboken-drift med
   filtret `is:issue`. Flödena pekar på statusvalen, så byter ett val namn
   måste flödena ställas in igen. PR:er läggs inte till. De stänger sina
   issues med "Closes #n".
5. Agenten lägger till issues från stamboken med `gh project item-add`,
   eftersom gratisplanen bara har ett auto-add-flöde.
6. Todo-filerna i driftrepot läggs ner. Levande poster blir issues och resten
   stängs. Katalogen får en README som pekar på projektet. Statusfilen
   behåller bara sin daterade logg, och avsnitten om kö, ordning och
   parkerat tas bort.
7. Agenterna skapar, länkar och stänger issues. Ingen ska behöva flytta
   kort för hand.
8. Medlemmarna informeras i forumet, med ett inlägg när en release
   innehåller något de märker. RSS från releaserna kopplas på först när
   releaserna har text skriven för medlemmar. I dag är release-texten tom.

### Konsekvenser

* Bra, eftersom kön går att läsa utan att fråga utvecklaren, och styrelsen
  ser vad som väntar på den.
* Bra, eftersom den som vill bidra hittar öppna issues i det publika repot.
* Dåligt, eftersom GSD-skillens todo-kommandon slutar vara kön, och de 99
  posterna måste gås igenom en gång.
* Dåligt, eftersom den som saknar GitHub-konto med läsrätt på driftrepot
  bara ser de publika issues. Driftfrågor som väntar på styrelsen syns inte
  för den.
* Neutralt: GitHub for Nonprofits ger Team-planen gratis, med fem
  auto-add-flöden, om föreningen godkänns. Beslutet bygger inte på det.

### Bekräftelse

Beslutet blir `accepted` först när detta har gått igenom:

1. **Integritet.** Projektet görs publikt med en issue från stamboken-drift
   och ett utkast, och projektsidan hämtas utloggad. Godkänt är att varken
   rubrik eller fältvärde från drift-issuen syns. Syns utkastet gäller
   regel 3 som den står. Syns drift-issuen görs projektet privat, och
   publiken får bara forumets releaseinlägg.
2. **Automatik.** En test-issue i stamboken-drift hamnar i projektet utan
   manuellt steg och flyttas till Klart när en PR med "Closes #n" mergas.
3. **Riktig användare.** En styrelseledamot får länken och tre frågor om
   läget. Godkänt är att hen svarar rätt utan att fråga utvecklaren.
4. **Efter två veckor.** Driftrepots todo-katalog har inte fått några nya
   filer, och ingen sak finns både som issue och i statusfilens kö.

## Mer information

* GitHub Docs, [Managing visibility of your projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/managing-your-project/managing-visibility-of-your-projects):
  "Only people with access to a private repository will be able to view
  project items from that private repository."
* GitHub Docs, [Adding items automatically](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically):
  auto-add är begränsat till ett flöde på GitHub Free och fem på Team.
  Befintliga objekt läggs inte till i efterhand.
* GitHub Docs, [Using the built-in automations](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations).
* [GitHub for Nonprofits](https://docs.github.com/en/nonprofit).

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-11-10 | Jonas | Skapad som förslag |
