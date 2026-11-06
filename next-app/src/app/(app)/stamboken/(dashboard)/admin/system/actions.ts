"use server";

import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "../_lib/requireAdminProdMode";

export async function massLogout(): Promise<
  { sessions_cleared: number } | { error: string }
> {
  await requireAdminProdMode(); // MUST be the first line.
  try {
    // SCAN+DEL of session:* in Redis db 2 + audit marker row.
    return await fetchApi<{ sessions_cleared: number }>(
      "/v2/admin/sessions/mass-logout",
      { method: "POST", forceProd: true },
    );
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
}
