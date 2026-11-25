import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MatrikelAuditClient } from "@/app/(app)/stamboken/(dashboard)/admin/system/audit/MatrikelAuditClient";
import type { MatrikelAuditRow } from "@/app/(app)/medlem/matrikel/types";

afterEach(cleanup);

const rows: MatrikelAuditRow[] = [
  {
    id: 9,
    action: "membership_status_changed",
    created_at: "2026-11-20T09:05:00+01:00",
    actor: { id: 7, name: "adminkonto" },
    membership: { id: 5, member_number: 99 },
    person: null,
    payload: {
      before: { membership_status: "active" },
      after: { membership_status: "inactive" },
    },
  },
  {
    id: 8,
    action: "person_user_linked",
    created_at: "2026-11-19T10:00:00+01:00",
    actor: null,
    membership: { id: 5, member_number: null },
    person: { id: 3, name: "Tova Testsson" },
    payload: { person_id: 3, user_id: 11, source: "admin" },
  },
];

const filters = {
  action: "",
  actor: "adminkonto",
  member_number: "99",
  membership_id: "",
  from: "",
  to: "",
};

it("shows each event and its before and after on open", () => {
  render(
    <MatrikelAuditClient
      rows={rows}
      total={2}
      page={1}
      perPage={50}
      filters={filters}
    />,
  );
  const status = screen.getByRole("button", { name: /Status ändrad/ });
  expect(status).toHaveTextContent("Medlemskap nr 99");
  expect(status).toHaveTextContent("adminkonto · 2026-11-20 09:05:00");
  fireEvent.click(status);
  expect(screen.getByText("Aktiv")).toBeInTheDocument();
  expect(screen.getByText("Inaktiv")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "adminkonto" })).toHaveAttribute(
    "href",
    "/stamboken/admin/anvandare/7",
  );

  const linked = screen.getByRole("button", { name: /Konto kopplat/ });
  expect(linked).toHaveTextContent("Medlemskap #5 · Tova Testsson");
  expect(linked).toHaveTextContent("Nattlig gallring");
  fireEvent.click(linked);
  expect(screen.getByText("Konto")).toBeInTheDocument();
  expect(screen.getByText("11")).toBeInTheDocument();
});

it("keeps the source and the filters in the form and the page links", () => {
  const { container } = render(
    <MatrikelAuditClient
      rows={rows}
      total={120}
      page={2}
      perPage={50}
      filters={filters}
    />,
  );
  expect(
    container.querySelector('input[type="hidden"][name="source"]'),
  ).toHaveValue("matrikel");
  expect(screen.getByLabelText("Medlemsnummer")).toHaveValue("99");
  expect(
    container.querySelector('input[name="membership_id"]'),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Nästa" })).toHaveAttribute(
    "href",
    "/stamboken/admin/system/audit?source=matrikel&actor=adminkonto&member_number=99&page=3",
  );
  expect(screen.getByText("Sida 2 av 3")).toBeInTheDocument();
});

it("keeps the member page's membership id through a new filter", () => {
  const { container } = render(
    <MatrikelAuditClient
      rows={rows}
      total={1}
      page={1}
      perPage={50}
      filters={{ ...filters, member_number: "", membership_id: "5" }}
    />,
  );
  expect(
    container.querySelector('input[type="hidden"][name="membership_id"]'),
  ).toHaveValue("5");
});

it("does not link a masked actor", () => {
  render(
    <MatrikelAuditClient
      rows={[{ ...rows[0], actor: { id: null, name: "[borttagen]" } }]}
      total={1}
      page={1}
      perPage={50}
      filters={filters}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Status ändrad/ }));
  expect(screen.getByText(/Utförd av \[borttagen\]/)).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "[borttagen]" }),
  ).not.toBeInTheDocument();
});
