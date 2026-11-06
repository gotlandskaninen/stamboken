import { beforeEach, describe, expect, test, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import { requireAdminProdMode } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode";
import { updateGenebank } from "@/app/(app)/stamboken/(dashboard)/admin/genbanker/actions";

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

const mockedGuard = vi.mocked(requireAdminProdMode);
const mockedFetch = vi.mocked(fetchApi);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("admin genebank actions — prod-mode guard", () => {
  test("updateGenebank with sb_mode=demo rejects before any fetchApi", async () => {
    mockedGuard.mockRejectedValue(new Error("NEXT_REDIRECT"));
    await expect(updateGenebank(1, { name: "X" })).rejects.toThrow(
      "NEXT_REDIRECT",
    );
    expect(mockedFetch).not.toHaveBeenCalled();
  });
});
