"use server";

import { revalidatePath } from "next/cache";
import { fetchApi } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

export type AddPersonResult =
  | { ok: true; duplicateContactEmail: boolean }
  | { ok: false; error: string };

export type MembershipPatch = {
  membership_status?: string;
  member_number?: number;
  address?: string | null;
  postal_code?: string | null;
  city?: string | null;
  payment_note?: string | null;
  notes?: string | null;
};

export type PersonInput = {
  first_name: string;
  last_name: string;
  email?: string | null;
  phone?: string | null;
  role?: string;
};

export type MembershipCreateInput = {
  first_name: string;
  last_name: string;
  email?: string | null;
  phone?: string | null;
  address?: string | null;
  postal_code?: string | null;
  city?: string | null;
  membership_status?: string;
  allocate?: boolean;
};

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "detail" in err) {
    return String((err as { detail: unknown }).detail);
  }
  return err instanceof Error ? err.message : "Ett fel uppstod.";
}

function revalidateMatrikel(membershipId: number) {
  revalidatePath(`/medlem/matrikel/${membershipId}`);
  revalidatePath("/medlem/matrikel");
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function updateMembership(
  id: number,
  patch: MembershipPatch,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/memberships/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: JSON_HEADERS,
    });
    revalidateMatrikel(id);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function createMembership(
  input: MembershipCreateInput,
): Promise<ActionResult & { id?: number }> {
  try {
    const data = await fetchApi<{ id: number }>("/v2/memberships", {
      method: "POST",
      body: JSON.stringify(input),
      headers: JSON_HEADERS,
    });
    revalidatePath("/medlem/matrikel");
    return { ok: true, id: data.id };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function retireMembership(id: number): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/memberships/${id}`, { method: "DELETE" });
    revalidateMatrikel(id);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function addPerson(
  membershipId: number,
  person: PersonInput,
): Promise<AddPersonResult> {
  try {
    const data = await fetchApi<{ duplicate_contact_email?: boolean }>(
      `/v2/memberships/${membershipId}/persons`,
      { method: "POST", body: JSON.stringify(person), headers: JSON_HEADERS },
    );
    revalidateMatrikel(membershipId);
    return {
      ok: true,
      duplicateContactEmail: Boolean(data?.duplicate_contact_email),
    };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function updatePerson(
  membershipId: number,
  personId: number,
  patch: PersonInput,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/persons/${personId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: JSON_HEADERS,
    });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function removePerson(
  membershipId: number,
  personId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/persons/${personId}`, { method: "DELETE" });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function anonymizePerson(
  membershipId: number,
  personId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/persons/${personId}/anonymize`, { method: "POST" });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function setMainMember(
  membershipId: number,
  personId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/memberships/${membershipId}/main-member`, {
      method: "POST",
      body: JSON.stringify({ person_id: personId }),
      headers: JSON_HEADERS,
    });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function createGrant(
  membershipId: number,
  personId: number,
  grant: { herd_id: number; valid_until?: string },
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/persons/${personId}/grants`, {
      method: "POST",
      body: JSON.stringify(grant),
      headers: JSON_HEADERS,
    });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function renewGrant(
  membershipId: number,
  grantId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/grants/${grantId}/renew`, { method: "POST" });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export async function revokeGrant(
  membershipId: number,
  grantId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/grants/${grantId}`, { method: "DELETE" });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}

export type LinkResult =
  | { ok: true }
  | {
      ok: false;
      confirmRequired: {
        conveysHerds: { id: number; herd: string; herd_name: string | null }[];
      };
    }
  | { ok: false; error: string };

export async function linkPersonUser(
  membershipId: number,
  personId: number,
  userId: number,
  confirmedHerdIds?: number[],
): Promise<LinkResult> {
  const body = confirmedHerdIds
    ? { user_id: userId, confirm: true, confirmed_herd_ids: confirmedHerdIds }
    : { user_id: userId };
  try {
    await fetchApi(`/v2/persons/${personId}/link-user`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: JSON_HEADERS,
    });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    // Structural check, not instanceof: the vitest mock of @/lib/api rejects a
    // plain Error carrying type/extensions, and a real ApiError has the same shape.
    const problem = err as {
      type?: unknown;
      extensions?: { conveys_herds?: unknown };
    };
    if (problem?.type === "confirm-required") {
      const raw = problem.extensions?.conveys_herds;
      const herds = (Array.isArray(raw) ? raw : []).filter(
        (h): h is { id: number; herd: string; herd_name: string | null } =>
          !!h && typeof h.id === "number" && typeof h.herd === "string",
      );
      return { ok: false, confirmRequired: { conveysHerds: herds } };
    }
    return { ok: false, error: extractError(err) };
  }
}

export async function unlinkPersonUser(
  membershipId: number,
  personId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/persons/${personId}/link-user`, { method: "DELETE" });
    revalidateMatrikel(membershipId);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: extractError(err) };
  }
}
