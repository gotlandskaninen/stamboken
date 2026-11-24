"use server";

import { fetchApi, ApiError } from "@/lib/api";

export type TyckTillResult =
  | {
      ok: true;
      issueUrl: string | null;
      visibility: "publik" | "privat";
      images: number;
      replyTo: string | null;
    }
  | { ok: false; status: number; error: string; field?: string };

// Not forceProd: a logged-in tester in the testmiljö reaches api-test, whose
// issues get the label `testmiljö`. 30 s: the images are encoded and GitHub
// may take up to ten seconds (docs/tyck-till.md).
export async function sendTyckTill(
  formData: FormData,
): Promise<TyckTillResult> {
  try {
    const res = await fetchApi<{
      issue_url: string | null;
      visibility: "publik" | "privat";
      images: number;
      reply_to: string | null;
    }>("/v2/tyck-till", { method: "POST", body: formData, timeout: 30000 });
    return {
      ok: true,
      issueUrl: res.issue_url,
      visibility: res.visibility,
      images: res.images,
      replyTo: res.reply_to,
    };
  } catch (e) {
    if (e instanceof ApiError) {
      const field = e.extensions?.field;
      return {
        ok: false,
        status: e.status,
        error: e.detail,
        ...(typeof field === "string" ? { field } : {}),
      };
    }
    return { ok: false, status: 0, error: "" };
  }
}
