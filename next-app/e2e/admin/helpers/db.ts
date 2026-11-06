import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Run SQL against the local-production Postgres. SQL is passed on STDIN
 * (`psql -tAq` reads commands from stdin), so quotes/jsonb literals in the
 * SQL never fight shell quoting.
 *
 * Used for state the admin UI cannot create (seed rows, dump-admin
 * deactivation for the sole-admin precondition) and for id lookups.
 */
// ESM: package.json declares "type": "module", so __dirname is undefined.
// Derive it from import.meta.url — same pattern as e2e/herd-switching.spec.ts.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../../..");
const COMPOSE = `docker compose -f ${path.join(
  REPO_ROOT,
  "docker-compose.local-production.yml",
)}`;

export function psql(
  sql: string,
  db: "herdbook" | "herdbook_demo" = "herdbook",
): string {
  // -q drops the command tags ("INSERT 0 1") that otherwise ride along after
  // the rows a RETURNING clause prints, so an id read back from an INSERT is
  // the id and nothing else. ON_ERROR_STOP makes psql exit non-zero on a SQL
  // error so execSync throws and a half-applied seed fails loudly instead of
  // cascading silently into the statements after it.
  return execSync(
    `${COMPOSE} exec -T database psql -U herdbook -d ${db} -tAq -v ON_ERROR_STOP=1`,
    {
      cwd: REPO_ROOT,
      input: sql,
      encoding: "utf8",
    },
  ).trim();
}
