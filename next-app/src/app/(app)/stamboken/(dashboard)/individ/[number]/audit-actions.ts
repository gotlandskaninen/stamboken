"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";

export async function revertAuditEntry(
  auditId: number,
  fields?: string[],
  revalidate?: string,
) {
  try {
    const result = await fetchApi<{ status: string; message: string }>(
      `/audit-log/${auditId}/revert`,
      {
        method: "POST",
        body: fields ? JSON.stringify({ fields }) : undefined,
      },
    );
    if (revalidate) revalidatePath(revalidate);
    return { success: true as const, message: result.message };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    console.error("revertAuditEntry failed:", auditId, e);
    return { success: false as const, error: "unexpected_error" };
  }
}

export async function restoreRecord(
  tableName: string,
  recordId: string | number,
  auditId: number,
  revalidate?: string,
) {
  try {
    const result = await fetchApi<{ status: string; message: string }>(
      `/audit-log/${tableName}/${recordId}/restore/${auditId}`,
      { method: "POST" },
    );
    if (revalidate) revalidatePath(revalidate);
    return { success: true as const, message: result.message };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    console.error("restoreRecord failed:", tableName, recordId, auditId, e);
    return { success: false as const, error: "unexpected_error" };
  }
}
