// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => ({
  get: (name: string) => ({ name, value: "test-" + name }),
  getAll: () => [{ name: "sb_mode", value: "demo" }],
  set: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("next/headers", () => ({
  cookies: async () => store,
  headers: async () => new Headers(),
}));
vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    throw new Error("redirect " + path);
  },
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
const http = vi.fn<typeof fetch>();
const prod = "https://example.org/prod";

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal("fetch", http);
  vi.stubEnv("API_INTERNAL_URL", prod);
  vi.stubEnv("API_TEST_INTERNAL_URL", "https://example.org/demo");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function flask(data: object, status = 200, cookie?: string) {
  return Response.json(data, {
    status,
    headers: cookie ? { "Set-Cookie": cookie } : {},
  });
}

describe("code login server actions", () => {
  it("only enables the form on an affirmative production status", async () => {
    const { codeLoginEnabled } = await import("@/lib/code-login-enabled");
    http.mockResolvedValueOnce(flask({ enabled: true }));
    expect(await codeLoginEnabled()).toBe(true);
    expect(http).toHaveBeenCalledWith(
      prod + "/api/v2/login/status",
      expect.objectContaining({ cache: "no-store" }),
    );
    http.mockResolvedValueOnce(flask({ enabled: false }));
    expect(await codeLoginEnabled()).toBe(false);
    http.mockRejectedValueOnce(new Error("Unavailable"));
    expect(await codeLoginEnabled()).toBe(false);
  });
  it("keeps the challenge in a short-lived httpOnly cookie, even from demo", async () => {
    const { requestLoginCode } = await import("@/app/(app)/(auth)/actions");
    http.mockResolvedValueOnce(
      flask({ message: "Skickat" }, 200, "login_request=test-request; Path=/"),
    );
    expect(await requestLoginCode("member@example.org")).toBe(true);
    expect(http).toHaveBeenCalledWith(
      prod + "/api/v2/login/kod",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "member@example.org" }),
        headers: expect.objectContaining({
          Cookie: "session=test-session; login_request=test-login_request",
        }),
      }),
    );
    expect(store.set).toHaveBeenCalledWith(
      "login_request",
      "test-request",
      expect.objectContaining({
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 600,
      }),
    );
  });
  it("looks up only in a POST body, without applying any Flask session to the browser", async () => {
    const { lookupLoginLink } = await import("@/app/(app)/(auth)/actions");
    http.mockResolvedValueOnce(
      flask(
        { name: "Testmedlem", switch_from: null },
        200,
        "session=unused; Path=/",
      ),
    );
    expect(await lookupLoginLink("test-token")).toEqual({
      name: "Testmedlem",
      switchFrom: null,
    });
    expect(http).toHaveBeenCalledWith(
      prod + "/api/v2/login/lank/uppslag",
      expect.objectContaining({
        body: JSON.stringify({ token: "test-token" }),
        cache: "no-store",
      }),
    );
    expect(store.set).not.toHaveBeenCalled();
  });
  it("requires a second account-specific POST on conflict and binds pending to prod", async () => {
    const { redeemLoginLink } = await import("@/app/(app)/(auth)/actions");
    http.mockResolvedValueOnce(flask({ switch_from: 12 }, 409));
    expect(await redeemLoginLink("test-token")).toEqual({ switchFrom: 12 });
    expect(store.set).not.toHaveBeenCalled();
    http.mockResolvedValueOnce(
      flask({ pending: true }, 200, "session=test-pending; Path=/"),
    );
    await expect(redeemLoginLink("test-token", 12)).rejects.toThrow(
      "redirect /auth/skapa-konto",
    );
    expect(http).toHaveBeenLastCalledWith(
      prod + "/api/v2/login/lank",
      expect.objectContaining({
        body: JSON.stringify({ token: "test-token", confirm_user_id: 12 }),
      }),
    );
    expect(store.set).toHaveBeenCalledWith(
      "session",
      "test-pending",
      expect.objectContaining({ httpOnly: true }),
    );
    expect(store.set).toHaveBeenCalledWith(
      "sb_mode",
      "prod",
      expect.objectContaining({ httpOnly: false }),
    );
  });
  it("preserves the requested destination for verification and account creation", async () => {
    const { verifyLoginCode, createMemberAccount } = await import(
      "@/app/(app)/(auth)/actions"
    );
    const destination = "/stamboken/inskick/ny";
    http.mockResolvedValueOnce(
      flask({ pending: true }, 200, "session=test-pending; Path=/"),
    );
    await expect(verifyLoginCode("12345678", destination)).rejects.toThrow(
      "redirect /auth/skapa-konto?return_to=" + encodeURIComponent(destination),
    );
    http.mockResolvedValueOnce(
      flask({ v2_prod_access: true }, 200, "session=test-login; Path=/"),
    );
    await expect(createMemberAccount(true, "7", destination)).rejects.toThrow(
      "redirect " + destination,
    );
    expect(http).toHaveBeenLastCalledWith(
      prod + "/api/v2/login/skapa-konto",
      expect.objectContaining({
        body: JSON.stringify({ accepted: true, rules_version: "7" }),
      }),
    );
  });
  it("uses the demo cookie for a nonpromoted account and reports the overnight delay", async () => {
    const { createMemberAccount } = await import("@/app/(app)/(auth)/actions");
    http.mockResolvedValueOnce(
      flask({ v2_prod_access: false }, 200, "session=test-login; Path=/"),
    );
    expect(await createMemberAccount(true, "7")).toEqual({
      demoAccountCreated: true,
    });
    expect(store.set).toHaveBeenCalledWith(
      "sb_mode",
      "demo",
      expect.objectContaining({ httpOnly: false }),
    );
  });
  it("rejects an unchecked agreement and reports a stale version", async () => {
    const { createMemberAccount } = await import("@/app/(app)/(auth)/actions");
    expect(await createMemberAccount(false, "7")).toHaveProperty("error");
    expect(http).not.toHaveBeenCalled();
    http.mockResolvedValueOnce(flask({}, 412));
    expect(await createMemberAccount(true, "7")).toEqual({
      error: "rulesChanged",
    });
    expect(store.set).not.toHaveBeenCalled();
  });
});
