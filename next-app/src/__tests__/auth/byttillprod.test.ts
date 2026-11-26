// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  set: vi.fn(),
  incoming: new Headers(),
  user: { v2_prod_access: true } as { v2_prod_access?: boolean } | Error,
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({ set: h.set }),
  headers: async () => h.incoming,
}));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  },
}));
vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(async () => {
    if (h.user instanceof Error) throw h.user;
    return h.user;
  }),
}));

import { GET } from "@/app/(app)/stamboken/byt-till-prod/route";

const run = (f: () => Promise<unknown>) =>
  f().then(
    () => "",
    (e: Error) => e.message,
  );

beforeEach(() => {
  vi.clearAllMocks();
  h.incoming = new Headers({ host: "gotlandskaninen.se" });
  h.user = { v2_prod_access: true };
});

describe("/stamboken/byt-till-prod", () => {
  it("sets prod for a promoted user on the main host", async () => {
    expect(await run(GET)).toBe("NEXT_REDIRECT:/stamboken");
    expect(h.set).toHaveBeenCalledWith("sb_mode", "prod", expect.anything());
  });
  it("sets nothing for a non-promoted user or an API error", async () => {
    h.user = { v2_prod_access: false };
    await run(GET);
    h.user = new Error("down");
    expect(await run(GET)).toBe("NEXT_REDIRECT:/stamboken");
    expect(h.set).not.toHaveBeenCalled();
  });
  it("forwards to the production route from the test host", async () => {
    h.incoming = new Headers({ host: "sb.gotlandskaninen.se" });
    expect(await run(GET)).toBe(
      "NEXT_REDIRECT:https://gotlandskaninen.se/stamboken/byt-till-prod",
    );
    expect(h.set).not.toHaveBeenCalled();
  });
});
