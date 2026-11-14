import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchApi } from "@/lib/api";
import {
  assignItem,
  changeState,
  confirmMask,
  takeItem,
  updateDocument,
  waitForParent,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const api = vi.mocked(fetchApi);
const body = (call: number) =>
  JSON.parse(api.mock.calls[call][1]!.body as string);

beforeEach(() => {
  vi.clearAllMocks();
  api.mockResolvedValue({});
});

describe("the queue's server actions", () => {
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
    await updateDocument(12, 31, { rotation: 90, waiting_for: ["X"], foo: 1 });
    expect(body(0)).toEqual({ rotation: 90 });
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

  it("send an empty mask list as a list (nothing to hide), never leave it out", async () => {
    await confirmMask(12, 31, []);
    expect(body(0)).toEqual({ mask_rects: [] });
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
});
