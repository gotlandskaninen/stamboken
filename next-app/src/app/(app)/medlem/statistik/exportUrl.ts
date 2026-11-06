import type { Mode } from "@/lib/mode";

// Mode-aware CSV export URL. Mirrors the routing rule of
// redux/api/apiSlice.ts modeAwareBaseQuery: demo mode goes to the configured
// test URL ONLY when one is set; base dev (no test URL) and prod stay on
// /api. Hardcoding /api here would let a demo-mode reviewer download the
// PRODUCTION member CSV while the visible stats came from the demo database.
// v2: no genebank scoping — the export covers the whole association matrikel
// including friexemplar rows (it doubles as the magazine mailing list).
export function memberExportUrl(
  mode: Mode,
  apiTestUrl: string | undefined,
): string {
  const base = mode === "demo" && apiTestUrl ? apiTestUrl : "/api";
  return `${base}/v2/members/export`;
}

// Consent-aware Koharen listing. Same demo/prod routing rule
// as memberExportUrl above; the two exports are separate endpoints because the
// MATR contract is frozen (ADR-0006).
export function koharenExportUrl(
  mode: Mode,
  apiTestUrl: string | undefined,
): string {
  const base = mode === "demo" && apiTestUrl ? apiTestUrl : "/api";
  return `${base}/v2/members/koharen-export`;
}
