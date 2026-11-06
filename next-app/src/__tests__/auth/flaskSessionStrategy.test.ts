// @vitest-environment node
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  addDataAndFileToRequest,
  type AuthStrategyFunctionArgs,
} from "payload";
import { flaskSessionStrategy } from "@/auth/flaskSessionStrategy";

const CMS_ADMIN = "cms-admin@gotlandskaninen.se";
const ADMIN_ROW = { id: 1, email: CMS_ADMIN, role: "admin" };

/** Run the strategy against a mocked GET /api/user body and allowlist. */
async function authenticateWith(apiUser: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(apiUser), { status: 200 })),
  );
  const find = vi.fn(
    async ({ where }: { where: { email: { equals: string } } }) => ({
      docs: where.email.equals === CMS_ADMIN ? [ADMIN_ROW] : [],
    }),
  );
  const result = await flaskSessionStrategy.authenticate({
    headers: new Headers({ cookie: "session=abc" }),
    payload: { find },
  } as never);
  return { user: result.user, find };
}

afterEach(() => vi.unstubAllGlobals());

describe("flaskSessionStrategy", () => {
  it("does not make an owner CMS admin by a self-set User.email", async () => {
    // GET /api/user after the owner PATCHed /api/manage/user/ to the
    // allowlisted address.
    const { user } = await authenticateWith({
      id: 4,
      email: CMS_ADMIN,
      google_email: null,
      validated: false,
    });
    expect(user, `owner resolved as ${JSON.stringify(user)}`).toBeNull();
  });

  it("resolves a validated user by the Google-verified google_email", async () => {
    const { user, find } = await authenticateWith({
      id: 1,
      email: "jonas.privat@example.se",
      google_email: "CMS-Admin@gotlandskaninen.se",
      validated: true,
    });
    expect(find.mock.calls[0]?.[0].where).toEqual({
      email: { equals: CMS_ADMIN },
    });
    expect(user).toMatchObject({ id: 1, role: "admin", collection: "users" });
  });
});

// Payload's session check calls Flask's /api/user for every /admin and
// /cms-api request. It sent only the Cookie, so Flask rate-limited all editors
// as one address.
describe("flaskSessionStrategy client address", () => {
  const CLIENT_IP = "203.0.113.9";
  const payload = {
    find: vi.fn(async () => ({
      docs: [{ id: 1, email: "editor@gotlandskaninen.se", role: "editor" }],
    })),
  };

  async function authenticate(incoming: Record<string, string>) {
    return flaskSessionStrategy.authenticate({
      headers: new Headers({ cookie: "session=abc", ...incoming }),
      payload,
    } as unknown as AuthStrategyFunctionArgs);
  }

  function sentHeaders(): Record<string, string> {
    const init = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
    return Object.fromEntries(new Headers(init.headers).entries());
  }

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              email: "editor@gotlandskaninen.se",
              google_email: "editor@gotlandskaninen.se",
              validated: true,
            }),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          ),
      ),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("forwards the browser address together with the session cookie", async () => {
    const result = await authenticate({ "x-forwarded-for": CLIENT_IP });
    expect(result.user).toMatchObject({ id: 1 });
    const sent = sentHeaders();
    expect(sent["x-forwarded-for"]).toBe(CLIENT_IP);
    expect(sent.cookie).toBe("session=abc");
  });

  it("sends no X-Forwarded-For when the request carried none", async () => {
    await authenticate({});
    expect(sentHeaders()["x-forwarded-for"]).toBeUndefined();
  });
});

/**
 * The Payload flask-session strategy must not accept the Flask `session`
 * cookie on requests another site triggered. A cross-site HTML form (multipart,
 * `_payload` JSON, no CORS preflight) reaches Users.create as the victim admin
 * otherwise: Payload's own Origin check lives only in extractJWT for its
 * `<prefix>-token` cookie, and nothing in nginx/middleware checks Origin on
 * /cms-api.
 */
