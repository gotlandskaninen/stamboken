import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { fetchApi } from "@/lib/api";

let mode = "prod";
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ value: mode }) }),
}));
vi.mock("@/lib/api", () => ({ fetchApi: vi.fn() }));
const markUploadsSeen = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/actions", () => ({
  markUploadsSeen: () => markUploadsSeen(),
}));
vi.mock("@/components/shell/Masthead", () => ({ Masthead: () => null }));

import MinaInskickPage from "@/app/(app)/stamboken/(dashboard)/inskick/page";

const api = vi.mocked(fetchApi);
beforeEach(() => {
  vi.clearAllMocks();
  mode = "prod";
  vi.stubEnv("API_TEST_INTERNAL_URL", "https://demo.example.org");
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const demoMessage =
  "Du är i testmiljön. Det du har skickat in till riktiga Stamboken visas inte här.";

describe("Mina inskick", () => {
  it("only reads while it renders, and marks the notices seen once it is shown", async () => {
    api.mockResolvedValueOnce({ items: [] });
    const page = await MinaInskickPage();
    expect(api.mock.calls).toEqual([
      ["/v2/inkorg/mina-inskick", { isolateDemo: true }],
    ]);
    expect(markUploadsSeen).not.toHaveBeenCalled();
    render(page);
    expect(markUploadsSeen).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(demoMessage)).toBeNull();
  });

  it("shows the demo notice alongside the demo submissions", async () => {
    mode = "demo";
    api.mockResolvedValueOnce({
      items: [
        {
          id: 7,
          herd: "G1",
          documents: 1,
          status: "ny",
          received_at: "2026-01-01",
        },
      ],
    });
    render(await MinaInskickPage());
    expect(screen.getByText(demoMessage)).toBeTruthy();
    expect(screen.getByText("ärende 7")).toBeTruthy();
  });

  it("shows the notice and an empty list when the demo API is missing", async () => {
    mode = "demo";
    vi.stubEnv("API_TEST_INTERNAL_URL", undefined);
    render(await MinaInskickPage());
    expect(screen.getByText(demoMessage)).toBeTruthy();
    expect(screen.getByText(/Här ser du de intyg/)).toBeTruthy();
    expect(api).not.toHaveBeenCalled();
    expect(markUploadsSeen).not.toHaveBeenCalled();
  });
});
