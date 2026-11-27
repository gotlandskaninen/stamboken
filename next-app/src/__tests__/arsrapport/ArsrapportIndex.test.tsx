import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { getInboxCount } from "@/lib/inkorg-server";
import ArsrapportIndex from "@/app/(app)/stamboken/(dashboard)/arsrapport/page";

vi.mock("@/lib/api", () => ({ fetchApi: vi.fn() }));
vi.mock("@/lib/auth", () => ({ requireUser: vi.fn() }));
vi.mock("@/lib/inkorg-server", () => ({ getInboxCount: vi.fn() }));

afterEach(cleanup);

async function showEmptyPage(herds: string[] | null, worksInQueue: boolean) {
  vi.mocked(requireUser, { partial: true }).mockResolvedValue({
    is_owner: herds,
    is_admin: false,
    is_manager: null,
  });
  vi.mocked(fetchApi).mockResolvedValue({ reports: [] });
  vi.mocked(getInboxCount).mockResolvedValue({
    unread: 0,
    works_in_queue: worksInQueue,
  });
  render(await ArsrapportIndex());
}

const empty = "Ingen årsrapport är öppen för dina besättningar ännu.";
const helper =
  "Du har inga egna besättningar. Årsrapporter som kommer in på papper registrerar du i Inkorgen.";

it("links a herdless inbox worker to Inkorgen", async () => {
  await showEmptyPage(null, true);
  expect(screen.getByText(helper)).toBeTruthy();
  const link = screen.getByRole("link", { name: "Till Inkorgen" });
  expect(link.getAttribute("href")).toBe("/stamboken/inkorg");
  expect(screen.queryByText(empty)).toBeNull();
});

it.each([
  { who: "a worker with a herd", herds: ["G9001"], worksInQueue: true },
  { who: "a herdless non-worker", herds: null, worksInQueue: false },
])("keeps the empty page for $who", async ({ herds, worksInQueue }) => {
  await showEmptyPage(herds, worksInQueue);
  expect(screen.getByText(empty)).toBeTruthy();
  expect(screen.queryByText(helper)).toBeNull();
  expect(screen.queryByRole("link", { name: "Till Inkorgen" })).toBeNull();
});
