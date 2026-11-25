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
    const { setCookie, render } = await run("session=abc");
    expect(setCookie).toBe("prod");
    expect(render).toContain("sb_mode=prod");
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

  it("still sends a request without a session to sign-in", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const res = await middleware(request(""));
    expect(res.headers.get("location")).toContain("/auth/sign-in");
    expect(fetch).not.toHaveBeenCalled();
  });
});
