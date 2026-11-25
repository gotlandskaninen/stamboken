import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import MembershipsListPage from "@/app/(app)/medlem/matrikel/page";

const { fetchApi, getUser } = vi.hoisted(() => ({
  fetchApi: vi.fn(),
  getUser: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ fetchApi }));
vi.mock("@/lib/auth", () => ({ getUser }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/app/(app)/medlem/matrikel/MembershipsGridClient", () => ({
  MembershipsGridClient: () => null,
}));

afterEach(cleanup);

it.each([
  [["G", "M"], ""],
  ["X", ""],
  ["M", "M"],
])(
  "passes only a single G or M on to the API and the filter (%j)",
  async (raw, expected) => {
    fetchApi.mockResolvedValue({ items: [], total: 0, page: 1, per_page: 25 });
    getUser.mockResolvedValue({ is_admin: false });
    const { container } = render(
      await MembershipsListPage({
        // A repeated ?active_herd= arrives as an array.
        searchParams: Promise.resolve({
          active_herd: raw as unknown as string,
        }),
      }),
    );
    const url = new URL(fetchApi.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("active_herd") ?? "").toBe(expected);
    expect(
      container.querySelector<HTMLInputElement>('input[name="active_herd"]')!
        .value,
    ).toBe(expected);
  },
);
