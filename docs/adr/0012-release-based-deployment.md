---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0012: Releasebaserad driftsättning

## Kontext och problem

Deployment till produktionsservern krävde manuell SSH-inloggning och körning
av ett deployskript. Det gav ingen revisionshistorik, risk för mänskliga fel
(fel tag, glömt steg) och ingen koppling mellan GitHub Releases och vad som
faktiskt körs i produktion.

## Alternativ

* Watchtower (auto-pull): avvisat, eftersom det inte stöder legacy
  frontend-filer och ger mindre kontroll över timing och inget manuellt
  godkännande
* Webhook-lyssnare på prod: avvisat, eftersom det kräver en egen service och
  exponerar ett webhook-endpoint
* Self-hosted GitHub Actions runner: avvisat, eftersom det ger mer
  infrastruktur och löpande uppdateringar av runnern
* Varje produktionsversion är en GitHub Release (valt)

## Beslut

Valt alternativ: "Varje produktionsversion är en GitHub Release", eftersom
releasen innehåller exakt de artefakter som deployas och ger revisionshistorik.
Varje produktionsversion är en GitHub Release med version-tagg (t.ex.
`v1.2.3`). Deploy sker alltid till en namngiven version.

1. En release med tag `v1.2.3` skapas i detta repo.
2. `.github/workflows/build-and-publish.yml` bygger container-images taggade
   `1.2.3`, `1.2` och `latest`, bygger legacy-frontenderna och bifogar
   deployment-bundle och legacy-tarballs till releasen.
3. Deploy körs som en separat workflow med versionsnumret som indata. Den
   ligger i det privata driftrepot, se
   [ADR-0013](0013-public-code-private-operations.md).
4. Deploy-jobbet uppdaterar `TAG_PROD`, drar images, startar om berörda
   tjänster och väntar på hälsokontroll (`scripts/wait-healthy.sh`).

* `TAG_PROD` styr `api`, `next-app` och `cms-migrate` (samma version).
  `TAG_TEST` styr `api-test` (oberoende version) och uppdateras separat
  (deployskriptet i driftrepot, `--test v1.2.3`).
* Legacy-frontenderna byggs från
  [`gotlandskaninen/stamboken-legacy`](https://github.com/gotlandskaninen/stamboken-legacy),
  låsta på en commit.
* Den enda långlivade branchen heter `main`; releaser är taggar på den. Fram
  till exporten till det publika repot (2026-11) hette den `develop`.

| Git-händelse | Container-taggar | Effekt |
|---------|--------------|---------------|
| Tag `v1.2.3` | `1.2.3`, `1.2`, `latest`, SHA | Images + release-assets; kan deployas |
| Push till `main` | `main`, SHA | Bygger images, ingen deploy |
| Tag `v1.2.3-rc.1` | `1.2.3-rc.1`, SHA | Images för provning; inte `latest` |
| Pull request | — | Bygger utan push |

### Konsekvenser

* Bra, eftersom GitHub Releases ger full revisionshistorik och reproducerbara
  deployments.
* Bra, eftersom rollback förenklas: rollbackskriptet i driftrepot laddar ner
  från releasen, och pre-release-taggar (`-rc.1`) kan provas utan deploy.
* Dåligt, eftersom deploy kräver att GitHub Actions är tillgängligt (nertid:
  deployskriptet i driftrepot kan köras manuellt med samma version).
* Dåligt, eftersom en image-rollback inte ångrar schemamigrationer; rollback
  efter en migration kräver databasåterställning.
* Dåligt, eftersom legacy-frontenderna måste paketeras som tarballs.

### Bekräftelse

Hälsokontrollen (`scripts/wait-healthy.sh`) stoppar deployen innan den
räknas som klar.

## Mer information

* [ADR-0013: Publikt kodrepo, privat driftrepo](0013-public-code-private-operations.md)
* [build-and-publish.yml](../../.github/workflows/build-and-publish.yml)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-02 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
