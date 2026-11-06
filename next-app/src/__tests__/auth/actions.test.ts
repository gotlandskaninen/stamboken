import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const { cookieSetMock, cookieGetMock, redirectMock, incoming } = vi.hoisted(
  () => ({
    cookieSetMock: vi.fn(),
    cookieGetMock: vi.fn(),
    redirectMock: vi.fn((url: string) => {
      throw new Error(`NEXT_REDIRECT:${url}`);
    }),
    // The request next-app is serving, as nginx forwarded it.
    incoming: { headers: new Headers() },
  }),
);
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    set: cookieSetMock,
    get: cookieGetMock,
    delete: vi.fn(),
    getAll: () => [],
  })),
  headers: vi.fn(async () => incoming.headers),
}));
vi.mock("next/navigation", () => ({ redirect: redirectMock }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchApi: vi.fn() }));

import {
  loginWithGoogle,
  loginWithPassword,
  logout,
} from "@/app/(app)/(auth)/actions";

async function run(action: () => Promise<unknown>): Promise<unknown> {
  try {
    return await action();
  } catch (e) {
    return (e as Error).message;
  }
}

function stubFlask(status: number, body: unknown, setCookie?: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status,
          headers: {
            "content-type": "application/json",
            ...(setCookie ? { "set-cookie": setCookie } : {}),
          },
        }),
    ),
  );
}

describe("loginWithPassword", () => {
  beforeEach(() => {
    cookieSetMock.mockClear();
    redirectMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  // hbuser.username is nullable (register_user defaults it to None, the
  // legacy admin form posts "" when left empty) and Flask authenticates by
  // email, so a correct email+password login returns 200 + session. The action
  // used to read the missing username as a failed login.
  describe.each([null, "", "anna"])("200 with username=%j", (username) => {
    it("accepts the login and sets the session cookie", async () => {
      stubFlask(
        200,
        { id: 7, email: "user@example.test", username, v2_prod_access: false },
        "session=abc123; HttpOnly; Path=/",
      );
      const result = await run(() =>
        loginWithPassword("user@example.test", "correct-pass"),
      );
      expect(result, `action returned ${JSON.stringify(result)}`).toBe(
        "NEXT_REDIRECT:/stamboken/min-besattning",
      );
      expect(cookieSetMock).toHaveBeenCalledWith(
        "session",
        "abc123",
        expect.anything(),
      );
    });
  });

  it("refuses a 401 and sets no cookie", async () => {
    stubFlask(
      401,
      { status: "error", message: "Not authenticated" },
      "session=anon; HttpOnly; Path=/",
    );
    const result = await run(() => loginWithPassword("user", "wrong"));
    expect(result).toEqual({ error: "Felaktigt användarnamn eller lösenord" });
    expect(cookieSetMock).not.toHaveBeenCalled();
  });

  it("refuses a non-2xx answer even if the body carries a user id", async () => {
    stubFlask(
      403,
      { id: 7, email: "user@example.test", username: "anna" },
      "session=anon; HttpOnly; Path=/",
    );
    const result = await run(() => loginWithPassword("user", "wrong"));
    expect(result).toEqual({ error: "Felaktigt användarnamn eller lösenord" });
    expect(cookieSetMock).not.toHaveBeenCalled();
  });

  it("refuses a 200 without a user id (legacy null body)", async () => {
    stubFlask(200, null, "session=anon; HttpOnly; Path=/");
    const result = await run(() => loginWithPassword("user", "wrong"));
    expect(result).toEqual({ error: "Felaktigt användarnamn eller lösenord" });
    expect(cookieSetMock).not.toHaveBeenCalled();
  });
});

// Flask-Limiter keys on the address ProxyFix takes from the last
// X-Forwarded-For entry. next-app's calls used to carry none, so every user
// arrived as the next-app container and shared one bucket per endpoint.
describe("client address reaches Flask", () => {
  const CLIENT_IP = "203.0.113.9";

  function sentHeaders(): Record<string, string> {
    const init = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
    return Object.fromEntries(new Headers(init.headers).entries());
  }

  beforeEach(() => {
    incoming.headers = new Headers({ "x-forwarded-for": CLIENT_IP });
    cookieGetMock.mockReturnValue({ name: "session", value: "s1" });
    stubFlask(401, { status: "error", message: "Not authenticated" });
  });
  afterEach(() => {
    incoming.headers = new Headers();
    cookieGetMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("loginWithPassword forwards the browser address to /api/login", async () => {
    await run(() => loginWithPassword("someone", "wrong"));
    expect(sentHeaders()["x-forwarded-for"]).toBe(CLIENT_IP);
  });

  it("loginWithGoogle forwards the browser address to /api/auth/google", async () => {
    await run(() => loginWithGoogle("credential"));
    expect(sentHeaders()["x-forwarded-for"]).toBe(CLIENT_IP);
  });

  it("logout forwards the browser address to /api/logout", async () => {
    await run(() => logout());
    expect(sentHeaders()["x-forwarded-for"]).toBe(CLIENT_IP);
  });

  it("sends no X-Forwarded-For when the request carried none", async () => {
    incoming.headers = new Headers();
    await run(() => loginWithPassword("someone", "wrong"));
    expect(sentHeaders()["x-forwarded-for"]).toBeUndefined();
  });

  it("loginWithGoogle explains an unlinked workspace account in Swedish", async () => {
    stubFlask(401, { error: "User not found or not authorized" });
    expect(await run(() => loginWithGoogle("credential"))).toEqual({
      error:
        "Ditt föreningskonto är inte kopplat till Stamboken än. Kontakta administratören.",
    });
  });

  describe("429 from the rate limiter", () => {
    const message =
      "För många inloggningsförsök. Vänta en minut och försök igen.";

    it("loginWithPassword says so instead of 'wrong password'", async () => {
      stubFlask(429, { error: "ratelimit exceeded" });
      expect(await run(() => loginWithPassword("someone", "x"))).toEqual({
        error: message,
      });
    });

    it("loginWithGoogle says so instead of a generic failure", async () => {
      stubFlask(429, { error: "ratelimit exceeded" });
      expect(await run(() => loginWithGoogle("credential"))).toEqual({
        error: message,
      });
    });
  });
});
