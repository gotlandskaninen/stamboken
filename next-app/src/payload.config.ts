import { buildConfig } from "payload";
import { postgresAdapter } from "@payloadcms/db-postgres";
import { lexicalEditor } from "@payloadcms/richtext-lexical";
import path from "path";
import { fileURLToPath } from "url";

import { Users } from "./collections/Users";
import { Media } from "./collections/Media";
import { Pages } from "./collections/Pages";
import { Navigation } from "./collections/Navigation";

const filename = fileURLToPath(import.meta.url);
const dirname = path.dirname(filename);

// True during `next build` (the standalone build stage), where the CMS database
// is not reachable. Used to skip the PAYLOAD_SECRET requirement and Drizzle push.
const isBuild =
  process.env.NEXT_PHASE === "phase-production-build" ||
  process.env.PAYLOAD_BUILD === "1";

function resolvePayloadSecret(): string {
  const secret = process.env.PAYLOAD_SECRET;
  if (secret) return secret;
  // Allow the Docker build stage (next build) to proceed without the real secret.
  if (process.env.NODE_ENV === "production" && !isBuild) {
    throw new Error(
      "PAYLOAD_SECRET is required in production. Set it in .docker/next-app-variables.env.",
    );
  }
  return "insecure-dev-only-change-in-production";
}

export default buildConfig({
  admin: {
    user: Users.slug,
    meta: {
      titleSuffix: " — Gotlandskaninen CMS",
    },
    components: {
      // With disableLocalStrategy the built-in login form is empty; this notice
      // tells users to sign in via Stamboken (or that their account lacks CMS
      // access). Path is resolved relative to importMap.baseDir below.
      beforeLogin: ["/../../components/admin/StambokenLoginNotice#default"],
    },
    importMap: {
      baseDir: path.resolve(dirname, "app/(payload)"),
    },
  },
  routes: {
    api: "/cms-api",
    admin: "/admin",
    graphQL: "/cms-graphql",
  },
  collections: [Users, Media, Pages, Navigation],
  editor: lexicalEditor(),
  // PAYLOAD_SECRET MUST be set in production. resolvePayloadSecret() throws at
  // runtime if it is missing (the dev/build fallback only applies outside prod
  // or during `next build`).
  secret: resolvePayloadSecret(),
  typescript: {
    outputFile: path.resolve(dirname, "payload-types.ts"),
  },
  db: postgresAdapter({
    pool: {
      connectionString:
        process.env.CMS_DATABASE_URL ||
        "postgres://herdbook_cms:herdbook_cms_insecure@cms-database:5432/herdbook_cms",
    },
    // Schema strategy (see CLAUDE.md → "Payload CMS schema"): Drizzle `push`
    // runs ONLY in development — Payload disables it under NODE_ENV=production
    // (the standalone build, incl. local-production), so push never touches a
    // production database regardless of this flag. In dev the schema auto-syncs
    // on startup; in production the schema is created/updated by migrations
    // (`pnpm migrate` as a deploy step). Set PAYLOAD_DB_PUSH=false to turn dev
    // push off if you want to exercise the migration path locally.
    // Never push during `next build` — the CMS database is unreachable there.
    push: process.env.PAYLOAD_DB_PUSH !== "false" && !isBuild,
    migrationDir: path.resolve(dirname, "migrations"),
  }),
  // Bulletproof admin bootstrap: on every startup, re-ensure CMS_ADMIN_EMAIL is
  // an admin allowlist row so it can never be lost (reseed, fresh DB, etc.).
  // Identity still comes from the Stamboken session; this row only grants that
  // email CMS admin access. Skipped during `next build` (DB unreachable) and
  // non-fatal — a failure logs and lets the app start.
  onInit: async (payload) => {
    if (isBuild) return;
    const adminEmail = process.env.CMS_ADMIN_EMAIL?.toLowerCase();
    if (!adminEmail) {
      payload.logger.warn(
        "CMS_ADMIN_EMAIL not set — skipping admin bootstrap.",
      );
      return;
    }
    try {
      const { docs } = await payload.find({
        collection: "users",
        where: { email: { equals: adminEmail } },
        limit: 1,
        overrideAccess: true,
      });
      if (docs.length === 0) {
        await payload.create({
          collection: "users",
          data: { email: adminEmail, role: "admin" } as never,
          overrideAccess: true,
        });
        payload.logger.info(`Bootstrapped CMS admin: ${adminEmail}`);
      } else if (docs[0].role !== "admin") {
        await payload.update({
          collection: "users",
          id: docs[0].id,
          data: { role: "admin" },
          overrideAccess: true,
        });
        payload.logger.info(`Promoted CMS user to admin: ${adminEmail}`);
      }
    } catch (err) {
      payload.logger.error(
        `CMS admin bootstrap failed for ${adminEmail}: ${err}`,
      );
    }
  },
});
