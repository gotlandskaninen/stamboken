import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { HistorikCard } from "@/app/(app)/medlem/matrikel/[id]/HistorikCard";
import type { MatrikelAuditPage } from "@/app/(app)/medlem/matrikel/types";

afterEach(cleanup);

const history: MatrikelAuditPage = {
  total: 12,
  page: 1,
  per_page: 10,
  rows: [
    {
      id: 2,
      action: "person_updated",
      created_at: "2026-11-20T09:05:00+01:00",
      actor: { id: 7, name: "matrikelkonto" },
      membership: { id: 5, member_number: 99 },
      person: { id: 3, name: "Tova Testsson" },
      payload: {
        person_id: 3,
        before: { email: "[borttagen]" },
        after: { email: "[borttagen]" },
      },
    },
    {
      id: 1,
      action: "person_anonymized",
      created_at: "2026-11-21T02:00:00+01:00",
      actor: null,
      membership: { id: 5, member_number: 99 },
      person: { id: 4, name: "" },
      payload: { person_id: 4 },
    },
  ],
};

it("lists time, actor, action, person and changed fields", () => {
  render(<HistorikCard membershipId={5} history={history} isAdmin={false} />);
  expect(screen.getByRole("heading", { name: "Historik" })).toBeInTheDocument();
  expect(
    screen.getByText("2026-11-20 09:05:00 · matrikelkonto"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Person ändrad · Tova Testsson — E-post"),
  ).toBeInTheDocument();
  expect(screen.getByText(/nattlig gallring/)).toBeInTheDocument();
  expect(
    screen.getByText("Person anonymiserad · Person #4"),
  ).toBeInTheDocument();
});

it("links the full list and the account only for admin", () => {
  const { rerender } = render(
    <HistorikCard membershipId={5} history={history} isAdmin={false} />,
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  rerender(<HistorikCard membershipId={5} history={history} isAdmin />);
  expect(
    screen.getByRole("link", { name: "Visa hela historiken (12)" }),
  ).toHaveAttribute(
    "href",
    "/stamboken/admin/system/audit?source=matrikel&membership_id=5",
  );
  expect(screen.getByRole("link", { name: "matrikelkonto" })).toHaveAttribute(
    "href",
    "/stamboken/admin/anvandare/7",
  );
});

it("says so when the log is empty or cannot be read", () => {
  const { rerender } = render(
    <HistorikCard
      membershipId={5}
      history={{ ...history, rows: [], total: 0 }}
      isAdmin
    />,
  );
  expect(
    screen.getByText("Inga ändringar är loggade ännu."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  rerender(<HistorikCard membershipId={5} history={null} isAdmin />);
  expect(
    screen.getByText("Historiken kunde inte läsas just nu."),
  ).toBeInTheDocument();
});
