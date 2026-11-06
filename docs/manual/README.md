# Så underhålls användarmanualen

Manualen är `docs/USER_MANUAL.md`; skärmbilderna ligger här. Tre saker håller den i
takt med gränssnittet.

## 1. Täckningsgrind: varje sida har ett avsnitt

`scripts/check-manual-coverage.sh` listar varje `page.tsx` under
`next-app/src/app/(app)/stamboken/` och inloggningssidan, och kräver att manualen
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

`next-app/e2e/manual/screenshots.spec.ts` tar varje bild vid 375 px (`-mobil.png`)
och 1280 px (`-desktop.png`) med `playwright.manual-screenshots.config.ts`. Den körs
aldrig i CI och aldrig mot prod eller demo.gotlandskaninen.se, bara mot den seedade
stacken ovan. Två krav utöver stacken:

- En proxy framför Next och API på samma origin (adminpanelen och genetiksidan
  behöver prod-läge respektive sökvägar med avslutande snedstreck, som nginx bevarar).
  Ett minimalt nginx räcker: `/api/` till :9090, allt annat till :3000, med
  `proxy_set_header Host $http_host` (Server Actions avvisar annars anropen).
  Adressen ges i `MANUAL_BASE_URL` (standard `http://localhost:8080`).
- Flödestesterna ovan har körts först (kullista och utfärdat intyg finns då), och
  `MANUAL_CERT_UUID` är `verification_token` för ett utfärdat intyg
  (`select verification_token from digitalcertificatev2 where is_current order by id desc limit 1`).

```bash
cd next-app && MANUAL_CERT_UUID=<uuid> pnpm exec playwright test --config playwright.manual-screenshots.config.ts
```

Bilderna visar seedens påhittade besättningar (Visby Kaninuppfödning, G1274) och
testanvändarna; inga riktiga medlemmar.

## Framtida steg: förslag på manualtext från PR-diffen

Inte byggt. Tänkt koppling: ett separat, icke-blockerande jobb i `playwright.yml`
eller ett eget workflow som på `pull_request` kör en Sonnet-agent (Claude Code
Action) med PR-diffen under `next-app/src/app/(app)/stamboken/` och
`next-app/messages/sv.json` som indata, manualens berörda avsnitt som kontext, och
uppdraget att föreslå ändrad manualtext som en PR-kommentar (aldrig en commit).
Agenten läser bara; människan klistrar in. Grinden i punkt 1 förblir det enda som
blockerar.
