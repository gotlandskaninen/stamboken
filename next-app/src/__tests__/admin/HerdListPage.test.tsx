import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { fetchApi, requireHerdAdmin } = vi.hoisted(() => ({
  fetchApi: vi.fn(),
  requireHerdAdmin: vi.fn(),
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchApi }));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdmin", () => ({
  requireHerdAdmin,
}));
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/admin/besattningar/HerdListGrid",
  () => ({
    HerdListGrid: ({ rows }: { rows: { herd: string }[] }) => (
      <ul>
        {rows.map((r) => (
          <li key={r.herd}>{r.herd}</li>
        ))}
      </ul>
    ),
  }),
);

import HerdListPage from "@/app/(app)/stamboken/(dashboard)/admin/besattningar/page";

const renderPage = async (sp: Record<string, string> = {}) =>
  render(await HerdListPage({ searchParams: Promise.resolve(sp) }));

const genebanks = [
  { id: 1, name: "Gotlandskanin" },
  { id: 2, name: "Mellerudskanin" },
];
const herdCall = () =>
  new URL(
    fetchApi.mock.calls.find(([p]) => p.startsWith("/manage/herd"))![0],
    "http://x",
  );

beforeEach(() => {
  vi.clearAllMocks();
  fetchApi.mockImplementation(async (path: string) =>
    path === "/genebanks" ? { genebanks } : herdList,
  );
});
afterEach(cleanup);

const herdList = {
  herds: [
    {
      id: 1,
      herd: "G1",
      herd_name: null,
      genebank_name: "Gotlandskanin",
      owner_usernames: [],
      is_active: true,
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
};

describe("herd list page (#214)", () => {
  it("shows a manager the search box and filters, from the scoped API", async () => {
    requireHerdAdmin.mockResolvedValue({ id: 3, is_manager: [1] });
    await renderPage({ q: "G1", active: "true" });

    expect(
      screen.getByRole("textbox", { name: "Sök besättningsnummer eller namn" }),
    ).toHaveValue("G1");
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Ägare")).toBeInTheDocument();
    // One genebank: nothing to choose between.
    expect(screen.queryByLabelText("Genbank")).not.toBeInTheDocument();
    expect(screen.getByText("G1")).toBeInTheDocument();

    const url = herdCall();
    expect(url.pathname).toBe("/manage/herd");
    expect(url.searchParams.get("q")).toBe("G1");
    expect(url.searchParams.get("active")).toBe("true");
  });

  it("drops a genebank the manager cannot choose", async () => {
    requireHerdAdmin.mockResolvedValue({ id: 3, is_manager: [1] });
    await renderPage({ genebank_id: "2" });

    expect(herdCall().searchParams.has("genebank_id")).toBe(false);
  });

  it("shows an admin the genebank filter too", async () => {
    requireHerdAdmin.mockResolvedValue({ id: 1, is_admin: true });
    await renderPage();

    expect(
      screen.getByRole("textbox", { name: "Sök besättningsnummer eller namn" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Genbank")).toBeInTheDocument();
  });

  it("offers a manager of two genebanks both, from /genebanks", async () => {
    requireHerdAdmin.mockResolvedValue({ id: 4, is_manager: [1, 2] });
    await renderPage({ genebank_id: "2" });

    expect(screen.getByLabelText("Genbank")).toBeInTheDocument();
    expect(herdCall().searchParams.get("genebank_id")).toBe("2");
  });
});
