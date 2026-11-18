import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// The sb_mode cookie value returned by the mocked cookies() store. Reconfigured
// per test. Hoisted so the vi.mock factory below can reference it safely.
const { cookieGetMock, incoming } = vi.hoisted(() => ({
  cookieGetMock: vi.fn(),
  // The request next-app is serving, as nginx forwarded it.
  incoming: { headers: new Headers() },
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    getAll: () => [],
    get: cookieGetMock,
  })),
  headers: vi.fn(async () => incoming.headers),
}));

const PROD_HOST = "http://api:9090";
const TEST_HOST = "http://api-test:9090";

/**
 * Import a FRESH copy of lib/api after setting env vars, mock the sb_mode
 * cookie (and, unless `session` is false, a signed-in `session` cookie), call
 * fetchApi(), and return the URL the mocked global fetch was called with.
 * lib/api computes its base-URL consts at module-eval time, so it MUST be
 * re-imported (vi.resetModules) after each env change.
 */
async function fetchedUrlFor(
  mode: string | undefined,
  { session = true, forceProd = false } = {},
): Promise<string> {
  cookieGetMock.mockImplementation((name: string) => {
    if (name === "sb_mode" && mode !== undefined) return { name, value: mode };
    if (name === "session" && session) return { name, value: "flask-session" };
    return undefined;
  });
  const { fetchApi } = await import("@/lib/api");
  await fetchApi("/user", { forceProd });
  const fetchMock = vi.mocked(globalThis.fetch);
  return String(fetchMock.mock.calls[0][0]);
}

describe("fetchApi mode-aware base URL selection", () => {
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...ORIGINAL_ENV, API_INTERNAL_URL: PROD_HOST };
    delete process.env.API_TEST_INTERNAL_URL;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("mode=prod -> prod host (API_INTERNAL_URL)", async () => {
    const url = await fetchedUrlFor("prod");
    expect(url).toBe(`${PROD_HOST}/api/user`);
  });

  it("mode=demo + API_TEST_INTERNAL_URL set -> api-test host", async () => {
    process.env.API_TEST_INTERNAL_URL = TEST_HOST;
    const url = await fetchedUrlFor("demo");
    expect(url).toBe(`${TEST_HOST}/api/user`);
  });

  it("mode=demo + API_TEST_INTERNAL_URL UNSET (base dev) -> prod host fallback", async () => {
    // API_TEST_INTERNAL_URL deleted in beforeEach.
    const url = await fetchedUrlFor("demo");
    expect(url).toBe(`${PROD_HOST}/api/user`);
  });

  it("prod mode never routes to api-test even when a test URL is configured", async () => {
    process.env.API_TEST_INTERNAL_URL = TEST_HOST;
    const url = await fetchedUrlFor("prod");
    expect(url).toBe(`${PROD_HOST}/api/user`);
  });

  // parseMode(undefined) is "demo", so every anonymous visitor read as
  // demo and /ansok applications were written to the nightly-wiped demo db.
  describe("anonymous requests (no session cookie) go to prod", () => {
    beforeEach(() => {
      process.env.API_TEST_INTERNAL_URL = TEST_HOST;
    });

    it("no sb_mode and no session -> prod", async () => {
      const url = await fetchedUrlFor(undefined, { session: false });
      expect(url).toBe(`${PROD_HOST}/api/user`);
    });

    it("stale sb_mode=demo but no session -> prod", async () => {
      const url = await fetchedUrlFor("demo", { session: false });
      expect(url).toBe(`${PROD_HOST}/api/user`);
    });

    it("empty session cookie value counts as anonymous -> prod", async () => {
      cookieGetMock.mockImplementation((name: string) =>
        name === "sb_mode"
          ? { name, value: "demo" }
          : name === "session"
            ? { name, value: "" }
            : undefined,
      );
      const { fetchApi } = await import("@/lib/api");
      await fetchApi("/user");
      const url = String(vi.mocked(globalThis.fetch).mock.calls[0][0]);
      expect(url).toBe(`${PROD_HOST}/api/user`);
    });

    it("session but no sb_mode cookie -> api-test (unchanged: absent mode reads as demo)", async () => {
      const url = await fetchedUrlFor(undefined);
      expect(url).toBe(`${TEST_HOST}/api/user`);
    });

    it("sb_mode=demo + session -> api-test (signed-in demo routing unchanged)", async () => {
      const url = await fetchedUrlFor("demo");
      expect(url).toBe(`${TEST_HOST}/api/user`);
    });

    it("forceProd beats sb_mode=demo + session", async () => {
      const url = await fetchedUrlFor("demo", { forceProd: true });
      expect(url).toBe(`${PROD_HOST}/api/user`);
    });
  });
});

