import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode";
import {
  alarmText,
  isFuture,
  rowAction,
  statusLabel,
  STATUS_LABEL,
} from "@/app/(app)/stamboken/(dashboard)/admin/utskick/lib";
import { Alarms } from "@/app/(app)/stamboken/(dashboard)/admin/utskick/Alarms";
import {
  cancelMessage,
  retryMessage,
} from "@/app/(app)/stamboken/(dashboard)/admin/utskick/actions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode",
  () => ({ requireAdminProdMode: vi.fn() }),
);
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

describe("status mapping", () => {
  it("labels all eight API statuses in Swedish", () => {
    expect(Object.keys(STATUS_LABEL)).toHaveLength(8);
    expect(statusLabel("queued")).toBe("Köad");
    expect(statusLabel("cancelled")).toBe("Stoppad");
    expect(statusLabel("bounced")).toBe("Studsade");
  });
  it("shows an unknown status as is", () => {
    expect(statusLabel("weird")).toBe("weird");
  });
});

describe("rowAction", () => {
  it.each([
    ["failed", "retry"],
    ["bounced", "retry"],
    ["queued", "cancel"],
    ["sending", null],
    ["sent", null],
    ["blocked", null],
    ["logged", null],
    ["cancelled", null],
  ])("%s -> %s", (status, action) => {
    expect(rowAction(status)).toBe(action);
  });
});

describe("alarms", () => {
  it("maps known codes to the Swedish texts, unknown to the API message", () => {
    expect(alarmText({ code: "queue_stalled", message: "x" })).toBe(
      "Kön står still. Schemaläggaren kör inte.",
    );
    expect(alarmText({ code: "relay_refusing", message: "x" })).toContain(
      "Kontrollera reläets inställningar.",
    );
    expect(alarmText({ code: "new_one", message: "Nytt larm" })).toBe(
      "Nytt larm",
    );
  });

  it("renders alarms, last sent and a future pause", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    render(
      <Alarms
        now={now}
        data={{
          alarms: [{ code: "queue_stalled", message: "x" }],
          last_sent_at: "2026-01-01T10:00:00Z",
          paused_until: "2026-01-01T13:00:00Z",
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Kön står still.");
    expect(screen.getByText(/Senaste utskick: /)).toHaveTextContent(
      "Pausad till",
    );
  });

  it("renders no alarm and no pause when all is well", () => {
    render(
      <Alarms
        now={Date.parse("2026-01-01T12:00:00Z")}
        data={{
          alarms: [],
          last_sent_at: null,
          paused_until: "2026-01-01T11:00:00Z",
        }}
      />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/Senaste utskick: —/)).not.toHaveTextContent(
      "Pausad",
    );
  });

  it("isFuture", () => {
    expect(isFuture(null)).toBe(false);
    expect(isFuture("2999-01-01T00:00:00Z")).toBe(true);
  });
});

describe("actions", () => {
  it("POST the retry and cancel endpoints", async () => {
    vi.mocked(fetchApi).mockResolvedValue({});
    await retryMessage(7);
    await cancelMessage(8);
    expect(fetchApi).toHaveBeenCalledWith(
      "/v2/mail/messages/7/retry",
      expect.objectContaining({ method: "POST", forceProd: true }),
    );
    expect(fetchApi).toHaveBeenCalledWith(
      "/v2/mail/messages/8/cancel",
      expect.objectContaining({ method: "POST", forceProd: true }),
    );
  });

  it("returns the API's Swedish detail on 409", async () => {
    vi.mocked(fetchApi).mockRejectedValue(
      new ApiError({
        status: 409,
        title: "Fel status",
        detail: "Bara köade utskick kan stoppas.",
      }),
    );
    await expect(cancelMessage(1)).resolves.toEqual({
      error: "Bara köade utskick kan stoppas.",
    });
  });

  it("does not call the API outside prod mode", async () => {
    vi.mocked(requireAdminProdMode).mockRejectedValueOnce(
      new Error("NEXT_REDIRECT"),
    );
    await expect(retryMessage(1)).rejects.toThrow("NEXT_REDIRECT");
    expect(fetchApi).not.toHaveBeenCalled();
  });
});
