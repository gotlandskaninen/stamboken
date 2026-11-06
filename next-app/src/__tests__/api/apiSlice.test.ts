import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  apiSlice,
  useLoginMutation,
  useGoogleLoginMutation,
  useFetchUserQuery,
  useLogoutMutation,
  useFetchActiveUsersQuery,
  useFetchPopulationMetricsQuery,
  useFetchFounderStatisticsQuery,
  useFetchGeneticPrioritiesQuery,
  useFetchBreedingSuggestionsQuery,
} from "@/redux/api/apiSlice";
import { MODE_COOKIE } from "@/lib/mode";

describe("apiSlice", () => {
  it("exports all expected hooks", () => {
    expect(useLoginMutation).toBeDefined();
    expect(useGoogleLoginMutation).toBeDefined();
    expect(useFetchUserQuery).toBeDefined();
    expect(useLogoutMutation).toBeDefined();
    expect(useFetchActiveUsersQuery).toBeDefined();
  });

  it("exports genetics hooks", () => {
    expect(useFetchPopulationMetricsQuery).toBeDefined();
    expect(useFetchFounderStatisticsQuery).toBeDefined();
    expect(useFetchGeneticPrioritiesQuery).toBeDefined();
    expect(useFetchBreedingSuggestionsQuery).toBeDefined();
  });

  it("has correct reducer path", () => {
    expect(apiSlice.reducerPath).toBe("api");
  });

  it("defines expected tag types", () => {
    const state = apiSlice.reducer(undefined, { type: "@@INIT" });
    expect(state).toBeDefined();
  });

  it("has endpoints for all expected operations", () => {
    const endpointNames = Object.keys(apiSlice.endpoints);
    expect(endpointNames).toContain("login");
    expect(endpointNames).toContain("googleLogin");
    expect(endpointNames).toContain("fetchUser");
    expect(endpointNames).toContain("logout");
    expect(endpointNames).toContain("fetchHerd");
    expect(endpointNames).toContain("fetchActiveUsers");
  });

  it("has genetics endpoints", () => {
    const endpointNames = Object.keys(apiSlice.endpoints);
    expect(endpointNames).toContain("fetchPopulationMetrics");
    expect(endpointNames).toContain("fetchFounderStatistics");
    expect(endpointNames).toContain("fetchGeneticPriorities");
    expect(endpointNames).toContain("fetchBreedingSuggestions");
  });

  // fetchHerd and fetchBreedingList endpoints still defined but hooks
  // no longer exported — min-besattning uses server-fetched props (Story 2.11)
});

describe("mode-aware baseQuery", () => {
  const ORIGINAL_ENV = { ...process.env };
  const clearModeCookie = () => {
    document.cookie = `${MODE_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  };
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...ORIGINAL_ENV };
    delete process.env.NEXT_PUBLIC_API_TEST_URL;
    clearModeCookie();
    // fetchBaseQuery's defaultFetchFn calls global fetch lazily; stub it so we
    // can capture which baseUrl the selected base query resolved to.
    fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    // fetchBaseQuery's timeout option builds a `new AbortController()` from the
    // jsdom global, whose signal undici's real `Request` rejects. Stub `Request`
    // with a minimal URL-capturing class so we can read the delegated baseUrl
    // without undici's signal validation.
    class CapturingRequest {
      url: string;
      constructor(input: string | { url: string }) {
        this.url = typeof input === "string" ? input : input.url;
      }
    }
    vi.stubGlobal("Request", CapturingRequest);
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    vi.unstubAllGlobals();
    clearModeCookie();
    vi.clearAllMocks();
  });

  // Fresh-import modeAwareBaseQuery (module reads NEXT_PUBLIC_API_TEST_URL at
  // eval time), drive it with a sb_mode cookie, and return the /api vs /api-test
  // pathname of the request it delegated to.
  async function selectedPath(mode: string): Promise<string> {
    document.cookie = `${MODE_COOKIE}=${mode}`;
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
    const url = typeof arg === "string" ? arg : (arg as Request).url;
    return new URL(url, "http://localhost").pathname;
  }

  it("demo + NEXT_PUBLIC_API_TEST_URL set -> /api-test", async () => {
    process.env.NEXT_PUBLIC_API_TEST_URL = "/api-test";
    expect(await selectedPath("demo")).toBe("/api-test/user");
  });

  it("demo + no test URL (base dev) -> /api fallback", async () => {
    // NEXT_PUBLIC_API_TEST_URL deleted in beforeEach.
    expect(await selectedPath("demo")).toBe("/api/user");
  });

  it("prod -> /api", async () => {
    process.env.NEXT_PUBLIC_API_TEST_URL = "/api-test";
    // even with a test URL configured, prod mode stays on /api
    expect(await selectedPath("prod")).toBe("/api/user");
  });
});
