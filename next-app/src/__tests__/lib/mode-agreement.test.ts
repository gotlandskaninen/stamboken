/**
 * Pitfall 1 regression guard: the two INDEPENDENT fetch paths must agree.
 *
 * `/stamboken/alla-kaniner` renders using BOTH the server-side `fetchApi()`
 * (RSC/Server Actions) and the browser-side RTK Query `modeAwareBaseQuery` on a
 * single page. If only one path is mode-aware — or only one has the base-dev
 * fallback — the page shows demo data on first paint and prod after the first
 * interaction (or vice versa). This test exercises BOTH real selection functions
 * with the SAME sb_mode value and asserts they resolve to the same backend side
 * in BOTH the test-URL-configured and base-dev (no test URL) deployments.
 *
 * It fails if a future change makes one path mode-aware but forgets the other,
 * or removes the base-dev fallback from just one side.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MODE_COOKIE, parseMode, readModeCookieClient } from "@/lib/mode";

const PROD_HOST = "http://api:9090";
const TEST_HOST = "http://api-test:9090";

// Server-path harness: lib/api.ts reads the sb_mode via next/headers cookies().
const { cookieGetMock } = vi.hoisted(() => ({ cookieGetMock: vi.fn() }));
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    getAll: () => [],
    get: cookieGetMock,
  })),
  headers: vi.fn(async () => new Headers()),
}));

const ORIGINAL_ENV = { ...process.env };

function jsonResponse() {
  return new Response(JSON.stringify({}), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function clearModeCookie() {
  document.cookie = `${MODE_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

/**
 * Which backend the SERVER path (fetchApi) selects for a signed-in user in a
 * mode + deployment. (Anonymous visitors diverge on purpose: the server path
 * sends them to prod, the browser path cannot see the httpOnly session cookie.)
 */
async function serverSide(
  mode: string,
  testUrlConfigured: boolean,
): Promise<"test" | "prod"> {
  vi.resetModules();
  process.env = { ...ORIGINAL_ENV, API_INTERNAL_URL: PROD_HOST };
  if (testUrlConfigured) process.env.API_TEST_INTERNAL_URL = TEST_HOST;
  else delete process.env.API_TEST_INTERNAL_URL;

  // Signed in: the server path only honours sb_mode=demo together with a
  // session cookie (anonymous requests always go to prod).
  cookieGetMock.mockImplementation((name: string) => {
    if (name === "sb_mode") return { name, value: mode };
    if (name === "session") return { name, value: "flask-session" };
    return undefined;
  });
  const fetchMock = vi.fn((..._args: unknown[]) => jsonResponse());
  vi.stubGlobal("fetch", fetchMock);

  const { fetchApi } = await import("@/lib/api");
  await fetchApi("/user");
  const url = String(fetchMock.mock.calls[0][0]);

  vi.unstubAllGlobals();
  return url.startsWith(TEST_HOST) ? "test" : "prod";
}

/** Which backend the BROWSER path (modeAwareBaseQuery) selects. */
async function browserSide(
  mode: string,
  testUrlConfigured: boolean,
): Promise<"test" | "prod"> {
  vi.resetModules();
  process.env = { ...ORIGINAL_ENV };
  if (testUrlConfigured) process.env.NEXT_PUBLIC_API_TEST_URL = "/api-test";
  else delete process.env.NEXT_PUBLIC_API_TEST_URL;

  clearModeCookie();
  document.cookie = `${MODE_COOKIE}=${mode}`;
  const fetchMock = vi.fn((..._args: unknown[]) => jsonResponse());
  vi.stubGlobal("fetch", fetchMock);
  // Dodge the jsdom/undici AbortSignal realm mismatch (fetchBaseQuery timeout).
  class CapturingRequest {
    url: string;
    constructor(input: string | { url: string }) {
      this.url = typeof input === "string" ? input : input.url;
    }
  }
  vi.stubGlobal("Request", CapturingRequest);

  const { modeAwareBaseQuery } = await import("@/redux/api/apiSlice");
  const api = {
    signal: new AbortController().signal,
    abort: () => {},
    dispatch: () => {},
    getState: () => ({}),
    extra: undefined,
    endpoint: "test",
    type: "query" as const,
    forced: false,
  };
  await modeAwareBaseQuery("/user", api as never, {});
  const arg = fetchMock.mock.calls[0][0];
  const url = typeof arg === "string" ? arg : (arg as { url: string }).url;
  const pathname = new URL(url, "http://localhost").pathname;

  vi.unstubAllGlobals();
  clearModeCookie();
  return pathname.startsWith("/api-test") ? "test" : "prod";
}

describe("mode routing agreement (Pitfall 1 guard)", () => {
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    clearModeCookie();
  });

  it("both paths derive the same Mode from the same cookie value (shared allow-list)", () => {
    for (const value of ["demo", "prod", "PROD", "garbage", ""]) {
      clearModeCookie();
      document.cookie = `${MODE_COOKIE}=${value}`;
      expect(readModeCookieClient()).toBe(parseMode(value));
    }
    // absent cookie
    clearModeCookie();
    expect(readModeCookieClient()).toBe(parseMode(undefined));
  });

  describe("test URL configured", () => {
    it("demo -> BOTH paths pick the api-test backend", async () => {
      expect(await serverSide("demo", true)).toBe("test");
      expect(await browserSide("demo", true)).toBe("test");
    });

    it("prod -> BOTH paths pick the prod backend", async () => {
      expect(await serverSide("prod", true)).toBe("prod");
      expect(await browserSide("prod", true)).toBe("prod");
    });
  });

  describe("no test URL (base dev)", () => {
    it("demo -> BOTH paths fall back to prod (never a non-existent api-test)", async () => {
      expect(await serverSide("demo", false)).toBe("prod");
      expect(await browserSide("demo", false)).toBe("prod");
    });

    it("prod -> BOTH paths stay on prod", async () => {
      expect(await serverSide("prod", false)).toBe("prod");
      expect(await browserSide("prod", false)).toBe("prod");
    });
  });

  it("server and browser resolve to the SAME side for every mode/deployment combo", async () => {
    for (const mode of ["demo", "prod"]) {
      for (const testUrlConfigured of [true, false]) {
        const server = await serverSide(mode, testUrlConfigured);
        const browser = await browserSide(mode, testUrlConfigured);
        expect(server, `mode=${mode} testUrl=${testUrlConfigured}`).toBe(
          browser,
        );
      }
    }
  });
});
