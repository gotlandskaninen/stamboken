"use server";

import { cookies } from "next/headers";
import { MODE_COOKIE, parseMode, type Mode } from "@/lib/mode";
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
export async function uploadIntyg(
  formData: FormData,
  mode: Mode,
): Promise<UploadResult> {
  if (parseMode((await cookies()).get(MODE_COOKIE)?.value) !== mode)
    return { ok: false, error: "Miljön har bytts. Ladda om sidan." };
  try {
    const res = await fetchApi<{
      item?: { id: number };
      documents: UploadedDoc[];
    }>("/v2/inkorg/upload", {
      method: "POST",
      body: formData,
      timeout: 60000,
      isolateDemo: true,
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

// MarkSeen reads the sender's "klart" notices in the same environment as the list.
export async function markUploadsSeen(): Promise<void> {
  try {
    const { read } = await fetchApi<{ read: number }>(
      "/v2/inkorg/mina-inskick/sedda",
      { method: "POST", isolateDemo: true },
    );
    if (read > 0) revalidatePath("/stamboken", "layout");
  } catch {
    // The notices stay unread until the next visit.
  }
}
