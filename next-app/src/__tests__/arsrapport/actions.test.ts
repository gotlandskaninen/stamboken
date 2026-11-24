import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchApi = vi.fn();
let modeCookie: string | undefined = "demo";
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (modeCookie ? { value: modeCookie } : undefined),
  }),
}));
vi.mock("@/lib/api", () => ({
  fetchApi: (...a: unknown[]) => fetchApi(...a),
  ApiError: class extends Error {
    status = 0;
    title = "";
    detail = "";
    extensions = {};
  },
}));

import {
  activateGenebank,
  dryRun,
  newLink,
  saveDraft,
  saveRound,
  sendTestMail,
  setOnTime,
  submitReport,
  withdrawReport,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/actions";
import { getGenebankHerds as linkHerds } from "@/app/(app)/rapport/actions";
import { uploadPhoto } from "@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions";
import { ApiError } from "@/lib/api";
import {
  SUBMIT_TIMEOUT_MS,
  emptyState,
  toBody,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

const body = toBody(emptyState(), "k", null);

beforeEach(() => {
  modeCookie = "demo";
  fetchApi.mockReset();
  fetchApi.mockResolvedValue({});
});

describe("arsrapport actions", () => {
  it("gives dryRun, submitReport and withdrawReport the long timeout", async () => {
    await dryRun("G9001", 2026, body, "demo");
    await submitReport("G9001", 2026, body, "demo");
    await withdrawReport("G9001", 2026, 1, "skäl", "demo");
    for (const call of fetchApi.mock.calls)
      expect(call[1]).toMatchObject({ timeout: SUBMIT_TIMEOUT_MS });
  });
  it("leaves saveDraft on the default timeout and adds ?post=", async () => {
    await saveDraft(
      "G9001",
      2026,
      toBody(emptyState(), "", null),
      null,
      "k",
      null,
      "demo",
      12,
    );
    expect(fetchApi.mock.calls[0][0]).toBe(
      "/v2/arsrapport/besattning/G9001/2026/utkast?post=12",
    );
    expect(fetchApi.mock.calls[0][1]).not.toHaveProperty("timeout");
  });
  it("refuses a herd, year or post that does not belong in a URL", async () => {
    for (const r of [
      await dryRun("../x", 2026, body, "demo"),
      await dryRun("G9001", 20.5, body, "demo"),
      await submitReport("G9001", 2026, body, "demo", -1),
    ])
      expect(r.ok).toBe(false);
    expect(fetchApi).not.toHaveBeenCalled();
  });
  it("answers a dropped connection as a 502 the form can show", async () => {
    fetchApi.mockRejectedValue(new Error("fetch failed"));
    const r = await submitReport("G9001", 2026, body, "demo");
    expect(r).toMatchObject({ ok: false, problem: { status: 502 } });
  });
  it("refuses every write whose expected environment is not the cookie's, before calling the API", async () => {
    modeCookie = "prod"; // switched after the call was queued
    const results = [
      await saveDraft(
        "G9001",
        2026,
        toBody(emptyState(), "", null),
        null,
        "k",
        null,
        "demo",
      ),
      await dryRun("G9001", 2026, body, "demo"),
      await submitReport("G9001", 2026, body, "demo"),
      await withdrawReport("G9001", 2026, 1, undefined, "demo"),
    ];
    for (const r of results)
      expect(r).toMatchObject({ ok: false, problem: { status: 400 } });
    expect(fetchApi).not.toHaveBeenCalled();
  });
  it("sends the round and status writes to their routes and refuses a stale environment", async () => {
    await saveRound(2026, { deadline: "2027-02-07" }, "demo");
    await activateGenebank(2026, 3, "demo");
    await setOnTime("G9001", 2026, null, "demo");
    expect(
      fetchApi.mock.calls.map((c) => [c[0], c[1].method, c[1].body]),
    ).toEqual([
      ["/v2/arsrapport/rundor/2026", "PUT", '{"deadline":"2027-02-07"}'],
      ["/v2/arsrapport/rundor/2026/genbanker/3/aktivera", "POST", "{}"],
      [
        "/v2/arsrapport/besattning/G9001/2026/i-tid",
        "POST",
        '{"on_time":null}',
      ],
    ]);
    fetchApi.mockClear();
    expect((await saveRound(2026, { deadline: "31 jan" }, "demo")).ok).toBe(
      false,
    );
    expect((await activateGenebank(2026, 0, "demo")).ok).toBe(false);
    modeCookie = "prod";
    for (const r of [
      await saveRound(2026, {}, "demo"),
      await activateGenebank(2026, 3, "demo"),
      await setOnTime("G9001", 2026, true, "demo"),
    ])
      expect(r).toMatchObject({ ok: false, problem: { status: 400 } });
    expect(fetchApi).not.toHaveBeenCalled();
  });
  it("sends Ny länk and the test mail to their routes, and refuses a bad herd or genebank", async () => {
    await newLink("G9001", 2026, "demo");
    await sendTestMail(2026, 3, "demo");
    expect(fetchApi.mock.calls.map((c) => [c[0], c[1].method])).toEqual([
      ["/v2/arsrapport/besattning/G9001/2026/ny-lank", "POST"],
      ["/v2/arsrapport/rundor/2026/genbanker/3/provmejl", "POST"],
    ]);
    fetchApi.mockClear();
    for (const r of [
      await newLink("../x", 2026, "demo"),
      await sendTestMail(2026, 0, "demo"),
    ])
      expect(r).toMatchObject({ ok: false, problem: { status: 400 } });
    expect(fetchApi).not.toHaveBeenCalled();
  });
});

describe("the link's herd picker", () => {
  it("asks the report's own route on production and gives the dialog its shape", async () => {
    const herds = [{ herd: "G9002", herd_name: "Gården", is_active: true }];
    fetchApi.mockResolvedValue({ herds });
    expect(await linkHerds("G9001", 2025, 1)).toEqual({
      success: true,
      herds,
    });
    expect(fetchApi.mock.calls[0][0]).toBe(
      "/v2/arsrapport/besattning/G9001/2025/besattningar?via=lank",
    );
    expect(fetchApi.mock.calls[0][1]).toMatchObject({
      method: "GET",
      forceProd: true,
    });
  });
  it("passes a refusal on as the dialog's error, and asks nothing for a bad herd", async () => {
    const refusal = { status: 404, title: "Hittades inte", detail: "Nej" };
    // the mocked ApiError takes no fields, so they are set on it as the real one sets them
    fetchApi.mockRejectedValue(Object.assign(new ApiError(refusal), refusal));
    expect(await linkHerds("G9001", 2025, 1)).toEqual({
      success: false,
      error: "Nej",
    });
    fetchApi.mockClear();
    expect((await linkHerds("../x", 2025, 1)).success).toBe(false);
    expect(fetchApi).not.toHaveBeenCalled();
  });
});

describe("the report's photo upload", () => {
  it("names a purchase notice's photo, which the server never reads", async () => {
    await uploadPhoto("G9001", 2025, new FormData(), undefined, "kop");
    await uploadPhoto("G9001", 2025, new FormData(), undefined, "inskick");
    await uploadPhoto("G9001", 2025, new FormData());
    expect(fetchApi.mock.calls.map((c) => c[0])).toEqual([
      "/v2/arsrapport/besattning/G9001/2025/foto?syfte=kop&via=lank",
      "/v2/arsrapport/besattning/G9001/2025/foto?syfte=inskick&via=lank",
      "/v2/arsrapport/besattning/G9001/2025/foto?via=lank",
    ]);
  });
});
