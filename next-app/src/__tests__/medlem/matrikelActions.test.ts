import { describe, it, expect, beforeEach, vi } from "vitest";

const { fetchApiMock, revalidatePathMock } = vi.hoisted(() => ({
  fetchApiMock: vi.fn(),
  revalidatePathMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ fetchApi: fetchApiMock }));
vi.mock("next/cache", () => ({ revalidatePath: revalidatePathMock }));

import {
  addPerson,
  anonymizePerson,
  createGrant,
  createMembership,
  removePerson,
  renewGrant,
  retireMembership,
  revokeGrant,
  setMainMember,
  linkPersonUser,
  unlinkPersonUser,
  updateMembership,
  updatePerson,
} from "@/app/(app)/medlem/matrikel/actions";

beforeEach(() => {
  fetchApiMock.mockReset();
  revalidatePathMock.mockReset();
  fetchApiMock.mockResolvedValue({});
});

describe("matrikel server actions", () => {
  it("updateMembership PATCHes /v2/memberships/<id> and revalidates list + detail", async () => {
    const result = await updateMembership(5, {
      membership_status: "inactive",
      member_number: 42,
    });
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/memberships/5", {
      method: "PATCH",
      body: JSON.stringify({
        membership_status: "inactive",
        member_number: 42,
      }),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel/5");
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel");
  });

  it("createMembership POSTs the address trio verbatim to /v2/memberships, returns the new id, revalidates the list", async () => {
    fetchApiMock.mockResolvedValue({ id: 77 });
    const input = {
      first_name: "Ny",
      last_name: "Medlem",
      address: "Gatan 1",
      postal_code: "623 55",
      city: "Visby",
      allocate: true,
    };
    const result = await createMembership(input);
    expect(result).toEqual({ ok: true, id: 77 });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/memberships", {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel");
  });

  it("retireMembership DELETEs /v2/memberships/<id> and revalidates list + detail", async () => {
    const result = await retireMembership(5);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/memberships/5", {
      method: "DELETE",
    });
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel/5");
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel");
  });

  it("addPerson POSTs to /v2/memberships/<id>/persons and surfaces the duplicate-email flag", async () => {
    fetchApiMock.mockResolvedValue({ duplicate_contact_email: true });
    const result = await addPerson(5, {
      first_name: "Bo",
      last_name: "Ek",
      email: "bo@example.com",
      phone: null,
      role: "familjemedlem",
    });
    expect(result).toEqual({ ok: true, duplicateContactEmail: true });
    expect(fetchApiMock).toHaveBeenCalledWith(
      "/v2/memberships/5/persons",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("updatePerson PATCHes /v2/persons/<id>", async () => {
    const result = await updatePerson(5, 9, {
      first_name: "Bo",
      last_name: "Ek",
    });
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9", {
      method: "PATCH",
      body: JSON.stringify({ first_name: "Bo", last_name: "Ek" }),
      headers: { "Content-Type": "application/json" },
    });
  });

  it("removePerson DELETEs /v2/persons/<id>", async () => {
    const result = await removePerson(5, 9);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9", {
      method: "DELETE",
    });
  });

  it("anonymizePerson POSTs /v2/persons/<id>/anonymize", async () => {
    const result = await anonymizePerson(5, 9);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9/anonymize", {
      method: "POST",
    });
  });

  it("setMainMember POSTs person_id to /v2/memberships/<id>/main-member", async () => {
    const result = await setMainMember(5, 9);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/memberships/5/main-member", {
      method: "POST",
      body: JSON.stringify({ person_id: 9 }),
      headers: { "Content-Type": "application/json" },
    });
  });

  it("createGrant POSTs herd_id and valid_until to /v2/persons/<id>/grants", async () => {
    const result = await createGrant(5, 9, {
      herd_id: 3,
      valid_until: "2027-07-11",
    });
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9/grants", {
      method: "POST",
      body: JSON.stringify({ herd_id: 3, valid_until: "2027-07-11" }),
      headers: { "Content-Type": "application/json" },
    });
  });

  it("renewGrant POSTs /v2/grants/<id>/renew", async () => {
    const result = await renewGrant(5, 3);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/grants/3/renew", {
      method: "POST",
    });
  });

  it("revokeGrant DELETEs /v2/grants/<id>", async () => {
    const result = await revokeGrant(5, 3);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/grants/3", {
      method: "DELETE",
    });
  });

  it("surfaces RFC 9457 detail on failure", async () => {
    fetchApiMock.mockRejectedValue({
      detail: "Sista aktiva huvudmedlemmen kan inte tas bort",
    });
    const result = await removePerson(5, 9);
    expect(result).toEqual({
      ok: false,
      error: "Sista aktiva huvudmedlemmen kan inte tas bort",
    });
  });
});

describe("kontokoppling server actions", () => {
  it("linkPersonUser maps a confirm-required 409 to confirmRequired with the herd list", async () => {
    const err = Object.assign(new Error("D"), {
      status: 409,
      type: "confirm-required",
      detail: "D",
      extensions: {
        conveys_herds: [{ id: 3, herd: "G1274", herd_name: "Solhaga" }],
      },
    });
    fetchApiMock.mockRejectedValue(err);
    const result = await linkPersonUser(5, 9, 42);
    expect(result).toEqual({
      ok: false,
      confirmRequired: {
        conveysHerds: [{ id: 3, herd: "G1274", herd_name: "Solhaga" }],
      },
    });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9/link-user", {
      method: "POST",
      body: JSON.stringify({ user_id: 42 }),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePathMock).not.toHaveBeenCalled();
  });

  it("linkPersonUser confirms with the exact herd ids and revalidates", async () => {
    fetchApiMock.mockResolvedValue({ id: 9 });
    const result = await linkPersonUser(5, 9, 42, [3]);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9/link-user", {
      method: "POST",
      body: JSON.stringify({
        user_id: 42,
        confirm: true,
        confirmed_herd_ids: [3],
      }),
      headers: { "Content-Type": "application/json" },
    });
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel/5");
  });

  it("linkPersonUser surfaces a changed delta as a new confirmRequired", async () => {
    const err = Object.assign(new Error("D"), {
      status: 409,
      type: "confirm-required",
      detail: "D",
      extensions: {
        conveys_herds: [
          { id: 3, herd: "G1274", herd_name: null },
          { id: 4, herd: "G1275", herd_name: null },
        ],
      },
    });
    fetchApiMock.mockRejectedValue(err);
    const result = await linkPersonUser(5, 9, 42, [3]);
    expect(result).toMatchObject({
      ok: false,
      confirmRequired: { conveysHerds: [{ id: 3 }, { id: 4 }] },
    });
  });

  it("unlinkPersonUser DELETEs and revalidates", async () => {
    const result = await unlinkPersonUser(5, 9);
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith("/v2/persons/9/link-user", {
      method: "DELETE",
    });
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/matrikel");
  });
});
