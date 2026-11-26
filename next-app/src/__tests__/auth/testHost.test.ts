// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  set: vi.fn(),
  incoming: new Headers(),
  prodAccess: true,
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    set: h.set,
    get: () => undefined,
    delete: vi.fn(),
    getAll: () => [],
  }),
  headers: async () => h.incoming,
}));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  },
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn(), refresh: vi.fn() }));
vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(async () => ({ v2_prod_access: h.prodAccess })),
}));

import { loginWithPassword, setMode } from "@/app/(app)/(auth)/actions";

function stubFlask() {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ id: 1, v2_prod_access: true }), {
          headers: {
            "content-type": "application/json",
            "set-cookie": "session=abc; Path=/",
          },
        }),
    ),
  );
}
const modeSet = () => h.set.mock.calls.filter((c) => c[0] === "sb_mode");
const run = (f: () => Promise<unknown>) =>
  f().then(
    () => "",
    (e: Error) => e.message,
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("API_TEST_INTERNAL_URL", "https://example.org/demo");
  h.incoming = new Headers();
  h.prodAccess = true;
  stubFlask();
});

describe("testmiljön sb.gotlandskaninen.se", () => {
  it("login sets demo on the test host even with v2_prod_access", async () => {
    h.incoming = new Headers({
      "x-forwarded-host": "SB.gotlandskaninen.se:443",
    });
    await run(() => loginWithPassword("u", "p"));
    expect(modeSet()[0][1]).toBe("demo");
  });

  it("login on the main host is unchanged", async () => {
    h.incoming = new Headers({ "x-forwarded-host": "gotlandskaninen.se" });
    await run(() => loginWithPassword("u", "p"));
    expect(modeSet()[0][1]).toBe("prod");
  });

  it("falls back to Host when x-forwarded-host is missing", async () => {
    h.incoming = new Headers({ host: "sb.gotlandskaninen.se:3000" });
    await run(() => loginWithPassword("u", "p"));
    expect(modeSet()[0][1]).toBe("demo");
  });

  it("setMode prod on the test host redirects to production, no cookie", async () => {
    h.incoming = new Headers({ "x-forwarded-host": "sb.gotlandskaninen.se" });
    expect(await run(() => setMode("prod"))).toBe(
      "NEXT_REDIRECT:https://gotlandskaninen.se/stamboken",
    );
    expect(h.set).not.toHaveBeenCalled();
  });

  it("setMode demo on the test host and prod on the main host set cookies", async () => {
    h.incoming = new Headers({ "x-forwarded-host": "sb.gotlandskaninen.se" });
    await setMode("demo");
    expect(modeSet()[0][1]).toBe("demo");
    h.set.mockClear();
    h.incoming = new Headers({ host: "gotlandskaninen.se" });
    await setMode("prod");
    expect(modeSet()[0][1]).toBe("prod");
  });
});
