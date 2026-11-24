import { beforeEach, describe, expect, test, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import { confirmLitterCount } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const mockedFetch = vi.mocked(fetchApi);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("confirmLitterCount", () => {
  test.each([Number.NaN, 1.5, 0, -3, 2 ** 53])(
    "refuses the litter id %s before any request",
    async (id) => {
      expect(await confirmLitterCount(id, 3)).toEqual({
        success: false,
        error: "Kullen finns inte.",
      });
      expect(mockedFetch).not.toHaveBeenCalled();
    },
  );

  test("posts the count of a valid litter", async () => {
    mockedFetch.mockResolvedValue({ id: 7 });
    expect(await confirmLitterCount(7, 3)).toEqual({
      success: true,
      data: { id: 7 },
    });
    expect(mockedFetch).toHaveBeenCalledWith("/v2/breeding/7/antal", {
      method: "POST",
      body: JSON.stringify({ litter_size6w: 3 }),
    });
  });
});
