"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "../_lib/requireAdminProdMode";

export type ActionError = { error: string };

async function post(
  id: number,
  verb: "retry" | "cancel",
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    // 409 carries the API's Swedish detail ("Bara köade utskick kan stoppas.").
    await fetchApi(`/v2/mail/messages/${id}/${verb}`, {
      method: "POST",
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidatePath("/stamboken/admin/utskick");
}

export const retryMessage = (id: number) => post(id, "retry");
export const cancelMessage = (id: number) => post(id, "cancel");
