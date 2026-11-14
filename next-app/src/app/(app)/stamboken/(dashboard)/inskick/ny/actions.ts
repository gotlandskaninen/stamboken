"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";

export interface UploadedDoc {
  file: number;
  page: number | null;
  warnings: string[];
}

export type UploadResult =
  | { ok: true; documents: UploadedDoc[]; itemId: number | null }
  | { ok: false; error: string };

// dry_run measures the images and saves nothing (docs/inkorg.md, Ladda upp).
export async function uploadIntyg(
  formData: FormData,
  dryRun: boolean,
): Promise<UploadResult> {
  if (dryRun) formData.set("dry_run", "1");
  try {
    const res = await fetchApi<{
      item?: { id: number };
      documents: UploadedDoc[];
    }>("/v2/inkorg/upload", {
      method: "POST",
      body: formData,
      timeout: 60000,
    });
    if (!dryRun) {
      revalidatePath("/stamboken", "layout");
    }
    return {
      ok: true,
      documents: res.documents,
      itemId: res.item?.id ?? null,
    };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e.detail };
    return { ok: false, error: "Det gick inte att skicka. Försök igen." };
  }
}
