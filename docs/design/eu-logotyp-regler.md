# EU-logotypen — regler och hur repot uppfyller dem

Föreningens verksamhet medfinansieras av Europeiska jordbruksfonden för
landsbygdsutveckling. Det förpliktar: EU-logotypen ska visas enligt
Jordbruksverkets/EU:s regler på webbplatser som rör verksamheten.

**Källa (auktoritativ, läst 2026-08-21):**
<https://jordbruksverket.se/stod/eus-politik-for-jordbruk-och-fiske/pengar-fran-eu---anvand-eu-logotyp>

## Reglerna (Jordbruksverkets formulering)

- Om ditt projekt eller din investering får stöd från EU ska du använda
  logotypen med undertexten **Medfinansieras av Europeiska unionen**.
  För internationell marknad finns en engelsk variant,
  **Co-funded by the European Union**.
- Om andra logotyper förekommer, utöver EU-logotypen, ska EU-logotypen visas
  i **minst samma storlek, till höjd eller bredd, som den största av de andra
  logotyperna**.
- EU-logotypen **får inte ändras** eller slås samman med andra grafiska
  element eller texter. Texten får inte överlappa emblemet.
- Utöver EU-logotypen får **ingen annan symbol eller logotyp** användas för
  att visa på stödet från EU.
- EU-logotypen ska alltid placeras mot en **vit bakgrund**. Om du måste ha en
  färgad bakgrund ska emblemet omges av en **vit bård**.

## Hur repot uppfyller dem — gör SÅ HÄR

- **Använd alltid `EUFundingBadge`**
  (`next-app/src/components/public/EUFundingBadge.tsx`) när EU-stödet ska
  visas. Den renderar den **officiella, oförändrade lockupen**
  (emblem + "Medfinansieras av Europeiska unionen") på ett **vitt kort med
  padding** — det uppfyller vit-bakgrund/vit-bård-regeln även mot färgade
  ytor (paper/beige, mörka sektioner).
- **Officiella filer** (nedladdade från Jordbruksverket, ändra aldrig):
  - `next-app/public/static/img/stamboken/eu/medfinansieras-av-eu.svg`
    (stående)
  - `next-app/public/static/img/stamboken/eu/medfinansieras-av-eu-horizontal.svg`
    (liggande)
  - `next-app/public/static/img/stamboken/eu/EU-flagga-Europeiska-jordbruksfonden-färg.jpg`
    (äldre EJFLU-variant, referens)
- **Storleksregeln i praktiken:** dashboard-topbaren visar föreningens emblem
  33 px — EU-lockupen i footern (höjd 44, bredd ≈135 px) uppfyller
  "minst samma storlek till höjd ELLER bredd". På inloggningssidan är
  marginalen smalare: föreningslogotypen är 50×50 och EU-lockupen h 44 —
  regeln uppfylls enbart via bredden (≈135 ≥ 50). Krymp aldrig badgen där,
  och förstora inte föreningslogotypen, utan att räkna om. Lägger du till
  fler logotyper på en yta: kontrollera regeln igen.
- Den beskrivande meningen ("Verksamheten medfinansieras av Europeiska
  jordbruksfonden…") är **tillåten som fristående brödtext** bredvid
  lockupen — den får bara inte bakas in i eller överlappa logotypen.

## Gör ALDRIG så här

- **Rita aldrig emblemet själv** (SVG med stjärnor e.d.) och använd det som
  logotyp — det räknas som ändrad logotyp. Den handritade
  `EUFlag`-komponenten (`components/public/EUFlag.tsx`) togs bort i Phase 18
  slice 4 tillsammans med sina enda konsumenter (`components/pages/landing/`).
  Rita aldrig en ny.
- Visa aldrig enbart flaggan utan undertexten — lockupen är odelbar.
- Placera aldrig logotypen direkt mot färgad bakgrund utan vit bård.

## Var den används i dag (2026-08-21)

| Yta | Komponent | Variant |
|-----|-----------|---------|
| Landningssidan | `(public)/page.tsx` | vertikal, h 132 |
| Inloggning | `(auth)/auth/sign-in/page.tsx` | horisontell, h 44 (×2) |
| Publik footer | `components/public/PublicFooter.tsx` | horisontell, h 52 |
| Dashboard-footer | `components/shell/ShellFooter.tsx` | horisontell, h 44 |

**Medvetet utan lockup (öppen fråga):** den publika
intygsverifieringsytan `stamboken/verifiera` visar föreningslogotypen men
ingen EU-lockup. Webbplatskravet uppfylls på sajtnivå (landning + footers),
men ytan är publik och del av den finansierade verksamheten — ta ställning
vid nästa översyn av ytan (slice 3).

**OBS designunderlag:** Claude Design-handoffens footer
(`design_handoff_min_besattning/` i driftrepot) visar en förenklad flagga
utan undertext — den är **överspelad på denna punkt**. Regeln ovan vinner
över mocken; implementera aldrig mockens EU-flagga bokstavligt.
