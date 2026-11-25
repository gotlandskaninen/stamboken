# Så underhålls användarmanualen

Manualen är `next-app/public/stamboken/manual/USER_MANUAL.md`, och skärmbilderna
ligger i samma katalog. Hemsidan visar den på `/stamboken-online/manual`: sidan läser
filen vid varje anrop, så en ändrad manual syns efter nästa release utan något extra
steg. Länkar inom manualen skrivs som GitHubs rubrikankare (`#logga-in`).
Playwright-testet `e2e/public-manual.spec.ts` (projektet public-tests, körs i
Actions) kontrollerar på den renderade sidan att varje sådan länk, och varje länk
från Kom igång in i manualen, landar på en rubrik. Länkar till föreningens webbplats
skrivs med full adress (`https://gotlandskaninen.se/...`) så att de fungerar på
GitHub; sidan gör dem relativa. Tre saker håller manualen i takt med gränssnittet.

## 1. Täckningsgrind: varje sida har ett avsnitt

`scripts/check-manual-coverage.sh` listar varje `page.tsx` under
`next-app/src/app/(app)/stamboken/` och inloggningssidorna under `/auth/`, och kräver att manualen
innehåller kommentaren `<!-- route: /stamboken/... -->` för var och en (route-grupper
som `(dashboard)` tas bort, `[param]` behålls). Skriptet körs i CI (`lint.yml`, steget
"Manual coverage") och av `scripts/ci-local.sh` i lint-steget. Saknas ett avsnitt
stoppar det bygget och listar vilka routes som saknas.

Ny sida i appen = nytt avsnitt under rätt del i manualen med kommentaren direkt under
rubriken. PR-mallen har raden "Manual: ändrad / ingen användarvänd ändring"; stryk det
som inte gäller.

## 2. Tester som följer manualens steg

`next-app/e2e/manual/mutation-manual-flows.spec.ts` kör tre how-tos steg för steg
(stegens namn är manualens): registrera kull, registrera unge med digitalt intyg,
sälja kanin och ångra. Filen hör till projektet `mutation-tests` i
`playwright.config.ts` och körs därmed i CI:s e2e-steg och av `ci-local.sh`.
Digitala intyg laddas upp till S3, så e2e-stacken har en rustfs-container
(`.docker/rustfs`) precis som dev-stacken.

Lokalt: samma stack som `ci-local.sh` reser i steget e2e-next (postgres, redis, rustfs,
api-test-imagen med `flask seed create` och `cli.create_test_users`) plus `pnpm dev` på
:3000, sedan

```bash
cd next-app && pnpm exec playwright test e2e/manual --project=mutation-tests
```

Testet väljer ett födelsedatum per körning (den 1:a i en udda månad 2025) så att
honans dräktigheter inte överlappar; efter sex körningar mot samma seed behöver
stacken seedas om. Ändras ett steg i manualen ändras motsvarande `test.step` här.

## 3. Skärmbilder

Bilderna tas i GitHub Actions av workflowet `manual-screenshots.yml`, aldrig mot
prod eller demo.gotlandskaninen.se. Workflowet startar samma seedade stack som
Playwright-jobbet, med kodinloggning påslagen, och en nginx-proxy framför Next och
API:t på samma origin (genetiksidan behöver sina avslutande snedstreck). Sedan kör det
flödestesterna ovan, så att kullistan och ett utfärdat intyg finns, och tar alla
bilder i manualen och guiden.

- `e2e/manual/screenshots.spec.ts` tar varje sida vid 375 px (`-mobil.png`) och
  1280 px (`-desktop.png`). Ett svar med 404 eller en omdirigering till inloggningen
  stoppar testet i stället för att bli en bild.
- `e2e/manual/login-screenshots.spec.ts` tar kodinloggningen: fältet för koden,
  sidan för länken och Skapa mitt konto. Fixturen är densamma som i
  `public-code-login.spec.ts`. Den lägger in ett medlemskap och en besättning och
  körs därför sist (projektet `login`).
