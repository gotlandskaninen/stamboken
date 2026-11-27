import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { view } from "./fixtures";

const requestHeaders = new Headers();
const fetchApi = vi.fn();
vi.mock("next/headers", () => ({ headers: async () => requestHeaders }));
vi.mock("@/lib/api", () => ({ fetchApi, ApiError: Error }));
vi.mock("next/navigation", () => ({ useRouter: () => ({}) }));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

it("hides the sign-in tip on the configured test host", async () => {
  vi.stubEnv("TEST_HOST", "demo.example.test");
  const { default: RapportPage } = await import("@/app/(app)/rapport/page");
  for (const [host, show] of [
    ["demo.example.test:443", false],
    ["report.example.org", true],
  ] as const) {
    requestHeaders.set("host", host);
    fetchApi.mockResolvedValueOnce([
      { code_id: 1, herd: "G9001", year: 2026, login_tip: true },
    ]);
    fetchApi.mockResolvedValueOnce(view({ access: "code", source: "link" }));
    render(await RapportPage({ searchParams: Promise.resolve({}) }));
    expect(!!screen.queryByRole("link", { name: "Logga in" })).toBe(show);
    cleanup();
  }
});
