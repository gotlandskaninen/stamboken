import { beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError, fetchApi } from "@/lib/api";
import { revalidatePath } from "next/cache";
import {
  voidHerdTracking,
  correctHerdTracking,
  undoHerdTrackingOperation,
} from "@/app/(app)/stamboken/(dashboard)/individ/[number]/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const mockedFetch = vi.mocked(fetchApi);

beforeEach(() => vi.clearAllMocks());

describe("voidHerdTracking", () => {
  test("posts reason + operation id and revalidates the individual page", async () => {
    mockedFetch.mockResolvedValue({});
    const result = await voidHerdTracking(
      "G1274-2501",
      42,
      "Fel köpare",
      "op-1",
    );
    expect(result).toEqual({ success: true });
    expect(mockedFetch).toHaveBeenCalledWith("/v2/herd-tracking/42/void", {
      method: "POST",
      body: JSON.stringify({ reason: "Fel köpare", operation_id: "op-1" }),
    });
    expect(revalidatePath).toHaveBeenCalledWith(
      "/stamboken/individ/G1274-2501",
    );
  });

  test("returns the problem detail on an API error", async () => {
    mockedFetch.mockRejectedValue(
      new ApiError({
        status: 403,
        title: "Åtkomst nekad",
        detail: "Bara säljaren kan ångra försäljningen.",
      }),
    );
    expect(await voidHerdTracking("G1274-2501", 42, "x", "op")).toEqual({
      success: false,
      error: "Bara säljaren kan ångra försäljningen.",
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("correction and undo actions", () => {
  test("correctHerdTracking posts the payload to the corrections endpoint", async () => {
    mockedFetch.mockResolvedValue({});
    const payload = {
      operation_id: "op",
      void_ids: [21],
      events: [],
      reason: "r",
    };
    expect(await correctHerdTracking("G1-2511", payload)).toEqual({
      success: true,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/v2/individual/G1-2511/herd-tracking/corrections",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  });

  test("correctHerdTracking passes the ids of a 409's rows through", async () => {
    mockedFetch.mockRejectedValue(
      new ApiError({
        status: 409,
        title: "Konflikt",
        detail: "Det finns redan händelser samma dag.",
        extensions: {
          rows: [
            { id: 21, date: "2026-03-01", kind: "TRANSFER", herd: "G2" },
            { id: null, code: "I2" },
            { id: 22 },
          ],
        },
      }),
    );
    const payload = {
      operation_id: "op",
      void_ids: [],
      events: [],
      reason: "",
    };
    expect(await correctHerdTracking("G1-2511", payload)).toEqual({
      success: false,
      error: "Det finns redan händelser samma dag.",
      rows: [21, 22],
    });
  });

  test("undoHerdTrackingOperation posts the reason and its own operation id", async () => {
    mockedFetch.mockResolvedValue({});
    expect(
      await undoHerdTrackingOperation("G1-2511", "op-a", "Fel", "op-undo"),
    ).toEqual({ success: true });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/v2/herd-tracking/operations/op-a/undo",
      {
        method: "POST",
        body: JSON.stringify({ reason: "Fel", operation_id: "op-undo" }),
      },
    );
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/individ/G1-2511");
  });

  test("undoHerdTrackingOperation revalidates every individual in the response", async () => {
    mockedFetch.mockResolvedValue({
      undo_operation_id: "op-undo",
      individuals: [
        { number: "G1-2511", history: {} },
        { number: "G1-2512", history: {} },
      ],
    });
    await undoHerdTrackingOperation("G1-2511", "op-a", "Fel", "op-undo");
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/individ/G1-2511");
    expect(revalidatePath).toHaveBeenCalledWith("/stamboken/individ/G1-2512");
  });
});
