"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import type { Consent } from "./types";

// Legacy /api/profile returns 200 {"status": "error"} on failures —
// no proper HTTP status codes. Must check response body.
interface ProfileResponse {
  status: string;
  message?: string;
}

export async function updateProfilePicture(formData: FormData) {
  try {
    const result = await fetchApi<ProfileResponse>("/profile", {
      method: "PATCH",
      body: formData,
    });
    if (result.status === "error") {
      return {
        success: false as const,
        error: result.message || "Upload failed",
      };
    }
    revalidatePath("/stamboken/profil");
    return { success: true as const };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    console.error("updateProfilePicture failed:", e);
    return { success: false as const, error: "unexpected_error" };
  }
}

export async function updateSettings(data: { use_google_picture: boolean }) {
  try {
    const result = await fetchApi<ProfileResponse>("/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    if (result.status === "error") {
      return {
        success: false as const,
        error: result.message || "Update failed",
      };
    }
    revalidatePath("/stamboken/profil");
    return { success: true as const };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    console.error("updateSettings failed:", e);
    return { success: false as const, error: "unexpected_error" };
  }
}

// --- Medlemskap self-service (ported from the deleted member profile actions, Phase 19) ---

type Result = { ok: true } | { ok: false; error: string };

// The merged row the backend wrote under the membership lock — the client
// re-bases its next partial update on it.
type ConsentResult =
  | { ok: true; consent: Consent; answered: boolean }
  | { ok: false; error: string };

type AddPersonResult =
  | { ok: true; duplicateEmail: boolean }
  | { ok: false; error: string };

export async function updateContact(patch: {
  phone?: string;
  email?: string;
  address?: string;
  postal_code?: string;
  city?: string;
}): Promise<Result> {
  try {
    await fetchApi("/v2/members/me/contact", {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: { "Content-Type": "application/json" },
    });
    revalidatePath("/stamboken/profil");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function updateConsent(
  consent: Partial<Consent>,
): Promise<ConsentResult> {
  try {
    const me = await fetchApi<{
      publication_consent: Consent;
      consent_answered: boolean;
    }>("/v2/members/me/consent", {
      method: "PATCH",
      body: JSON.stringify(consent),
      headers: { "Content-Type": "application/json" },
    });
    revalidatePath("/stamboken/profil");
    return {
      ok: true,
      consent: me.publication_consent,
      answered: me.consent_answered,
    };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function addMyPerson(input: {
  first_name: string;
  last_name: string;
  email?: string;
  phone?: string;
  role: "familjemedlem" | "skotare";
}): Promise<AddPersonResult> {
  try {
    const data = await fetchApi<{ duplicate_contact_email?: boolean }>(
      "/v2/my-membership/persons",
      {
        method: "POST",
        body: JSON.stringify(input),
        headers: { "Content-Type": "application/json" },
      },
    );
    revalidatePath("/stamboken/profil");
    return { ok: true, duplicateEmail: !!data?.duplicate_contact_email };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function removeMyPerson(personId: number): Promise<Result> {
  try {
    await fetchApi(`/v2/my-membership/persons/${personId}`, {
      method: "DELETE",
    });
    revalidatePath("/stamboken/profil");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function createMyGrant(
  personId: number,
  herdId: number,
): Promise<Result> {
  try {
    await fetchApi(`/v2/my-membership/persons/${personId}/grants`, {
      method: "POST",
      body: JSON.stringify({ herd_id: herdId }),
      headers: { "Content-Type": "application/json" },
    });
    revalidatePath("/stamboken/profil");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function renewMyGrant(grantId: number): Promise<Result> {
  try {
    await fetchApi(`/v2/my-membership/grants/${grantId}/renew`, {
      method: "POST",
    });
    revalidatePath("/stamboken/profil");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

export async function revokeMyGrant(grantId: number): Promise<Result> {
  try {
    await fetchApi(`/v2/my-membership/grants/${grantId}`, {
      method: "DELETE",
    });
    revalidatePath("/stamboken/profil");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: describe(err) };
  }
}

function describe(err: unknown): string {
  if (err && typeof err === "object" && "detail" in err) {
    return String((err as { detail: unknown }).detail);
  }
  return "Kunde inte spara.";
}
