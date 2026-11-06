/**
 * The public flows (/ansok, /stamboken/verifiera) must read and write the
 * PROD backend. fetchApi chose the backend from sb_mode, and parseMode(undefined)
 * is "demo", so an anonymous visitor was routed to API_TEST_INTERNAL_URL
 * (api-test -> herdbook_demo, wiped nightly): applications were lost and
 * certificates issued in prod showed as "not found".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const { cookieGetMock } = vi.hoisted(() => ({ cookieGetMock: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    getAll: () => [],
    get: cookieGetMock,
  })),
  // fetchApi forwards the client address.
  headers: vi.fn(async () => new Headers()),
}));

const PROD_HOST = "http://api:9090";
const TEST_HOST = "http://api-test:9090";

const VERIFIED = {
  verified: true,
  certificate_type: "pedigree",
  individual_name: "Test",
  individual_number: "G1",
  genebank: "Gotlandskanin",
  digital_certificate: 1,
  issued_by: "x",
  issued_at: "2026-01-01T00:00:00",
  is_current: true,
  replaced_by_date: null,
};

// Who is calling: an anonymous visitor, a visitor with a stale sb_mode=demo
// cookie but no session, or a signed-in user in demo mode.
const CALLERS: Record<string, Record<string, string>> = {
  "anonymous (no cookies)": {},
  "anonymous with stale sb_mode=demo": { sb_mode: "demo" },
  "empty session cookie, sb_mode=demo": { sb_mode: "demo", session: "" },
  "signed in, sb_mode=demo": { sb_mode: "demo", session: "flask-session" },
};

describe.each(Object.entries(CALLERS))(
  "public flows hit the prod backend: %s",
  (_who, jar) => {
    const ORIGINAL_ENV = { ...process.env };

    beforeEach(() => {
      vi.resetModules();
      // Same env as docker-compose.production.yml next-app service.
      process.env = {
        ...ORIGINAL_ENV,
        API_INTERNAL_URL: PROD_HOST,
        API_TEST_INTERNAL_URL: TEST_HOST,
      };
      cookieGetMock.mockImplementation((name: string) =>
        name in jar ? { name, value: jar[name] } : undefined,
      );
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          const body = String(url).includes("/certificates/verify/")
            ? VERIFIED
            : { id: 1, status: "pending" };
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }),
      );
    });

    afterEach(() => {
      process.env = { ...ORIGINAL_ENV };
      vi.unstubAllGlobals();
      vi.clearAllMocks();
    });

    it("/ansok submitApplication writes to prod", async () => {
      const { submitApplication } = await import(
        "@/app/(app)/(public)/ansok/actions"
      );
      const result = await submitApplication({
        first_name: "A",
        last_name: "B",
        email: "a@example.org",
        gdpr_consent: true,
      });
      expect(result.ok).toBe(true);
      const url = String(vi.mocked(globalThis.fetch).mock.calls[0][0]);
      expect(
        url,
        `application POSTed to ${url} (demo db, dropped by nightly sync)`,
      ).toBe(`${PROD_HOST}/api/v2/member-applications`);
    });

    it("/stamboken/verifiera reads prod", async () => {
      const { default: VerifieraPage } = await import(
        "@/app/(app)/stamboken/verifiera/[uuid]/page"
      );
      const page = await VerifieraPage({
        params: Promise.resolve({ uuid: "abc" }),
      });
      const url = String(vi.mocked(globalThis.fetch).mock.calls[0][0]);
      expect(url, `certificate verification fetched ${url} (demo db)`).toBe(
        `${PROD_HOST}/api/v2/certificates/verify/abc`,
      );
      // The verified payload renders the success branch, not "not found".
      const html = renderToStaticMarkup(page);
      expect(html).toContain(VERIFIED.individual_number);
      expect(html).not.toContain("hittades inte");
    });
  },
);
