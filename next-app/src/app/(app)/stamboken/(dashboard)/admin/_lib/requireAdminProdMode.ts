import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { MODE_COOKIE, parseMode } from "@/lib/mode";

/**
 * Admin Server Actions MUST force the prod backend
 * regardless of sb_mode cookie state. This guard is the FIRST line of code
 * in every admin Server Action. If the cookie is not prod it throws a
 * redirect back to /stamboken/admin so the layout re-renders the
 * mode-switch prompt — BEFORE any fetchApi call, so demo never sees a
 * side effect. Belt: every admin fetchApi call also passes
 * { forceProd: true } (the flag shipped in Phase 999.2 — api.ts:17).
 */
export async function requireAdminProdMode(): Promise<void> {
  const store = await cookies();
  const mode = parseMode(store.get(MODE_COOKIE)?.value);
  if (mode !== "prod") {
    redirect("/stamboken/admin");
  }
}