describe("fetchApi problem-details normalisation", () => {
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...ORIGINAL_ENV, API_INTERNAL_URL: PROD_HOST };
    delete process.env.API_TEST_INTERNAL_URL;
    cookieGetMock.mockImplementation((name: string) =>
      name === "sb_mode" ? { name, value: "prod" } : undefined,
    );
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  /** Make fetchApi fail on `body`/`status` and hand back the thrown ApiError. */
  async function errorFor(body: unknown, status: number) {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(body), {
            status,
            statusText: "Conflict",
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    const { fetchApi } = await import("@/lib/api");
    return await fetchApi("/v2/persons/9/link-user").then(
      () => {
        throw new Error("expected fetchApi to reject");
      },
      (err) => err,
    );
  }

  it("keeps the RFC 9457 type and the extension members", async () => {
    const conveysHerds = [{ id: 1, herd: "G1", herd_name: null }];
    const err = await errorFor(
      {
        type: "confirm-required",
        title: "T",
        status: 409,
        detail: "D",
        instance: "/api/v2/persons/3/link-user",
        conveys_herds: conveysHerds,
      },
      409,
    );
    expect(err.status).toBe(409);
    expect(err.title).toBe("T");
    expect(err.detail).toBe("D");
    expect(err.type).toBe("confirm-required");
    expect(err.extensions.conveys_herds).toEqual(conveysHerds);
    // Extensions are the body minus RFC 9457's standard members — `instance`
    // is one of them and must not surface as an extension.
    expect(err.extensions.instance).toBeUndefined();
    expect(err.extensions).toEqual({ conveys_herds: conveysHerds });
  });

  it("defaults a legacy {status,message} body to about:blank with no extensions", async () => {
    const err = await errorFor({ status: "error", message: "x" }, 400);
    expect(err.type).toBe("about:blank");
    expect(err.extensions).toEqual({});
    expect(err.detail).toBe("x");
  });
});

// Flask-Limiter keys on the address ProxyFix takes from the last
// X-Forwarded-For entry. fetchApi sent only Cookie and Content-Type, so every
// user arrived as the next-app container and shared one bucket per endpoint.
describe("fetchApi client address", () => {
  const ORIGINAL_ENV = { ...process.env };
  const CLIENT_IP = "203.0.113.9";

  async function sentHeaders(): Promise<Record<string, string>> {
    const { fetchApi } = await import("@/lib/api");
    await fetchApi("/user");
    const init = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
    return Object.fromEntries(new Headers(init.headers).entries());
  }

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...ORIGINAL_ENV, API_INTERNAL_URL: PROD_HOST };
    delete process.env.API_TEST_INTERNAL_URL;
    cookieGetMock.mockImplementation((name: string) =>
      name === "sb_mode" ? { name, value: "prod" } : undefined,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({}), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    incoming.headers = new Headers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  // Flask keys on the entry nginx appended, so only the last one goes on.
  it.each([
    ["a forged first entry", `198.51.100.1, ${CLIENT_IP}`, CLIENT_IP],
    // Werkzeug reads this whole string as ONE entry, so a client could pick
    // its own limiter key by changing the nonce.
    ["an unterminated quote", `"nonce1, ${CLIENT_IP}`, CLIENT_IP],
    ["an IPv6 address", "198.51.100.1, 2001:db8::9", "2001:db8::9"],
  ])("forwards only the last entry: %s", async (_name, header, expected) => {
    incoming.headers = new Headers({ "x-forwarded-for": header });
    expect((await sentHeaders())["x-forwarded-for"]).toBe(expected);
  });

  it("ignores a last entry that is not an IP address and uses X-Real-IP", async () => {
    incoming.headers = new Headers({
      "x-forwarded-for": `${CLIENT_IP}, unknown`,
      "x-real-ip": "198.51.100.7",
    });
    expect((await sentHeaders())["x-forwarded-for"]).toBe("198.51.100.7");
  });

  it.each([
    ["a port", `${CLIENT_IP}:4711`],
    ["a bracketed IPv6 address", "[2001:db8::9]"],
    ["a hostname", "unknown"],
  ])("sends nothing when the last entry is %s", async (_name, header) => {
    incoming.headers = new Headers({
      "x-forwarded-for": `198.51.100.1, ${header}`,
    });
    expect((await sentHeaders())["x-forwarded-for"]).toBeUndefined();
  });

  it("falls back to X-Real-IP", async () => {
    incoming.headers = new Headers({ "x-real-ip": CLIENT_IP });
    expect((await sentHeaders())["x-forwarded-for"]).toBe(CLIENT_IP);
  });

  it("sends no X-Forwarded-For when the request carried none", async () => {
    expect((await sentHeaders())["x-forwarded-for"]).toBeUndefined();
  });
});

describe("fetchApi HEAD", () => {
  it("resolves on a 200 without a body, and throws ApiError on 404", async () => {
    vi.resetModules();
    cookieGetMock.mockReturnValue(undefined);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const { fetchApi } = await import("@/lib/api");
    await expect(fetchApi("/x", { method: "HEAD" })).resolves.toBeUndefined();
    await expect(fetchApi("/x", { method: "HEAD" })).rejects.toMatchObject({
      status: 404,
    });
  });
});
