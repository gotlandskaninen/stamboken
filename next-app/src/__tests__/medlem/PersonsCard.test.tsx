// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const { showSnackbarMock, addNotificationMock } = vi.hoisted(() => ({
  showSnackbarMock: vi.fn(),
  addNotificationMock: vi.fn(),
}));

vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  addPerson: vi.fn(),
  anonymizePerson: vi.fn(),
  createGrant: vi.fn(),
  linkPersonUser: vi.fn(),
  removePerson: vi.fn(),
  renewGrant: vi.fn(),
  revokeGrant: vi.fn(),
  setMainMember: vi.fn(),
  unlinkPersonUser: vi.fn(),
  updatePerson: vi.fn(),
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: showSnackbarMock }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: addNotificationMock }),
}));

import { PersonsCard } from "@/app/(app)/medlem/matrikel/[id]/PersonsCard";
import { updatePerson } from "@/app/(app)/medlem/matrikel/actions";
import type {
  MembershipDetail,
  Person,
} from "@/app/(app)/medlem/matrikel/types";

function person(over: Partial<Person> & Pick<Person, "id">): Person {
  return {
    first_name: "F",
    last_name: "L",
    email: "person@example.com",
    phone: null,
    role: "familjemedlem",
    end_date: null,
    user_id: null,
    user: null,
    grants: [],
    ...over,
  };
}

const MEMBERSHIP: MembershipDetail = {
  id: 1,
  member_number: 1274,
  membership_status: "active",
  organization_name: null,
  address: null,
  postal_code: null,
  city: null,
  postal_address: null,
  billing_name: null,
  billing_address: null,
  billing_postal_code: null,
  billing_city: null,
  billing_email: null,
  billing_reference: null,
  publication_consent: {},
  payment_note: null,
  joined_date: "2019-03-01",
  notes: null,
  herds: [
    {
      id: 3,
      herd: "G1274",
      herd_name: "Solhaga",
      genebank_id: 1,
      is_active: true,
    },
  ],
  persons: [
    person({
      id: 11,
      first_name: "Anna",
      last_name: "Linkad",
      role: "huvudmedlem",
      user_id: 7,
      user: { id: 7, username: "anna.l", email: "anna@example.com" },
    }),
    person({ id: 12, first_name: "Bo", last_name: "Olinkad" }),
    person({
      id: 13,
      first_name: "Cecilia",
      last_name: "Avslutad",
      role: "skotare",
      end_date: "2026-01-01",
      user_id: 8,
      user: { id: 8, username: "cecilia.a", email: "cecilia@example.com" },
    }),
    person({
      id: 14,
      first_name: "David",
      last_name: "Avslutad",
      end_date: "2026-01-01",
    }),
  ],
};

const row = (name: RegExp) => screen.getByRole("row", { name });

afterEach(cleanup);

describe("PersonsCard — organisationens kontaktperson", () => {
  const contact = person({
    id: 11,
    first_name: "",
    last_name: "",
    role: "huvudmedlem",
  });
  const organization = {
    ...MEMBERSHIP,
    organization_name: "Exempelföreningen",
    persons: [contact],
  };

  it("displays an unnamed contact and allows editing the email alone", async () => {
    vi.mocked(updatePerson).mockResolvedValue({ ok: true });
    render(<PersonsCard membership={organization} canEdit />);
    const contactRow = row(/ingen namngiven kontaktperson/);
    expect(within(contactRow).getByText("Kontaktperson")).toBeInTheDocument();
    fireEvent.click(
      within(contactRow).getByRole("button", { name: "Redigera" }),
    );
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByLabelText("Förnamn")).not.toBeRequired();
    fireEvent.change(dialog.getByLabelText("E-post"), {
      target: { value: "kontakt@example.com" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(updatePerson).toHaveBeenCalledWith(1, 11, {
        first_name: "",
        last_name: "",
        email: "kontakt@example.com",
        phone: null,
      }),
    );
  });

  it("requires names when adding another person to the organisation", () => {
    render(<PersonsCard membership={organization} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till person" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByLabelText(/^Förnamn/)).toBeRequired();
    expect(dialog.getByRole("button", { name: "Spara" })).toBeDisabled();
  });

  it("requires both names when editing an ended organisation contact", () => {
    const ended = { ...contact, end_date: "2026-01-01" };
    render(
      <PersonsCard
        membership={{ ...organization, persons: [ended] }}
        canEdit
      />,
    );
    fireEvent.click(
      within(row(/avslutad/)).getByRole("button", { name: "Redigera" }),
    );
    const dialog = within(screen.getByRole("dialog"));
    const firstName = dialog.getByLabelText(/^Förnamn/);
    const lastName = dialog.getByLabelText(/^Efternamn/);
    const save = dialog.getByRole("button", { name: "Spara" });
    expect(firstName).toBeRequired();
    expect(lastName).toBeRequired();
    // unchanged names: other fields can be saved, as the API allows
    expect(save).toBeEnabled();
    fireEvent.change(firstName, { target: { value: "Lo" } });
    expect(save).toBeDisabled();
    fireEvent.change(lastName, { target: { value: "Exempel" } });
    expect(save).toBeEnabled();
  });
});

describe("PersonsCard — importerad rad utan förnamn", () => {
  it("saves a phone change without asking for a first name", async () => {
    vi.mocked(updatePerson).mockResolvedValue({ ok: true });
    const imported = person({
      id: 21,
      first_name: "",
      last_name: "Testbiblioteket",
      role: "huvudmedlem",
    });
    render(
      <PersonsCard
        membership={{ ...MEMBERSHIP, persons: [imported] }}
        canEdit
      />,
    );
    fireEvent.click(
      within(row(/Testbiblioteket/)).getByRole("button", { name: "Redigera" }),
    );
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    const save = dialog.getByRole("button", { name: "Spara" });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(updatePerson).toHaveBeenCalledWith(
        1,
        21,
        expect.objectContaining({ phone: "070-1234567" }),
      ),
    );
  });
});

describe("PersonsCard — Konto column", () => {
  it("shows the username and Koppla bort for a linked active person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Anna Linkad/);
    expect(within(cell).getByText("anna.l")).toBeInTheDocument();
    expect(
      within(cell).getByRole("button", { name: "Koppla bort" }),
    ).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("offers Koppla konto… for an unlinked active person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Bo Olinkad/);
    expect(
      within(cell).getByRole("button", { name: "Koppla konto…" }),
    ).toBeInTheDocument();
  });

  it("keeps Koppla bort — but never Koppla konto… — on an ended linked person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Cecilia Avslutad/);
    expect(within(cell).getByText("cecilia.a")).toBeInTheDocument();
    expect(
      within(cell).getByRole("button", { name: "Koppla bort" }),
    ).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("renders an em dash for an ended unlinked person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/David Avslutad/);
    expect(within(cell).getByText("—")).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("renders the column read-only when canEdit is false", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit={false} />);
    expect(screen.getByText("Konto")).toBeInTheDocument();
    expect(screen.getByText("anna.l")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Koppla bort" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });
});
