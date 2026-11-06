import { describe, it, expect, vi, beforeEach } from "vitest";

/**
 * safeReturnTo() in (auth)/actions.ts only rejected a leading "//".
 * "/\evil.example/" and "/<TAB>/evil.example" passed, and Next's client
 * (assignLocation -> new URL(location, currentUrl)) resolves them to
 * https://evil.example/ and hard-navigates there after a successful login.
 */

const { redirectMock, cookieSetMock } = vi.hoisted(() => ({
  redirectMock: vi.fn((url: string): never => {
    throw new Error(`REDIRECT:${url}`);
  }),
  cookieSetMock: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({ set: cookieSetMock, get: () => undefined }),
  headers: async () => ({ get: () => null }),
}));
vi.mock("next/navigation", () => ({ redirect: redirectMock }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchApi: vi.fn() }));

import { loginWithGoogle, loginWithPassword } from "@/app/(app)/(auth)/actions";
// The resolver Next's server-action reducer applies to x-action-redirect.
import { assignLocation } from "next/dist/client/assign-location";

const SITE = "https://gotlandskaninen.se";
const FALLBACK = "/stamboken/min-besattning";

const LOGINS = {
  loginWithPassword: (returnTo?: string) =>
    loginWithPassword("u", "p", returnTo),
  loginWithGoogle: (returnTo?: string) =>
    loginWithGoogle("credential", returnTo),
};

async function redirectTargetFor(
  login: (returnTo?: string) => Promise<unknown>,
  returnTo?: string,
): Promise<string> {
  redirectMock.mockClear();
  await expect(login(returnTo)).rejects.toThrow(/^REDIRECT:/);
  return redirectMock.mock.calls[0][0];
}

describe.each(Object.entries(LOGINS))("%s return_to", (_name, login) => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: {
          get: (n: string) =>
            n.toLowerCase() === "set-cookie"
              ? "session=abc; HttpOnly; Path=/"
              : null,
        },
        // loginWithPassword needs res.ok and a user id.
        json: async () => ({ id: 1, username: "u" }),
      })),
    );
  });

  it("keeps a same-site path, with query and hash", async () => {
    expect(await redirectTargetFor(login, "/stamboken/x")).toBe("/stamboken/x");
    expect(await redirectTargetFor(login, "/stamboken/x?y=1#z")).toBe(
      "/stamboken/x?y=1#z",
    );
  });

  it.each([
    undefined,
    "",
    "evil.example/",
    "https://evil.example/",
    "//evil.example/",
    "///evil.example/",
    "////evil.example/",
    "/\\evil.example/",
    "/\\/evil.example/",
    "/\t/evil.example/",
    "/\n/evil.example/",
    "/\r/evil.example/",
    "\\evil.example/",
    " //evil.example/",
  ])("falls back for %j", async (returnTo) => {
    expect(await redirectTargetFor(login, returnTo)).toBe(FALLBACK);
  });

  it("never redirects off-site after login", async () => {
    const offsite: Record<string, string> = {};
    for (const rt of [
      "/\\evil.example/",
      "/\t/evil.example/",
      "/.//evil.example/",
      "/..//evil.example/",
      "/a/..//evil.example/",
      "/%5Cevil.example/",
      "/?\\evil.example",
      "/#//evil.example",
    ]) {
      const target = await redirectTargetFor(login, rt);
      const resolved = assignLocation(target, new URL(`${SITE}/auth/sign-in`));
      if (resolved.origin !== SITE) offsite[JSON.stringify(rt)] = resolved.href;
    }
    expect(offsite, "return_to values that leave the site").toEqual({});
  });
});
