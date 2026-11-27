import { afterEach, expect, it, vi } from "vitest";
import { emptyState, toBody } from "./lib";

vi.mock("next/headers", () => {
  const all = [
    { name: "sb_mode", value: "demo" },
    { name: "session", value: "test" },
  ];
  return {
    cookies: async () => ({
      get: (name: string) => all.find((cookie) => cookie.name === name),
      getAll: () => all,
    }),
    headers: async () => new Headers(),
  };
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("blocks a late demo sale when the demo upstream is missing", async () => {
  vi.resetModules();
  vi.stubEnv("API_INTERNAL_URL", "https://prod.example.org");
  vi.stubEnv("API_TEST_INTERNAL_URL", "");
  const send = vi.fn();
  vi.stubGlobal("fetch", send);
  const { dryRun, submitReport } = await import("./actions");
  const body = toBody(
    emptyState(),
    "00000000-0000-4000-8000-000000000001",
    null,
  );
  body.health = "inga";
  body.reason = "Sent inskick";
  body.rabbits["1"] = {
    val: "sald",
    sald: {
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 1,
      kopare: {
        name: "Testköpare",
        town: "Testort",
        postal_address: "Testgatan 1",
        email: "buyer@example.org",
        notice_only: true,
      },
    },
  };

  for (const action of [dryRun, submitReport]) {
    expect(await action("G9001", 2025, body, "demo")).toMatchObject({
      ok: false,
      problem: { status: 503 },
    });
  }
  expect(send).not.toHaveBeenCalled();
});
