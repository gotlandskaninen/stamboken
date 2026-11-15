import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchApi = vi.fn();
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
  dryRun,
  saveDraft,
  submitReport,
  withdrawReport,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/actions";
import {
  SUBMIT_TIMEOUT_MS,
  emptyState,
  toBody,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

const body = toBody(emptyState(), "k", null);

beforeEach(() => {
  fetchApi.mockReset();
  fetchApi.mockResolvedValue({});
});

describe("arsrapport actions", () => {
  it("gives dryRun, submitReport and withdrawReport the long timeout", async () => {
    await dryRun("G9001", 2026, body);
    await submitReport("G9001", 2026, body);
    await withdrawReport("G9001", 2026, 1, "skäl");
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
      12,
    );
    expect(fetchApi.mock.calls[0][0]).toBe(
      "/v2/arsrapport/besattning/G9001/2026/utkast?post=12",
    );
    expect(fetchApi.mock.calls[0][1]).not.toHaveProperty("timeout");
  });
  it("refuses a herd, year or post that does not belong in a URL", async () => {
    for (const r of [
      await dryRun("../x", 2026, body),
      await dryRun("G9001", 20.5, body),
      await submitReport("G9001", 2026, body, -1),
    ])
      expect(r.ok).toBe(false);
    expect(fetchApi).not.toHaveBeenCalled();
  });
  it("answers a dropped connection as a 502 the form can show", async () => {
    fetchApi.mockRejectedValue(new Error("fetch failed"));
    const r = await submitReport("G9001", 2026, body);
    expect(r).toMatchObject({ ok: false, problem: { status: 502 } });
  });
});
