import { describe, it, expect, vi, beforeEach } from "vitest";

const { cookieGetMock, redirectMock } = vi.hoisted(() => ({
  cookieGetMock: vi.fn(),
  redirectMock: vi.fn((path: string) => {
    // Next's redirect() throws — emulate so callers' control flow matches prod.
    throw new Error(`redirect:${path}`);
  }),
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookieGetMock, getAll: () => [] })),
}));
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

import { requireAdminProdMode } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdminProdMode";

function setModeCookie(value: string | undefined) {
  cookieGetMock.mockImplementation((name: string) =>
    name === "sb_mode" && value !== undefined ? { name, value } : undefined,
  );
}

describe("requireAdminProdMode", () => {
  beforeEach(() => {
    cookieGetMock.mockReset();
    redirectMock.mockClear();
  });

  it("throws redirect to /stamboken/admin when sb_mode is missing", async () => {
    setModeCookie(undefined);
    await expect(requireAdminProdMode()).rejects.toThrow(
      "redirect:/stamboken/admin",
    );
    expect(redirectMock).toHaveBeenCalledWith("/stamboken/admin");
  });

  it("throws redirect when sb_mode is demo", async () => {
    setModeCookie("demo");
    await expect(requireAdminProdMode()).rejects.toThrow(
      "redirect:/stamboken/admin",
    );
  });

  it("throws redirect for unknown cookie values (parseMode fail-safe)", async () => {
    setModeCookie("PROD"); // wrong case — parseMode allow-lists exact "prod"
    await expect(requireAdminProdMode()).rejects.toThrow(
      "redirect:/stamboken/admin",
    );
  });

  it("returns void when sb_mode is prod", async () => {
    setModeCookie("prod");
    await expect(requireAdminProdMode()).resolves.toBeUndefined();
    expect(redirectMock).not.toHaveBeenCalled();
  });
});
