import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchApi } from "@/lib/api";
import { uploadIntyg } from "@/app/(app)/stamboken/(dashboard)/inskick/ny/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const api = vi.mocked(fetchApi);
beforeEach(() => vi.clearAllMocks());

describe("uploadIntyg", () => {
  it("hands the per-file warnings of a 409 back, as the API sent them", async () => {
    const warnings = [{ file: 0, page: null, warnings: ["suddig"] }];
    api.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        title: "Conflict",
        detail: "Bilden kan vara svår att läsa.",
        extensions: { warnings },
      }),
    );
    expect(await uploadIntyg(new FormData())).toEqual({
      ok: false,
      error: "Bilden kan vara svår att läsa.",
      warnings,
    });
  });

  it("sends no dry_run field and gives other refusals as plain errors", async () => {
    api.mockRejectedValueOnce(
      new ApiError({ status: 400, title: "x", detail: "Otillåten filtyp." }),
    );
    const res = await uploadIntyg(new FormData());
    expect(res).toEqual({ ok: false, error: "Otillåten filtyp." });
    expect((api.mock.calls[0][1]!.body as FormData).has("dry_run")).toBe(false);
  });
});
