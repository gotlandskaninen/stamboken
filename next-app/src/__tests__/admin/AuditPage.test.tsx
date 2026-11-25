import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { fetchApi } = vi.hoisted(() => ({ fetchApi: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  usePathname: () => "",
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchApi,
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdmin", () => ({
  requireAdmin: vi.fn(),
}));

import AuditPage from "@/app/(app)/stamboken/(dashboard)/admin/system/audit/page";
import { ApiError } from "@/lib/api";

const renderPage = async (sp: Record<string, string> = {}) =>
  render(await AuditPage({ searchParams: Promise.resolve(sp) }));

beforeEach(() => {
  fetchApi.mockReset();
});
afterEach(cleanup);

it("reads the matrikel's log with its own filters under source=matrikel (#244)", async () => {
  fetchApi.mockResolvedValue({ rows: [], total: 0, page: 1, per_page: 50 });
  await renderPage({
    source: "matrikel",
    action: "person_updated",
    member_number: "99",
    membership_id: "5",
    table: "hbuser",
  });
  expect(fetchApi).toHaveBeenCalledWith(
    "/v2/members/audit?action=person_updated&member_number=99&membership_id=5",
    { forceProd: true },
  );
  expect(
    screen.getByRole("heading", { name: /Matrikelns logg/ }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Matrikeln" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

it("keeps the studbook log as the default", async () => {
  fetchApi.mockResolvedValue({ rows: [], total: 0, page: 1, per_page: 50 });
  await renderPage({ table: "hbuser" });
  expect(fetchApi).toHaveBeenCalledWith("/v2/admin/audit-log?table=hbuser", {
    forceProd: true,
  });
  expect(screen.getByRole("link", { name: "Stamboken" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

it("says so when the matrikel's log cannot be read", async () => {
  fetchApi.mockRejectedValue(new Error("503"));
  await renderPage({ source: "matrikel" });
  expect(
    screen.getByText("Kunde inte läsa matrikelns logg just nu."),
  ).toBeInTheDocument();
});

it("shows the API's reason for a wrong filter and keeps the form (Opus #248)", async () => {
  fetchApi.mockRejectedValue(
    new ApiError({
      status: 400,
      title: "Ogiltig parameter",
      detail: "member_number måste vara ett positivt heltal",
    }),
  );
  await renderPage({ source: "matrikel", member_number: "0" });
  expect(
    screen.getByText("member_number måste vara ett positivt heltal"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Filtrera" })).toBeInTheDocument();
  expect(screen.getByLabelText("Medlemsnummer")).toHaveValue("0");
});
