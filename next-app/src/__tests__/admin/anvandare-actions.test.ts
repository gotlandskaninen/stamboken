import { beforeEach, describe, expect, test, vi } from "vitest";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { resetPassword } from "@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions";

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
