"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";

export async function markNoticesRead(
  body: { ids: number[] } | { all: true },
): Promise<{ ok: boolean }> {
  try {
    await fetchApi("/v2/inkorg/notiser/las", {
      method: "POST",
      body: JSON.stringify(body),
    });
    // Refresh the unread badge in the menu.
    revalidatePath("/stamboken", "layout");
    return { ok: true };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false };
    throw e;
  }
}

export async function setMailNotices(
  mailEnabled: boolean,
): Promise<{ ok: true; mailEnabled: boolean } | { ok: false; error: string }> {
  try {
    const res = await fetchApi<{ mail_enabled: boolean }>(
      "/v2/inkorg/notiser/installning",
      { method: "PUT", body: JSON.stringify({ mail_enabled: mailEnabled }) },
    );
    return { ok: true, mailEnabled: res.mail_enabled };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e.detail };
    throw e;
  }
}
