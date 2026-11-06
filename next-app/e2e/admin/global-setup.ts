import { psql } from "./helpers/db";

/**
 * The admin panel is prod-only (§1.1) and the mode-gate spec clicks the
 * real "Byt till riktiga stamboken" button, whose setMode('prod') action
 * re-validates v2_prod_access=true against the prod API (Phase 999.2).
 *
 * The bootstrap (stamboken-drift) does NOT promote test-admin (only
 * test-gk-owner-promoted carries the flag — see cli/create_test_users.py),
 * so we apply the promotion UPDATE exactly as the Phase 999.2 deployment
 * docs describe (CLAUDE.md "Promotion" block), against the PROD database
 * of the local-production stack. Idempotent — safe to re-run.
 */
export default function globalSetup(): void {
  const updated = psql(
    "UPDATE hbuser SET v2_prod_access = true " +
      "WHERE username IN ('test-admin', 'test-gk-manager') " +
      "RETURNING username;",
  );
  if (!updated.includes("test-admin")) {
    throw new Error(
      "global-setup: could not promote test-admin — is the " +
        "local-production stack up? Run bootstrap-local-production.sh (stamboken-drift)",
    );
  }
  console.log(
    `admin-tests global-setup: promoted [${updated.replace(/\n/g, ", ")}]`,
  );
}
