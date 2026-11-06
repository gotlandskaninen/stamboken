# Lokal testning av Payload CMS (steg-för-steg)

Verifierar att CMS-integrationen fungerar från ren start.
Kortversion finns i [CLAUDE.md](../CLAUDE.md) under "Snabbstart".

## 1. Starta infrastrukturen

```bash
docker compose up -d cms-database next-app
# Vänta tills next-app visar "Ready" i loggarna:
docker compose logs -f next-app
```

## 2. Skapa admin-användare

Öppna `http://localhost:3000/admin` — Payload visar "Create first user".
Skapa en användare med valfri e-post och lösenord.

## 3. Verifiera collections

I admin-sidofältet ska du se: Pages, Navigation, Media, Users.

## 4. Skapa en testsida

- Gå till Pages → Create New
- Titel: "Test", Slug: "test", Innehåll: valfri text
- Klicka Publish

## 5. Verifiera publik rendering

```bash
# CMS-sidan ska returnera HTML med titeln:
curl http://localhost:3000/test
# CMS API ska returnera JSON:
curl http://localhost:3000/cms-api/pages | jq '.docs[].title'
```

## 6. Testa draft access control

```bash
# Skapa en draft-sida i admin (spara utan att publicera, slug: "hemlig")
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/hemlig
# Förväntat: 404 (drafts syns inte publikt)
```

## 7. Testa reserved slug

I admin, försök skapa en sida med slug "admin" → ska ge valideringsfel.

## 8. Seed all content

Seedern och bilderna ligger i det privata driftrepot `stamboken-drift`
(`next-app/src/scripts/seed-content.ts`, `next-app/seed-media/`). Dess
`scripts/seed-cms-dev.sh` kopierar in dem i den här checkouten (båda sökvägarna
är gitignorerade) och kör seedern i dev-containern:

```bash
../stamboken-drift/scripts/seed-cms-dev.sh
# Verifierar att alla sidor skapats:
for slug in om-foreningen styrelse gotlandskanin mellerudskanin historik bli-medlem; do
  echo -n "$slug: "; curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000/$slug"; echo
done
```
