// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";

// #227: a session without a valid sb_mode gets its mode from v2_prod_access in prod.
function request(cookie: string) {
  return new NextRequest("https://localhost/stamboken/min-besattning", {
    headers: { cookie },
  });
}

function prodUser(v2_prod_access: boolean) {
  return vi.fn().mockResolvedValue(Response.json({ id: 1, v2_prod_access }));
}

// The cookie the browser gets, and the one this request's render reads.
async function run(cookie: string) {
  const res = await middleware(request(cookie));
  return {
    setCookie: res.cookies.get("sb_mode")?.value,
    render: res.headers.get("x-middleware-request-cookie"),
    cookie: res.cookies.get("sb_mode"),
    retry: res.cookies.get("sb_mode_retry"),
  };
}

describe("middleware sb_mode resolution", () => {
  beforeEach(() => {
    vi.stubEnv("API_TEST_INTERNAL_URL", "http://api-test:9090");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("session, no sb_mode, prod access: prod, and the cookie is set", async () => {
    const fetch = prodUser(true);
    vi.stubGlobal("fetch", fetch);
    const { setCookie, render, cookie } = await run("session=abc");
    expect(setCookie).toBe("prod");
    expect(render).toContain("sb_mode=prod");
    // Readable by the browser, site-wide, as long as the Flask session.
    expect(cookie).toMatchObject({
      httpOnly: false,
      path: "/",
      maxAge: 31 * 24 * 60 * 60,
    });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/user$/);
    expect(init.headers.Cookie).toBe("session=abc");
  });

  it("session, no sb_mode, no prod access: demo", async () => {
    vi.stubGlobal("fetch", prodUser(false));
    const { setCookie, render } = await run("session=abc");
    expect(setCookie).toBe("demo");
    expect(render).toContain("sb_mode=demo");
  });

  it("no test API configured: prod without asking Flask", async () => {
    vi.stubEnv("API_TEST_INTERNAL_URL", "");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { setCookie, retry } = await run("session=abc");
    expect(setCookie).toBe("prod");
    expect(retry).toBeUndefined();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("an invalid sb_mode is resolved like a missing one", async () => {
    vi.stubGlobal("fetch", prodUser(true));
    expect((await run("session=abc; sb_mode=PROD")).setCookie).toBe("prod");
  });

  it.each(["demo", "prod"])(
    "a valid sb_mode=%s costs no API call",
    async (mode) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const { setCookie, render } = await run(`session=abc; sb_mode=${mode}`);
      expect(fetch).not.toHaveBeenCalled();
      expect(setCookie).toBeUndefined();
      expect(render).toBeNull();
    },
  );

  it("sets nothing when prod cannot read the user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    );
    expect((await run("session=abc")).setCookie).toBeUndefined();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect((await run("session=abc")).setCookie).toBeUndefined();
  });

  // A failed lookup sets a short marker; with it, the next request does not ask again.
  it.each([
    [
      "429",
      () => vi.fn().mockResolvedValue(new Response(null, { status: 429 })),
    ],
    [
      "a timeout",
      () =>
        vi.fn(
          (_url: string, init: RequestInit) =>
            new Promise<Response>((_resolve, reject) =>
              init.signal!.addEventListener("abort", () =>
                reject(init.signal!.reason),
              ),
            ),
        ),
    ],
  ])("after %s, no lookup while the marker is set", async (_name, make) => {
    const fetch = make();
    vi.stubGlobal("fetch", fetch);
    const first = await run("session=abc");
    expect(first.setCookie).toBeUndefined();
    expect(first.retry).toMatchObject({
      value: "1",
      httpOnly: true,
      maxAge: 120,
    });
    const second = await run("session=abc; sb_mode_retry=1");
    expect(second.setCookie).toBeUndefined();
    expect(second.retry).toBeUndefined();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("still sends a request without a session to sign-in", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const res = await middleware(request(""));
    expect(res.headers.get("location")).toContain("/auth/sign-in");
    expect(fetch).not.toHaveBeenCalled();
  });
});
