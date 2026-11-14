import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const fetchApi = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchApi,
}));
vi.mock("@/lib/auth", () => ({
  requireUser: async () => ({ id: 3, fullname: "Konto 3" }),
}));
vi.mock("@/lib/inkorg-server", () => ({
  requireQueueWorker: async () => undefined,
  fetchHandlers: async () => [],
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/GmailAlarm", () => ({
  GmailAlarm: () => null,
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/QueueControls", () => ({
  AssignHerd: () => null,
  RowActions: () => null,
}));

import InkorgPage from "@/app/(app)/stamboken/(dashboard)/inkorg/page";

beforeEach(() => {
  fetchApi.mockReset();
  fetchApi.mockImplementation(async (path: string) =>
    path.startsWith("/v2/inkorg?")
      ? { items: [], total: 0, counts: {}, scope: "mina", my_genebanks: [1] }
      : { genebanks: [] },
  );
});
afterEach(cleanup);

const show = async (sp: Record<string, string> = {}) =>
  render(await InkorgPage({ searchParams: Promise.resolve(sp) }));

describe("the queue list's scope switch", () => {
  it("marks the scope the server applied and sends none unless chosen", async () => {
    await show();
    expect(fetchApi.mock.calls[0][0]).not.toContain("scope");
    expect(
      screen.getByRole("link", { name: "Mina genbanker" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Alla genbanker" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      screen.getByRole("link", { name: "Alla genbanker" }),
    ).toHaveAttribute("href", "/stamboken/inkorg?scope=alla");
  });

  it("passes the chosen scope on to the API", async () => {
    await show({ scope: "alla" });
    expect(fetchApi.mock.calls[0][0]).toContain("scope=alla");
  });
});
