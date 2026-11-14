import { describe, expect, test, vi } from "vitest";
import { fetchApi } from "@/lib/api";
import IndividualPage from "@/app/(app)/stamboken/(dashboard)/individ/[number]/page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchApi: vi.fn() };
});
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));

const mockedFetch = vi.mocked(fetchApi);

describe("individual page data loading", () => {
  test("fetches history and audit in parallel, each degrading to null", async () => {
    let releaseHistory: (value: unknown) => void = () => {};
    mockedFetch.mockImplementation((path: string) => {
      if (path.startsWith("/v2/individual/") && path.includes("herd-tracking"))
        return new Promise((resolve) => {
          releaseHistory = resolve;
        });
      if (path.startsWith("/v2/individual/"))
        return Promise.resolve({ id: 7, number: "G1-2401" });
      if (path.startsWith("/audit-log/"))
        return Promise.reject(new Error("403"));
      return Promise.resolve(null);
    });
    const page = IndividualPage({
      params: Promise.resolve({ number: "G1-2401" }),
    });
    await vi.waitFor(() =>
      expect(mockedFetch).toHaveBeenCalledWith("/audit-log/individual/7"),
    );
    releaseHistory(null);
    const element = (await page) as React.ReactElement<{
      children: React.ReactElement<{ history: unknown; auditEntries: unknown }>;
    }>;
    expect(element.props.children.props.history).toBeNull();
    expect(element.props.children.props.auditEntries).toEqual([]);
  });

  test("renders the paper certificate only when the API has a copy", async () => {
    for (const has of [true, false]) {
      mockedFetch.mockReset();
      mockedFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.endsWith("/paper-certificate")) {
          expect(options?.method).toBe("HEAD");
          return has ? Promise.resolve(undefined) : Promise.reject(new Error());
        }
        if (
          path.startsWith("/v2/individual/") &&
          !path.includes("herd-tracking")
        )
          return Promise.resolve({ id: 7, number: "G1-2401" });
        return Promise.resolve(null);
      });
      const element = (await IndividualPage({
        params: Promise.resolve({ number: "G1-2401" }),
      })) as React.ReactElement<{
        children: React.ReactElement<{ hasPaperCertificate: boolean }>;
      }>;
      expect(element.props.children.props.hasPaperCertificate).toBe(has);
    }
  });
});
