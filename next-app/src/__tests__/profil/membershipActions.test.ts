import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock next/cache
vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

// Mock @/lib/api (actions only import fetchApi)
vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(),
}));

// Mock next/headers (defensive, matches profil/actions.test.ts precedent)
vi.mock("next/headers", () => ({
  cookies: vi.fn(() => ({
    getAll: () => [{ name: "session", value: "test-session" }],
    get: () => ({ name: "session", value: "test-session" }),
  })),
  headers: vi.fn(() => ({
    get: () => null,
  })),
}));

import { revalidatePath } from "next/cache";
import { fetchApi } from "@/lib/api";
import {
  addMyPerson,
  createMyGrant,
  removeMyPerson,
  renewMyGrant,
  revokeMyGrant,
  updateConsent,
  updateContact,
} from "@/app/(app)/stamboken/(dashboard)/profil/actions";

const apiError = (detail: string) =>
  Object.assign(new Error(detail), { detail });

describe("my-membership actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("addMyPerson POSTs the person and surfaces the duplicate-email flag", async () => {
    vi.mocked(fetchApi).mockResolvedValue({
      id: 7,
      duplicate_contact_email: true,
    });
    const input = {
      first_name: "Kim",
      last_name: "Karlsson",
      email: "kim@example.com",
      role: "familjemedlem" as const,
    };
    const result = await addMyPerson(input);
    expect(result).toEqual({ ok: true, duplicateEmail: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/my-membership/persons", {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
  });

  it("addMyPerson returns duplicateEmail=false when the flag is absent", async () => {
    vi.mocked(fetchApi).mockResolvedValue({ id: 8 });
    const result = await addMyPerson({
      first_name: "Sam",
      last_name: "Svensson",
      role: "skotare",
    });
    expect(result).toEqual({ ok: true, duplicateEmail: false });
  });

  it("addMyPerson returns the RFC 9457 detail on failure", async () => {
    vi.mocked(fetchApi).mockRejectedValue(
      apiError("Endast huvudmedlem får hantera personer."),
    );
    const result = await addMyPerson({
      first_name: "A",
      last_name: "B",
      role: "skotare",
    });
    expect(result).toEqual({
      ok: false,
      error: "Endast huvudmedlem får hantera personer.",
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("removeMyPerson DELETEs the person and revalidates", async () => {
    vi.mocked(fetchApi).mockResolvedValue(undefined);
    const result = await removeMyPerson(5);
    expect(result).toEqual({ ok: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/my-membership/persons/5", {
      method: "DELETE",
    });
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
  });

  it("createMyGrant POSTs herd_id to the person's grants endpoint", async () => {
    vi.mocked(fetchApi).mockResolvedValue({ id: 9 });
    const result = await createMyGrant(5, 3);
    expect(result).toEqual({ ok: true });
    expect(fetchApi).toHaveBeenCalledWith(
      "/v2/my-membership/persons/5/grants",
      {
        method: "POST",
        body: JSON.stringify({ herd_id: 3 }),
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
  });

  it("renewMyGrant POSTs to the renew endpoint", async () => {
    vi.mocked(fetchApi).mockResolvedValue({ id: 9 });
    const result = await renewMyGrant(9);
    expect(result).toEqual({ ok: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/my-membership/grants/9/renew", {
      method: "POST",
    });
  });

  it("revokeMyGrant DELETEs the grant", async () => {
    vi.mocked(fetchApi).mockResolvedValue(undefined);
    const result = await revokeMyGrant(9);
    expect(result).toEqual({ ok: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/my-membership/grants/9", {
      method: "DELETE",
    });
  });

  it("revokeMyGrant surfaces the error detail and skips revalidation", async () => {
    vi.mocked(fetchApi).mockRejectedValue(apiError("Åtkomsten finns inte."));
    const result = await revokeMyGrant(9);
    expect(result).toEqual({ ok: false, error: "Åtkomsten finns inte." });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("updateContact PATCHes the structured address and revalidates the profil", async () => {
    vi.mocked(fetchApi).mockResolvedValue({});
    const patch = {
      phone: "070",
      email: "a@b.example.com",
      address: "Gatan 1",
      postal_code: "623 55",
      city: "Visby",
    };
    const result = await updateContact(patch);
    expect(result).toEqual({ ok: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/members/me/contact", {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
  });

  it("updateConsent PATCHes the partial consent body verbatim", async () => {
    // The body carries only the keys the member changed — the
    // backend merges them onto the row it re-reads under the membership lock.
    const merged = { name: true, phone: true, email: false, address: false };
    vi.mocked(fetchApi).mockResolvedValue({
      publication_consent: merged,
      consent_answered: true,
    });
    const result = await updateConsent({ email: false });
    // The merged row comes back so the client can re-base its next diff.
    expect(result).toEqual({ ok: true, consent: merged, answered: true });
    expect(fetchApi).toHaveBeenCalledWith("/v2/members/me/consent", {
      method: "PATCH",
      body: JSON.stringify({ email: false }),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
  });
});
