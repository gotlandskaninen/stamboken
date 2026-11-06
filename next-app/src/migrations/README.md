# Payload CMS migrations

Schema for the `herdbook_cms` database is managed differently in dev vs
production (config in `src/payload.config.ts`, summary in the root `CLAUDE.md`
→ "Payload CMS schema").

## Dev — Drizzle push

In development, **push** is ON (`push: true` unless `PAYLOAD_DB_PUSH=false`) and
auto-syncs the schema on startup. Add a field, restart, done — no migrations
needed for local iteration.

## Production — migrations (push does NOT run here)

Payload disables push under `NODE_ENV=production` (the standalone build,
including local-production), so push never touches a production database
regardless of the flag. Production schema comes from the migrations in this
folder. A **baseline** migration (`*_baseline.ts`) creates the whole schema; a
fresh database goes from empty → full schema by running `pnpm migrate`.

The Payload CLI is not in the standalone runner image (`node server.js`), so
migrations run from a dedicated image. The `migrate` stage in `.docker/next-app`
(deps + source, no `next build`) provides it, wired as the **`cms-migrate`**
one-shot compose service.

**local-production (validated):** `bootstrap-local-production.sh` (stamboken-drift) runs
`docker compose run --rm --build cms-migrate` to create the schema, then loads
the data-only seed `seed-cms-content.sql` (production content; kept in the private
operations repo stamboken-drift under `scripts/`, path via `CMS_SEED`). A fresh `cms-postgres-data`
volume rebuilds correctly from scratch.

**production (`docker-compose.production.yml`):** next-app is a prebuilt ghcr
image, so CI must also build+push the `migrate`-target image, and the deploy
must run it (`cms-migrate`) before the data seed. *(Wired: `build-and-publish.yml`
builds/pushes the image and the deploy gates on `docker compose run --rm cms-migrate`
before restarting next-app.)*

### Workflow for later schema changes

1. Edit the collection.
2. `docker compose exec next-app pnpm migrate:create <name>` → review/commit.
   (Run inside the container — it has `CMS_DATABASE_URL` and network access;
   `cms-database` publishes no host port, so a host-side run cannot reach it.)
3. Deploy runs `pnpm migrate` (via the `cms-migrate` job) before serving.

`pnpm migrate:status` shows which migrations have run. Regenerate
`seed-cms-content.sql` from `seed-content.ts` (both in stamboken-drift) whenever seed content
changes (`pnpm migrate` to create schema → run the seed → `pg_dump --data-only
--disable-triggers --exclude-table=payload_migrations`).
