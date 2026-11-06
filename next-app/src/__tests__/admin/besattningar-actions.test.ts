import { beforeEach, describe, expect, test, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import { requireAdminProdMode } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode";
import {
  createHerd,
  updateHerd,
} from "@/app/(app)/stamboken/(dashboard)/admin/besattningar/actions";

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

describe("admin herd actions — prod-mode guard runs before any fetch", () => {
  test("createHerd with sb_mode=demo rejects before any fetchApi", async () => {
    mockedGuard.mockRejectedValue(new Error("NEXT_REDIRECT"));
    await expect(
      createHerd({ genebank: 1, herd: "G999", is_active: true }),
    ).rejects.toThrow("NEXT_REDIRECT");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  test("updateHerd with sb_mode=demo rejects before any fetchApi", async () => {
    mockedGuard.mockRejectedValue(new Error("NEXT_REDIRECT"));
    await expect(updateHerd("G42", { name: "X" })).rejects.toThrow(
      "NEXT_REDIRECT",
    );
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  test("createHerd maps 'herd ID already exists' to a Swedish field error", async () => {
    mockedGuard.mockResolvedValue(undefined);
    mockedFetch.mockResolvedValue({
      status: "error",
      message: "herd ID already exists",
    });
    const result = await createHerd({
      genebank: 1,
      herd: "G999",
      is_active: true,
    });
    expect(result).toEqual({
      field: "herd",
      error: "Besättningsnumret finns redan. Välj ett annat nummer.",
    });
  });
});
