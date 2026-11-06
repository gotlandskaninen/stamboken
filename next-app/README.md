# Herdbook next-app

Next.js frontend for the digital herdbook (stambok) of the Swedish rabbit
breeds Gotlandskanin and Mellerudskanin, served at
[gotlandskaninen.se](https://gotlandskaninen.se). Public CMS pages, the
authenticated `/stamboken` dashboard and the member registry live in this
app; the Flask API (`../app`) is the data backend.

## Stack

- Next.js 16 (App Router) + React 19, TypeScript
- MUI v9 (slice 0 upgrade) themed by the Stamboken design system
  ([ADR-0009](../docs/adr/0009-stamboken-design-system.md)) —
  `src/styles/tokens.css` is the single styling source of truth and
  `src/theme/stamboken.ts` the only MUI theme
- Server Components / Server Actions first
  ([ADR-0008](../docs/adr/0008-server-first-data-architecture.md));
  RTK Query only for interactive features
- Payload CMS 3.x embedded as a Next.js plugin (`src/payload.config.ts`;
  admin UI at `/admin`, REST at `/cms-api`), separate `herdbook_cms`
  database
- i18next — Swedish default, English via the topbar language toggle

## Development

Run the full stack (Flask API, databases, nginx, this app) from the repo
root:

```bash
docker compose up -d
```

The app is served through nginx at `https://localhost` (self-signed cert
in dev). To run the dev server directly against a stack whose API port is
published on the host:

```bash
pnpm install
API_INTERNAL_URL=http://localhost:9090 pnpm dev
```

`API_INTERNAL_URL` drives both the server-side fetches (`src/lib/api.ts`,
default `http://api:9090` — only resolvable inside the compose network)
and the `/api` rewrite (`next.config.js`, fallback `http://localhost:9090`).

Dependency changes regenerate the lockfile in Docker (same image as the
build stage, so the resolution matches CI), from the repo root:

```bash
docker run --rm -e CI=true -v "$(pwd)/next-app:/app" -w /app node:24-alpine \
  sh -c "corepack enable pnpm && pnpm install --no-frozen-lockfile"
```

That leaves musl-linked modules behind, so restore host `node_modules`
afterwards with `pnpm install --frozen-lockfile` in `next-app/`.

## Checks

```bash
pnpm type-check       # tsc
pnpm exec eslint .    # non-mutating check (pnpm lint runs eslint --fix)
pnpm test             # vitest (unit tests in src/__tests__/)
```

## End-to-end tests (Playwright)

```bash
pnpm exec playwright test                                       # dashboard suites (dev stack)
pnpm exec playwright test --config playwright.admin.config.ts   # adminpanel (local-production stack)
pnpm exec playwright test --config playwright.demo.config.ts    # demo/prod toggle (local-production stack)
pnpm exec playwright test --config playwright.legacy.config.ts  # legacy regression (../docs/legacy-regression-testing.md)
```

CI runs the default suite as a gate and the legacy suite as an advisory
job (`.github/workflows/playwright.yml`). The local-production suites
(admin, demo) never run in CI and need
`bootstrap-local-production.sh` (in stamboken-drift) first.

## Payload CMS schema

Dev pushes the schema automatically on startup; production uses
migrations: `docker compose exec next-app pnpm migrate:create <name>` in
dev (the CMS database publishes no host port), commit, then
`pnpm migrate` as a deploy step. See `src/migrations/README.md` and
[../docs/local-cms-testing.md](../docs/local-cms-testing.md).

## More documentation

- [../CLAUDE.md](../CLAUDE.md) — conventions, URL namespace, test users
- [../docs/adr/](../docs/adr/) — architecture decision records
- [../docs/design/design_handoff_min_besattning/tokens.css](../docs/design/design_handoff_min_besattning/tokens.css)
  — design-system tokens from the design handoff