const R021_ADMIN_ROW = {
  id: 1,
  email: "cms-admin@gotlandskaninen.se",
  role: "admin",
};
const HOST = "gotlandskaninen.se";
const SITE = `https://${HOST}`;

/** Run the strategy for a request carrying the victim's session cookie. */
async function authenticateCrossSite(headers: Record<string, string>) {
  const fetchMock = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          email: R021_ADMIN_ROW.email,
          google_email: R021_ADMIN_ROW.email,
          validated: true,
        }),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const payload = { find: vi.fn(async () => ({ docs: [R021_ADMIN_ROW] })) };
  const result = await flaskSessionStrategy.authenticate({
    headers: new Headers({
      cookie: "session=victim-admin-session",
      ...headers,
    }),
    payload,
    isGraphQL: false,
    canSetHeaders: false,
    strategyName: "flask-session",
  } as never);
  return { user: result.user, fetchMock };
}

describe("flaskSessionStrategy cross-site", () => {
  it("does not authenticate a cross-site form POST with the victim's session cookie", async () => {
    // What an attacker page's <form enctype="multipart/form-data"> sends to
    // https://gotlandskaninen.se/cms-api/users in the victim admin's browser.
    const form = new FormData();
    form.append(
      "_payload",
      JSON.stringify({ email: "eve@example.org", role: "admin" }),
    );
    const req = new Request(`${SITE}/cms-api/users`, {
      method: "POST",
      body: form,
      headers: {
        cookie: "session=victim-admin-session",
        origin: "https://hostile.invalid",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "navigate",
      },
    }) as Request & { payload?: unknown; data?: unknown };

    // sanity: Payload's real body parser turns the form into Users.create data
    req.payload = { config: {}, logger: console };
    await addDataAndFileToRequest(req as never);
    expect(req.data).toEqual({ email: "eve@example.org", role: "admin" });

    // Host is what nginx forwards; without it the strategy would fail closed
    // for the wrong reason.
    const { user } = await authenticateCrossSite({
      host: HOST,
      ...Object.fromEntries(req.headers),
    });

    expect(
      user,
      `cross-site request (Origin ${req.headers.get("origin")}, Sec-Fetch-Site ` +
        `${req.headers.get("sec-fetch-site")}) authenticated as ${JSON.stringify(user)}`,
    ).toBeNull();
  });

  it.each([
    ["another site", "https://hostile.invalid"],
    [
      "a sibling subdomain (legacy host)",
      "https://stamboken.gotlandskaninen.se",
    ],
    ["a look-alike suffix", `${SITE}.hostile.invalid`],
    ["the opaque origin", "null"],
    ["an unparsable origin", "not a url"],
  ])(
    "refuses a request with Origin from %s before asking Flask",
    async (_n, origin) => {
      const { user, fetchMock } = await authenticateCrossSite({
        host: HOST,
        origin,
      });
      expect(user).toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("fails closed for an Origin when the proxy forwards no Host", async () => {
    const { user } = await authenticateCrossSite({ origin: SITE });
    expect(user).toBeNull();
  });

  it("refuses a cross-site subresource load that carries no Origin", async () => {
    const { user } = await authenticateCrossSite({
      host: HOST,
      "sec-fetch-site": "cross-site",
      "sec-fetch-mode": "no-cors",
    });
    expect(user).toBeNull();
  });

  it.each([
    [
      "a same-origin POST",
      { host: HOST, origin: SITE, "sec-fetch-site": "same-origin" },
    ],
    ["a same-origin GET", { host: HOST, "sec-fetch-site": "same-origin" }],
    [
      "a link followed from another site (top-level navigation)",
      {
        host: HOST,
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "navigate",
      },
    ],
    ["a non-browser GET with no fetch metadata", { host: HOST }],
  ])("still authenticates %s", async (_n, headers) => {
    const { user } = await authenticateCrossSite(headers);
    expect(user).toMatchObject({
      email: R021_ADMIN_ROW.email,
      collection: "users",
    });
  });
});
