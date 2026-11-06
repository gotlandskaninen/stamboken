import { describe, it, expect, vi, beforeEach } from "vitest";

/**
 * requireDashboardSession — the CR-02 demo-lockout branch logic.
 *
 * A demo-mode /user 401 can mean either "dead session" OR "valid prod session
 * whose user row is missing in herdbook_demo" (account created after the last
 * nightly sync). The resolver must re-check /user against PROD (forceProd) and
 * only then decide: friendly page (missing-in-demo) vs sign-in redirect.
 */

const { fetchApiMock, MockApiError, redirectMock, cookieGetMock } = vi.hoisted(
  () => {
    class MockApiError extends Error {
      status: number;
      title: string;
      detail: string;
      constructor(p: { status: number; title?: string; detail?: string }) {
        super(p.detail ?? "err");
        this.status = p.status;
        this.title = p.title ?? "";
        this.detail = p.detail ?? "";
      }
    }
    return {
      fetchApiMock: vi.fn(),
      MockApiError,
      redirectMock: vi.fn((url: string): never => {
        throw new Error(`REDIRECT:${url}`);
      }),
      cookieGetMock: vi.fn(),
    };
  },
);

vi.mock("@/lib/api", () => ({
  fetchApi: fetchApiMock,
  ApiError: MockApiError,
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: cookieGetMock, getAll: () => [] }),
  headers: async () => ({ get: () => null }),
}));

vi.mock("next/navigation", () => ({ redirect: redirectMock }));

import { requireDashboardSession } from "@/lib/auth";

function setCookies(values: Record<string, string>) {
  cookieGetMock.mockImplementation((name: string) =>
    name in values ? { name, value: values[name] } : undefined,
  );
}

const unauthorized = () => new MockApiError({ status: 401 });

describe("requireDashboardSession", () => {
  beforeEach(() => {
    fetchApiMock.mockReset();
    redirectMock.mockClear();
    cookieGetMock.mockReset();
  });

  it("redirects to sign-in when there is no session cookie (no API call)", async () => {
    setCookies({});
    await expect(requireDashboardSession()).rejects.toThrow(
      /REDIRECT:\/auth\/sign-in/,
    );
    expect(fetchApiMock).not.toHaveBeenCalled();
  });

  it("returns the user when /user resolves on the mode-selected backend", async () => {
    setCookies({ session: "abc", sb_mode: "demo" });
    const user = { username: "test-gk-owner", v2_prod_access: false };
    fetchApiMock.mockResolvedValueOnce(user);

    await expect(requireDashboardSession()).resolves.toEqual({
      kind: "ok",
      user,
    });
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
  });

  it("demo 401 + prod OK => missing-in-demo (friendly page, no redirect)", async () => {
    setCookies({ session: "abc", sb_mode: "demo" });
    fetchApiMock
      .mockRejectedValueOnce(unauthorized()) // demo backend: no row yet
      .mockResolvedValueOnce({ username: "new-user" }); // prod: valid session

    await expect(requireDashboardSession()).resolves.toEqual({
      kind: "missing-in-demo",
    });
    expect(redirectMock).not.toHaveBeenCalled();
    // The re-check must bypass mode routing (prod is the source of truth).
    expect(fetchApiMock).toHaveBeenNthCalledWith(2, "/user", {
      forceProd: true,
    });
  });

  it("demo 401 + prod 401 => dead session, normal sign-in redirect", async () => {
    setCookies({ session: "abc", sb_mode: "demo" });
    fetchApiMock
      .mockRejectedValueOnce(unauthorized())
      .mockRejectedValueOnce(unauthorized());

    await expect(requireDashboardSession()).rejects.toThrow(
      /REDIRECT:\/auth\/sign-in/,
    );
    expect(fetchApiMock).toHaveBeenCalledTimes(2);
  });

  it("prod-mode 401 redirects without any forceProd re-check", async () => {
    setCookies({ session: "abc", sb_mode: "prod" });
    fetchApiMock.mockRejectedValueOnce(unauthorized());

    await expect(requireDashboardSession()).rejects.toThrow(
      /REDIRECT:\/auth\/sign-in/,
    );
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
  });
});
