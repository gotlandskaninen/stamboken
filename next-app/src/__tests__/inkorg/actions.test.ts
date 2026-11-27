import { beforeEach, describe, expect, it, vi } from "vitest";
import { revalidatePath } from "next/cache";
import { ApiError, fetchApi } from "@/lib/api";
import {
  assignHerd,
  assignItem,
  changeState,
  confirmMask,
  previewHerd,
  releaseItem,
  saveCertificate,
  takeItem,
  undoAssignment,
  updateDocument,
  waitForParent,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ value: "prod" }) }),
}));
const revalidated = vi.mocked(revalidatePath);

const api = vi.mocked(fetchApi);
const body = (call: number) =>
  JSON.parse(api.mock.calls[call][1]!.body as string);

beforeEach(() => {
  vi.clearAllMocks();
  api.mockResolvedValue({});
});

describe("the queue's server actions", () => {
  it("sends the displayed assignment with the conditional takeover request", async () => {
    const expected = {
      assigned_to: 7,
      assigned_at: "2026-11-14T08:00:00.123456+00:00",
    };
    await takeItem(12, expected);
    expect(api.mock.calls[0][0]).toBe("/v2/inkorg/12/ta-over");
    expect(api.mock.calls[0][1]?.method).toBe("PUT");
    expect(body(0)).toEqual(expected);
  });

  it("previews a herd without refreshing the queue and submits the reviewed revision", async () => {
    await previewHerd(" g9001 ");
    expect(api.mock.calls[0][0]).toBe("/v2/inkorg/tilldela?herd=G9001");
    expect(api.mock.calls[0][1]?.method).toBe("GET");
    expect(revalidated).not.toHaveBeenCalled();
    await assignHerd(" g9001 ", 7, "reviewed");
    expect(body(1)).toEqual({
      herd: "G9001",
      user_id: 7,
      revision: "reviewed",
    });
    expect((await assignHerd("G9001", 7, "")).ok).toBe(false);
  });

  it("releases the item and submits the server's undo receipt", async () => {
    await releaseItem(12);
    expect(api.mock.calls[0][0]).toBe("/v2/inkorg/12/slapp");
    await undoAssignment("receipt");
    expect(api.mock.calls[1][0]).toBe("/v2/inkorg/angra");
    expect(body(1)).toEqual({ undo: "receipt" });
    expect(revalidated).toHaveBeenCalledWith("/stamboken/inkorg", "layout");
  });
  it("never put an id that is not a whole number into the URL", async () => {
    for (const bad of [0, -1, 1.5, NaN, "12/../x" as unknown as number]) {
      expect((await takeItem(bad)).ok).toBe(false);
      expect((await updateDocument(1, bad, { rotation: 90 })).ok).toBe(false);
    }
    expect(api).not.toHaveBeenCalled();
  });

  it("send user_id and duplicate_of as numbers", async () => {
    await assignItem(12, 7);
    expect(body(0)).toEqual({ user_id: 7 });
    await changeState(12, "dubblett", { duplicate_of: 9 });
    expect(body(1)).toEqual({ state: "dubblett", duplicate_of: 9 });
    expect((await changeState(12, "dubblett", { duplicate_of: NaN })).ok).toBe(
      false,
    );
  });

  it("refuse a state …/lage cannot take", async () => {
    expect((await changeState(12, "ny")).ok).toBe(false);
    expect(api).not.toHaveBeenCalled();
  });

  it("let a message be closed as klar", async () => {
    await changeState(12, "klar");
    expect(body(0)).toEqual({ state: "klar" });
  });

  it("pass only the document fields the UI changes", async () => {
    await updateDocument(12, 31, {
      rotation: 90,
      straighten: 2.5,
      waiting_for: ["X"],
      foo: 1,
    });
    expect(body(0)).toEqual({ rotation: 90, straighten: 2.5 });
  });

  it("refuse a document change made for the other environment", async () => {
    const res = await updateDocument(12, 31, { dismissed: true }, "demo");
    expect(res.ok).toBe(false);
    expect(api).not.toHaveBeenCalled();
    await updateDocument(12, 31, { dismissed: true }, "prod");
    expect(body(0)).toEqual({ dismissed: true });
  });

  it("väntar på förälder: the number on the document first, then the state", async () => {
    await waitForParent(12, 31, [" g9001-2412", ""]);
    expect(api.mock.calls.map((c) => [c[0], c[1]!.method])).toEqual([
      ["/v2/inkorg/12/dokument/31", "PATCH"],
      ["/v2/inkorg/12/lage", "POST"],
    ]);
    expect(body(0)).toEqual({ waiting_for: ["G9001-2412"] });
    expect(body(1)).toEqual({ state: "vantar_foralder" });
  });

  it("väntar på förälder stops when the number is refused", async () => {
    api.mockRejectedValueOnce(
      new ApiError({
        status: 400,
        title: "Ogiltig begäran",
        detail: "G9001-2412 finns redan i Stamboken.",
      }),
    );
    const res = await waitForParent(12, 31, ["G9001-2412"]);
    expect(res).toMatchObject({
      ok: false,
      problem: { detail: "G9001-2412 finns redan i Stamboken." },
    });
    expect(api).toHaveBeenCalledTimes(1);
  });

  it("send the rotation together with the rectangles drawn in it", async () => {
    const rect = { x: 0, y: 0, w: 0.3, h: 1 };
    await confirmMask(12, 31, 90, 0, [rect], null);
    expect(body(0)).toEqual({
      rotation: 90,
      straighten: 0,
      mask_rects: [rect],
      copy_frame: null,
      matches_registry: false,
    });
  });

  it("send the frame around the copy rounded inside the image, and no no_personal_data beside it", async () => {
    const frame = { x: 0.33333333, y: 0, w: 0.66669999, h: 1.00001 };
    await confirmMask(12, 31, 90, 0, [], frame, true);
    expect(body(0)).toEqual({
      rotation: 90,
      straighten: 0,
      mask_rects: [],
      copy_frame: { x: 0.3334, y: 0, w: 0.6666, h: 1 }, // inwards: the copy keeps no more than shown
      matches_registry: false,
    });
  });

  it("send whether the handler found the certificate and the registry in agreement", async () => {
    const rect = { x: 0, y: 0, w: 0.3, h: 1 };
    await confirmMask(12, 31, 0, 0, [rect], null, false, true);
    expect(body(0)).toMatchObject({ matches_registry: true });
  });

  it("need the explicit no_personal_data for an empty list without a frame", async () => {
    expect((await confirmMask(12, 31, 0, 0, [], null)).ok).toBe(false);
    // A frame over the whole photo leaves nothing out: no cover either.
    const whole = { x: 0, y: 0, w: 1, h: 1 };
    expect((await confirmMask(12, 31, 0, 0, [], whole)).ok).toBe(false);
    expect(api).not.toHaveBeenCalled();
    await confirmMask(12, 31, 180, 0, [], null, true);
    expect(body(0)).toEqual({
      rotation: 180,
      straighten: 0,
      mask_rects: [],
      copy_frame: null,
      no_personal_data: true,
      matches_registry: false,
    });
  });

  it("refuse a rotation that is not a quarter turn", async () => {
    expect((await confirmMask(12, 31, 45, 0, [], null)).ok).toBe(false);
    for (const angle of [15.5, NaN, "2" as unknown as number])
      expect((await confirmMask(12, 31, 0, angle, [], null, true)).ok).toBe(
        false,
      );
    expect(api).not.toHaveBeenCalled();
  });

  it("hand the whole problem back, extensions included", async () => {
    api.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        title: "number_conflict",
        detail: "…",
        extensions: { stamboken_number: "G9001-2513" },
      }),
    );
    expect(await takeItem(12)).toEqual({
      ok: false,
      problem: {
        status: 409,
        title: "number_conflict",
        detail: "…",
        extensions: { stamboken_number: "G9001-2513" },
      },
    });
  });

  it("revalidate the item also when the API refuses with 409", async () => {
    api.mockRejectedValueOnce(
      new ApiError({ status: 409, title: "Conflict", detail: "Taget." }),
    );
    expect((await takeItem(12)).ok).toBe(false);
    expect(revalidated).toHaveBeenCalledWith("/stamboken/inkorg/12");
  });

  it("do not revalidate after other refusals", async () => {
    api.mockRejectedValueOnce(
      new ApiError({ status: 400, title: "x", detail: "Nej." }),
    );
    await takeItem(12);
    expect(revalidated).not.toHaveBeenCalled();
  });

  it("answer a dropped connection to the API as a refusal instead of throwing", async () => {
    api.mockRejectedValueOnce(new TypeError("fetch failed"));
    expect(await saveCertificate(12, 31, {})).toMatchObject({
      ok: false,
      problem: { detail: "Det gick inte att nå servern. Försök igen." },
    });
  });
});
