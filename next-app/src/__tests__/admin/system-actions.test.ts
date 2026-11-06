import { beforeEach, describe, expect, test, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import { requireAdminProdMode } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode";
import { massLogout } from "@/app/(app)/stamboken/(dashboard)/admin/system/actions";

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

const mockedGuard = vi.mocked(requireAdminProdMode);
const mockedFetch = vi.mocked(fetchApi);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("massLogout — prod-mode guard", () => {
  test("with sb_mode=demo rejects before any fetchApi", async () => {
    mockedGuard.mockRejectedValue(new Error("NEXT_REDIRECT"));
    await expect(massLogout()).rejects.toThrow("NEXT_REDIRECT");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  test("returns sessions_cleared from the endpoint", async () => {
    mockedGuard.mockResolvedValue(undefined);
    mockedFetch.mockResolvedValue({ sessions_cleared: 12 });
    await expect(massLogout()).resolves.toEqual({ sessions_cleared: 12 });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/v2/admin/sessions/mass-logout",
      expect.objectContaining({ method: "POST", forceProd: true }),
    );
  });
});
