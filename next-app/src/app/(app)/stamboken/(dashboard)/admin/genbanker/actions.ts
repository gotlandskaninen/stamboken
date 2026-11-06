"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "../_lib/requireAdminProdMode";

// Manager assign/revoke deliberately has NO action here — it reuses
// grantRole/revokeRole from ../anvandare/actions: one role endpoint, one pair
// of role actions.

export async function updateGenebank(
  gbId: number,
  fields: { name?: string },
): Promise<{ error: string } | void> {
  await requireAdminProdMode(); // MUST be the first line.
  try {
    await fetchApi(`/manage/genebank/${gbId}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidatePath("/stamboken/admin/genbanker");
  revalidatePath(`/stamboken/admin/genbanker/${gbId}`);
  redirect("/stamboken/admin/genbanker"); // Back to parent list.
}
