"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "../_lib/requireAdminProdMode";

export type AdminActionError = { error: string; field?: string };

// POST /api/manage/herd is a LEGACY endpoint: it answers HTTP 200 with
// {status: "error", message} on validation failures (duplicate herd-ID,
// missing data) — fetchApi does NOT throw for those. Inspect the body.
interface LegacyStatusBody {
  status: string;
  message?: string;
}

export interface CreateHerdInput {
  genebank: number;
  herd: string; // letter-prefixed, e.g. "G123" — built by the form client
  is_active: boolean;
  herd_name?: string | null;
  start_date?: string | null;
  name?: string | null;
  name_privacy?: string | null;
  email?: string | null;
  email_privacy?: string | null;
  mobile_phone?: string | null;
  mobile_phone_privacy?: string | null;
  wire_phone?: string | null;
  wire_phone_privacy?: string | null;
  www?: string | null;
  www_privacy?: string | null;
  physical_address?: string | null;
  physical_address_privacy?: string | null;
}

export async function createHerd(
  form: CreateHerdInput,
): Promise<AdminActionError | void> {
  await requireAdminProdMode(); // MUST be the first line.
  let body: LegacyStatusBody;
  try {
    body = await fetchApi<LegacyStatusBody>("/manage/herd", {
      method: "POST",
      body: JSON.stringify(form),
      forceProd: true, // Bypass sb_mode cookie routing.
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  if (body.status !== "success" && body.status !== "created") {
    if (body.message === "herd ID already exists") {
      // Duplicate herd-ID surfaces as a Swedish FIELD error.
      return {
        field: "herd",
        error: "Besättningsnumret finns redan. Välj ett annat nummer.",
      };
    }
    return {
      error:
        body.message ?? "Ett okänt fel inträffade. Kontakta en administratör.",
    };
  }
  revalidatePath("/stamboken/admin/besattningar");
  redirect("/stamboken/admin/besattningar"); // Back to parent list.
}

export interface UpdateHerdFields {
  // Exactly the PATCH allow-list.
  name?: string | null;
  name_privacy?: string | null;
  physical_address?: string | null;
  email?: string | null;
  mobile_phone?: string | null;
  wire_phone?: string | null;
  www?: string | null;
  is_active?: boolean;
}

export async function updateHerd(
  // Herd CODE (G1274) — matches the page URL so the revalidate below hits
  // the right path; the API accepts numeric id too.
  herdRef: string,
  fields: UpdateHerdFields,
): Promise<AdminActionError | void> {
  await requireAdminProdMode();
  try {
    await fetchApi(`/manage/herd/${encodeURIComponent(herdRef)}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidatePath("/stamboken/admin/besattningar");
  revalidatePath(`/stamboken/admin/besattningar/${herdRef}`);
  redirect("/stamboken/admin/besattningar");
}