- `e2e/manual/matrikel-guide-screenshots.spec.ts` tar guidens bilder, se nedan.

Bilderna är Playwrights jämförelsebilder (`toHaveScreenshot`), och
`playwright.manual-screenshots.config.ts` lägger dem bredvid manualen respektive
guiden. Workflowet skriver om varje bild (`--update-snapshots=all`), så ingen bild
blir kvar från en äldre version. Git ser bara de bilder vars pixlar har ändrats.
Jobbets sammanfattning listar dem med antal ändrade pixlar, störst först
(`e2e/manual/changed-pixels.mjs`), och bilder som manualen nämner men som saknas.
Listan är också listan över avsnitt att läsa om. De ändrade bilderna laddas upp som
artefakten `manual-screenshots`.

Några sidor skiljer sig mellan två körningar av samma commit, med några hundra till
några tusen pixlar: tider (ansökningar, aktivitetslogg, aktiva användare,
ändringshistorik), intygets slumpade kod, dagens datum i dialogerna för försäljning
och död, ordningen på lika rankade kaniner på genetiksidan och flikraden i Min
besättning. De står med i listan som små ändringar. Lägg in dem tillsammans med
resten.

Så förs bilderna in:

1. Kör workflowet: Actions → Manual screenshots → Run workflow, på `main` eller på en
   gren. Det körs också av sig självt på en PR som ändrar skärmbildsskripten.
2. Hämta artefakten till en tom katalog utanför repot och kopiera bara PNG-filerna
   till de två bildkatalogerna, så att en artefakt aldrig skriver över annat i din
   checkout. Hämta bara från en grön körning på `main` eller på en gren du har
   granskat: en PR kan ändra workflowet och därmed vad artefakten innehåller. En röd
   körning laddar inte upp några bilder.

   ```bash
   tmp=$(mktemp -d)
   gh run download <run-id> -n manual-screenshots -D "$tmp"
   cp "$tmp"/next-app/public/stamboken/manual/*.png next-app/public/stamboken/manual/ 2>/dev/null
   cp "$tmp"/next-app/content/matrikel-guide/*.png next-app/content/matrikel-guide/ 2>/dev/null
   ```

   Lägg bilderna i en PR.
3. Läs om avsnitten som visar de ändrade bilderna.

Bilderna visar seedens påhittade besättningar (Visby Kaninuppfödning, G1274) och
testanvändarna, inga riktiga medlemmar.

## Guiden för matrikeln

Medlemsregistret (`/medlem`) har en egen guide för matrikeladministratörer:
`next-app/content/matrikel-guide/GUIDE.md` med skärmbilderna i samma katalog. Den
ligger utanför `public/` eftersom den bara är till för dem som sköter matrikeln:
`/medlem/guide` och bilderna under `/medlem/guide/bild/` visas bara för
administratörer och matrikeladministratörer. Andra inloggade får 404, och den som
inte är inloggad skickas till inloggningen som på alla sidor under `/medlem`.
`outputFileTracingIncludes` i `next.config.js` tar med katalogen i standalone-bygget.
Den publika manualen nämner bara att guiden finns.

Täckningsgrinden ovan kräver ett `<!-- route: /medlem/... -->` i guiden för varje
`page.tsx` under `next-app/src/app/(app)/medlem/` (utom guiden själv). Skärmbilderna
tas av `next-app/e2e/manual/matrikel-guide-screenshots.spec.ts` (projektet `guide`)
med påhittade personer, i samma workflow som manualens bilder. Specen behöver en
nystartad seedad stack: en andra körning lägger in samma personer igen.

## Vid varje release

Texten granskas vid varje release-tagg (Jonas beslut 2026-11-25). Den som taggar
kör workflowet ovan på `main` före taggen och lägger in de ändrade bilderna. Sedan
läser den manualen och guiden mot releasens PR:er och listan över ändrade bilder, och
rättar texten i samma PR. Grinden i punkt 1 är fortfarande det enda som blockerar en
PR. En agent i CI som föreslår manualtext på varje PR valdes bort samma dag.
