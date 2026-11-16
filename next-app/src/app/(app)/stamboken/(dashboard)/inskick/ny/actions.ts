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
  // `warnings`: the API stored nothing because a photo may be hard to read (409);
  // sending again with the field accept_warnings=1 stores it anyway.
  | { ok: false; error: string; warnings?: UploadedDoc[] };

// One call (docs/inkorg.md, Ladda upp): the files are stored, or refused with
// per-file warnings that the sender can accept.
export async function uploadIntyg(formData: FormData): Promise<UploadResult> {
  try {
    const res = await fetchApi<{
      item?: { id: number };
      documents: UploadedDoc[];
    }>("/v2/inkorg/upload", {
      method: "POST",
      body: formData,
      timeout: 60000,
    });
    revalidatePath("/stamboken", "layout");
    return {
      ok: true,
      documents: res.documents,
      itemId: res.item?.id ?? null,
    };
  } catch (e) {
    if (e instanceof ApiError) {
      const warnings = e.extensions?.warnings;
      return {
        ok: false,
        error: e.detail,
        ...(e.status === 409 && Array.isArray(warnings) ? { warnings } : {}),
      };
    }
    return { ok: false, error: "Det gick inte att skicka. Försök igen." };
  }
}
