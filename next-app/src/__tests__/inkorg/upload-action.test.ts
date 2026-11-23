import { beforeEach, describe, expect, it, vi } from "vitest";
import { revalidatePath } from "next/cache";
import { ApiError, fetchApi } from "@/lib/api";
import {
  markUploadsSeen,
  uploadIntyg,
} from "@/app/(app)/stamboken/(dashboard)/inskick/ny/actions";

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

  it("sends to production in every mode, so the upload outlives the night", async () => {
    api.mockResolvedValueOnce({ item: { id: 7 }, documents: [] });
    expect(await uploadIntyg(new FormData())).toEqual({
      ok: true,
      documents: [],
      itemId: 7,
    });
    expect(api.mock.calls[0][1]).toMatchObject({ forceProd: true });
  });
});

describe("markUploadsSeen", () => {
  it("posts to production and refreshes the menu when notices were read", async () => {
    api.mockResolvedValueOnce({ read: 2 });
    await markUploadsSeen();
    expect(api).toHaveBeenCalledWith("/v2/inkorg/mina-inskick/sedda", {
      method: "POST",
      forceProd: true,
    });
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken", "layout");
  });

  it("leaves the menu alone when nothing was unread, and swallows a failure", async () => {
    api.mockResolvedValueOnce({ read: 0 });
    await markUploadsSeen();
    api.mockRejectedValueOnce(new Error("nere"));
    await markUploadsSeen();
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
