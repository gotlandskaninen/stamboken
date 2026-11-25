import { beforeEach, describe, expect, test, vi } from "vitest";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import {
  eraseAccount,
  resetPassword,
  setAccountActive,
  setV2ProdAccess,
} from "@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode",
  () => ({
    requireAdminProdMode: vi.fn(),
  }),
);
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("resetPassword", () => {
  test("returns the new password and re-renders nothing", async () => {
    // A reset of the admin's own password ends her session at once: a
    // revalidation would re-render the page without her and lose the password.
    vi.mocked(fetchApi).mockResolvedValue(undefined);
    const result = await resetPassword(7);
    expect(result).toEqual({ plaintext: expect.any(String) });
    expect(fetchApi).toHaveBeenCalledWith(
      "/v2/admin/users/7/password-reset",
      expect.objectContaining({ method: "POST", forceProd: true }),
    );
    expect(revalidatePath).not.toHaveBeenCalled();
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("the switches (#249)", () => {
  test.each([
    ["setAccountActive", () => setAccountActive(7, false), "active"],
    ["setV2ProdAccess", () => setV2ProdAccess(7, true), "v2-prod-access"],
  ])(
    "%s saves, re-renders the account and the list, and stays on the page",
    async (_name, action, endpoint) => {
      vi.mocked(fetchApi).mockResolvedValue(undefined);
      expect(await action()).toBeUndefined();
      expect(fetchApi).toHaveBeenCalledWith(
        `/v2/admin/users/7/${endpoint}`,
        expect.objectContaining({ method: "PATCH", forceProd: true }),
      );
      expect(revalidatePath).toHaveBeenCalledWith("/stamboken/admin/anvandare");
      expect(revalidatePath).toHaveBeenCalledWith(
        "/stamboken/admin/anvandare/7",
      );
      expect(redirect).not.toHaveBeenCalled();
    },
  );
});

describe("eraseAccount (#250)", () => {
  test("posts the erasure and re-renders the account as erased", async () => {
    vi.mocked(fetchApi).mockResolvedValue(undefined);
    expect(await eraseAccount(7)).toBeUndefined();
    expect(fetchApi).toHaveBeenCalledWith(
      "/v2/admin/users/7/erase",
      expect.objectContaining({ method: "POST", forceProd: true }),
    );
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/admin/anvandare/7");
  });

  test("returns the refusal's text and re-renders nothing", async () => {
    vi.mocked(fetchApi).mockRejectedValue(
      new ApiError({
        status: 409,
        title: "Kontot har en roll",
        detail: "Ta bort kontots roller innan uppgifterna raderas.",
        type: "has-role",
      }),
    );
    expect(await eraseAccount(7)).toEqual({
      error: "Ta bort kontots roller innan uppgifterna raderas.",
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
