# Legacy regression-tester

Tvålagers-testsuite som verifierar att legacy-frontenden och API:et är kompatibla (ADR-0006).
**Kör vid**: API-ändringar, före release, före servermigration.

## Layer 1 — API-kontraktstester (pytest, ~1 min)

Verifierar att alla legacy-endpoints returnerar rätt responsformat och statuskoder.

```bash
docker exec herdbook-pytest-api-1 pytest /app/tests/test_legacy_api_contracts.py -v
```

## Layer 2 — Legacy UI smoke tests (Playwright, ~45 sek)

Kör 11 kritiska användarflöden genom legacy-frontenden i en riktig webbläsare.
Kräver local-production-stacken med testanvändare.

```bash
# 1. Starta local-production (skapar testanvändare automatiskt). Skriptet ligger
#    i stamboken-drift och kräver en produktionsdump.
../stamboken-drift/scripts/bootstrap-local-production.sh

# 2. Kör Playwright-testerna
cd next-app && pnpm exec playwright test --config playwright.legacy.config.ts
```

## Testanvändare (skapas av bootstrap-scriptet)

| Användare | Lösenord | Roll |
|-----------|----------|------|
| `test-admin` | `test-admin-pass` | admin |
| `test-gk-manager` | `test-gk-pass` | manager(GK) |
| `test-gk-owner` | `test-gk-owner-pass` | owner(G-herd) |

**OBS:** Rate limiting är avstängt i local-production (`RATELIMIT_ENABLED=false`).
