import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import { askBreeder } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/ask";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const api = vi.mocked(fetchApi);

beforeEach(() => {
  vi.clearAllMocks();
  api.mockResolvedValue({});
});

describe("Fråga uppfödaren", () => {
  it("never puts an id that is not a whole number into the URL", async () => {
    const crop = { x: 0, y: 0, w: 1, h: 1 };
    expect((await askBreeder(1.5, "Fråga")).ok).toBe(false);
    expect((await askBreeder(12, "Fråga", { document: -1, crop })).ok).toBe(
      false,
    );
    expect(api).not.toHaveBeenCalled();
  });

  it("sends the question, and the frame only with its document", async () => {
    const crop = { x: 0.1, y: 0.2, w: 0.3, h: 0.4 };
    await askBreeder(12, "Vilken färg?");
    await askBreeder(12, "Vilken färg?", { document: 31, crop });
    expect(
      api.mock.calls.map((c) => [c[0], JSON.parse(c[1]!.body as string)]),
    ).toEqual([
      ["/v2/inkorg/12/fraga", { text: "Vilken färg?" }],
      ["/v2/inkorg/12/fraga", { text: "Vilken färg?", document: 31, crop }],
    ]);
  });
});
