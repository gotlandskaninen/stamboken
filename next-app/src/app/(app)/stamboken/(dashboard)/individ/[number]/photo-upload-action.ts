"use server";
import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";

export async function uploadPhoto(number: string, formData: FormData) {
  try {
    const res = await fetchApi<{ filename: string }>(
      `/v2/upload/photo/${encodeURIComponent(number)}`,
      { method: "POST", body: formData, timeout: 30000 },
    );
    revalidatePath(`/stamboken/individ/${number}`);
    return { success: true as const, filename: res.filename };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    return { success: false as const, error: "network_error" };
  }
}
