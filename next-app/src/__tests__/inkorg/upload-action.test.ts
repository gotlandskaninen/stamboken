import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { revalidatePath } from "next/cache";
import type { Mode } from "@/lib/mode";

let mode: Mode | undefined = "demo";
let session = true;
vi.mock("next/headers", () => ({
  cookies: async () => {
    const all = [
      ...(mode ? [{ name: "sb_mode", value: mode }] : []),
      ...(session ? [{ name: "session", value: "test" }] : []),
    ];
    return {
      get: (name: string) => all.find((c) => c.name === name),
      getAll: () => all,
    };
  },
  headers: async () => new Headers(),
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const actions = () =>
  import("@/app/(app)/stamboken/(dashboard)/inskick/ny/actions");
const send = vi.fn<typeof fetch>();
beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  mode = "demo";
  session = true;
  vi.stubGlobal("fetch", send);
  vi.stubEnv("API_INTERNAL_URL", "http://api:9090");
  vi.stubEnv("API_TEST_INTERNAL_URL", "http://api-test:9090");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("uploadIntyg", () => {
  it.each([
    ["demo", "api-test"],
    ["prod", "api"],
  ] as const)("sends the %s submission only to %s", async (formMode, host) => {
    mode = formMode;
    const data = new FormData();
    data.append("files", new File(["intyg"], "intyg.pdf"));
    send.mockResolvedValueOnce(
      Response.json({ item: { id: 7 }, documents: [] }),
    );
    expect(await (await actions()).uploadIntyg(data, formMode)).toEqual({
      ok: true,
      documents: [],
      itemId: 7,
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(
      `http://${host}:9090/api/v2/inkorg/upload`,
      expect.objectContaining({ method: "POST", body: data }),
    );
    expect(data.has("dry_run")).toBe(false);
  });

  it.each([
    "missing demo API",
    "demo URL pointing to production",
    "expired session",
    "mode switch",
  ])("stores nothing after a %s", async (reason) => {
    if (reason === "missing demo API") vi.stubEnv("API_TEST_INTERNAL_URL", "");
    if (reason === "demo URL pointing to production")
      vi.stubEnv("API_TEST_INTERNAL_URL", "http://api:9090");
    if (reason === "expired session") session = false;
    if (reason === "mode switch") mode = "prod";
    const data = new FormData();
    data.set("accept_warnings", "1");
    expect(await (await actions()).uploadIntyg(data, "demo")).toMatchObject({
      ok: false,
    });
    expect(send).not.toHaveBeenCalled();
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("forwards the default demo mode so the receiving API can check its instance", async () => {
    mode = undefined;
    send.mockResolvedValueOnce(Response.json({ documents: [] }));
    const { uploadIntyg } = await actions();
    expect((await uploadIntyg(new FormData(), "demo")).ok).toBe(true);
    expect(send).toHaveBeenCalledWith(
      "http://api-test:9090/api/v2/inkorg/upload",
      expect.objectContaining({
        headers: expect.objectContaining({
          Cookie: "session=test; sb_mode=demo",
        }),
      }),
    );
  });

  it("hands back per-file warnings and other refusals", async () => {
    const { uploadIntyg } = await actions();
    const warnings = [{ file: 0, page: null, warnings: ["suddig"] }];
    const detail = "Bilden kan vara svår att läsa.";
    send.mockResolvedValueOnce(
      Response.json({ detail, warnings }, { status: 409 }),
    );
    expect(await uploadIntyg(new FormData(), "demo")).toEqual({
      ok: false,
      error: detail,
      warnings,
    });
    send.mockResolvedValueOnce(
      Response.json({ detail: "Otillåten filtyp." }, { status: 400 }),
    );
    expect(await uploadIntyg(new FormData(), "demo")).toEqual({
      ok: false,
      error: "Otillåten filtyp.",
    });
  });
});

describe("markUploadsSeen", () => {
  it.each([
    ["demo", "api-test"],
    ["prod", "api"],
  ] as const)("marks notices in %s on %s", async (selected, host) => {
    mode = selected;
    send.mockResolvedValueOnce(Response.json({ read: 2 }));
    await (await actions()).markUploadsSeen();
    expect(send).toHaveBeenCalledWith(
      `http://${host}:9090/api/v2/inkorg/mina-inskick/sedda`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken", "layout");
  });

  it("leaves the menu alone when nothing was unread, and swallows a failure", async () => {
    const { markUploadsSeen } = await actions();
    send.mockResolvedValueOnce(Response.json({ read: 0 }));
    await markUploadsSeen();
    send.mockRejectedValueOnce(new Error("nere"));
    await markUploadsSeen();
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("certificate photos in the yearly report", () => {
  const purchase = {
    number: "G1-2511",
    from_herd: "G1",
    date: "2026-01-01",
    documents: [{ id: 1, doc_type: "intyg" as const }],
  };
  it("keeps both the photo and its submission off production when the demo API is missing", async () => {
    vi.stubEnv("API_TEST_INTERNAL_URL", "");
    const { uploadPhoto } = await import(
      "@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions"
    );
    const { sendPurchasePhotos } = await import(
      "@/app/(app)/stamboken/(dashboard)/arsrapport/actions"
    );
    expect((await uploadPhoto("G1", 2026, new FormData(), "demo")).ok).toBe(
      false,
    );
    expect((await sendPurchasePhotos("G1", 2026, purchase, "demo")).ok).toBe(
      false,
    );
    expect(send).not.toHaveBeenCalled();
  });

  it("allows the personal link without a mode cookie and refuses its upload routes in demo mode", async () => {
    const { uploadPhoto } = await import(
      "@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions"
    );
    const { sendPurchasePhotos } = await import("@/app/(app)/rapport/actions");
    const data = new FormData();
    expect((await uploadPhoto("G1", 2026, data)).ok).toBe(false);
    expect((await sendPurchasePhotos("G1", 2026, purchase)).ok).toBe(false);
    expect(send).not.toHaveBeenCalled();

    mode = undefined;
    send.mockResolvedValueOnce(Response.json({ item_id: 1, document_id: 1 }));
    expect((await uploadPhoto("G1", 2026, data)).ok).toBe(true);
    expect(send.mock.calls[0][0]).toBe(
      "http://api:9090/api/v2/arsrapport/besattning/G1/2026/foto",
    );
  });
});
