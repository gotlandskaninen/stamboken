"use server";

import { revalidatePath } from "next/cache";
import { fetchApi } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

export type ApproveResult =
  | { ok: true; duplicateContactEmail: boolean }
  | { ok: false; error: string };

export async function approveApplication(id: number): Promise<ApproveResult> {
  try {
    // v2 approve takes no body: the membership is created with the next free
    // member number server-side; the response flags a duplicate contact
    // email (warn-not-block, spec "Application approval").
    const data = await fetchApi<{ duplicate_contact_email?: boolean }>(
      `/v2/member-applications/${id}/approve`,
      { method: "POST" },
    );
    revalidatePath("/medlem/ansokningar");
    return {
      ok: true,
      duplicateContactEmail: Boolean(data?.duplicate_contact_email),
    };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function rejectApplication(
  id: number,
  reason: string,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/member-applications/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ rejection_reason: reason }),
      headers: { "Content-Type": "application/json" },
    });
    revalidatePath("/medlem/ansokningar");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "detail" in err) {
    return String((err as { detail: unknown }).detail);
  }
  return err instanceof Error ? err.message : "Ett fel uppstod.";
}
