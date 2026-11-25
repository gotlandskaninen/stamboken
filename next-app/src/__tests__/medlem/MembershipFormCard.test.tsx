// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const {
  updateMembershipMock,
  retireMembershipMock,
  showSnackbarMock,
  addNotificationMock,
} = vi.hoisted(() => ({
  updateMembershipMock: vi.fn(),
  retireMembershipMock: vi.fn(),
  showSnackbarMock: vi.fn(),
  addNotificationMock: vi.fn(),
}));

vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  updateMembership: updateMembershipMock,
  retireMembership: retireMembershipMock,
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: showSnackbarMock }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: addNotificationMock }),
}));

import { MembershipFormCard } from "@/app/(app)/medlem/matrikel/[id]/MembershipFormCard";
import type { MembershipDetail } from "@/app/(app)/medlem/matrikel/types";

const MEMBERSHIP: MembershipDetail = {
  id: 1,
  member_number: 1274,
  membership_status: "active",
  organization_name: null,
  organization_number: null,
  address: "Solhagavägen 12",
  postal_code: "623 55",
  city: "Klintehamn",
  postal_address: "623 55 Klintehamn",
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
  herds: [],
  persons: [],
};

const NUMBER_ERROR = "Medlemsnummer ska vara ett heltal större än 0";

beforeEach(() => {
  updateMembershipMock.mockReset();
  retireMembershipMock.mockReset();
  showSnackbarMock.mockReset();
  addNotificationMock.mockReset();
  updateMembershipMock.mockResolvedValue({ ok: true });
  retireMembershipMock.mockResolvedValue({ ok: true });
});

afterEach(cleanup);

const numberField = () => screen.getByLabelText("Medlemsnummer");
const spara = () => screen.getByRole("button", { name: /Spara/ });

describe("MembershipFormCard — juridisk person", () => {
  const checkbox = () =>
    screen.getByRole("checkbox", { name: "Juridisk person (organisation)" });

  it("converts a membership to an organisation with an optional number", async () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);
    fireEvent.click(checkbox());
    expect(spara()).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Organisationsnamn"), {
      target: { value: "Exempelföreningen" },
    });
    const number = screen.getByLabelText("Organisationsnummer");
    fireEvent.change(number, { target: { value: "abc" } });
    expect(spara()).toBeDisabled();
    fireEvent.change(number, { target: { value: "" } });
    fireEvent.click(spara());
    await waitFor(() =>
      expect(updateMembershipMock).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          organization_name: "Exempelföreningen",
        }),
      ),
    );
  });

  it("keeps the stored number out of a rename", async () => {
    render(
      <MembershipFormCard
        membership={{
          ...MEMBERSHIP,
          organization_name: "Exempelföreningen",
          organization_number: "123456-7897",
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("Organisationsnamn"), {
      target: { value: "Nya föreningen" },
    });
    fireEvent.click(spara());
    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    const [, patch] = updateMembershipMock.mock.calls[0];
    expect(patch.organization_name).toBe("Nya föreningen");
    expect(patch).not.toHaveProperty("organization_number");
  });

  it("requires both names before clearing an organisation", async () => {
    const membership = {
      ...MEMBERSHIP,
      organization_name: "Exempelföreningen",
      organization_number: "123456-7897",
    };
    const contact = {
      id: 11,
      first_name: "Karin",
      last_name: "",
      role: "huvudmedlem",
      end_date: null,
      phone: null,
      email: null,
      user_id: null,
      user: null,
      grants: [],
    };
    const { rerender } = render(
      <MembershipFormCard membership={{ ...membership, persons: [contact] }} />,
    );
    expect(checkbox()).toBeChecked();
    expect(screen.getByLabelText("Organisationsnummer")).toHaveValue(
      "123456-7897",
    );
    fireEvent.click(checkbox());
    expect(spara()).toBeDisabled();
    expect(
      screen.getByText(/Ange kontaktpersonens förnamn och efternamn/),
    ).toBeInTheDocument();
    rerender(
      <MembershipFormCard
        membership={{
          ...membership,
          persons: [{ ...contact, last_name: "Exempel" }],
        }}
      />,
    );
    fireEvent.click(spara());
    await waitFor(() =>
      expect(updateMembershipMock).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          organization_name: null,
          organization_number: null,
        }),
      ),
    );
  });
});

describe("MembershipFormCard — medlemsnummer validation", () => {
  it("blocks a medlemsnummer that is not a positive integer", () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);

    fireEvent.change(numberField(), { target: { value: "abc" } });
    expect(screen.getByText(NUMBER_ERROR)).toBeInTheDocument();
    expect(spara()).toBeDisabled();

    fireEvent.change(numberField(), { target: { value: "12.5" } });
    expect(screen.getByText(NUMBER_ERROR)).toBeInTheDocument();
    expect(spara()).toBeDisabled();

    fireEvent.change(numberField(), { target: { value: "0" } });
    expect(screen.getByText(NUMBER_ERROR)).toBeInTheDocument();
    expect(spara()).toBeDisabled();

    expect(updateMembershipMock).not.toHaveBeenCalled();
  });

  it("sends a valid medlemsnummer", async () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);

    fireEvent.change(numberField(), { target: { value: "12" } });
    expect(screen.queryByText(NUMBER_ERROR)).not.toBeInTheDocument();
    expect(spara()).toBeEnabled();

    fireEvent.click(spara());

    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    expect(updateMembershipMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ member_number: 12 }),
    );
  });
});

describe("MembershipFormCard — retire re-bases the status select", () => {
  it("sends membership_status=inactive on the next Spara after a retire", async () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);

    fireEvent.click(screen.getByRole("button", { name: "Avsluta medlemskap" }));
    fireEvent.click(screen.getByRole("button", { name: "Bekräfta" }));
    await waitFor(() => expect(retireMembershipMock).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(showSnackbarMock).toHaveBeenCalledWith(
        "Medlemskapet avslutat",
        "success",
      ),
    );

    // The select now says Inaktiv, so a later edit cannot re-activate the
    // membership behind the admin's back. (waitFor: the confirm dialog is
    // still aria-hiding the page while its exit transition runs.)
    await waitFor(() =>
      expect(screen.getByRole("combobox")).toHaveTextContent("Inaktiv"),
    );
    // …and the Avsluta button is gone before the revalidated prop arrives,
    // so a second click cannot write another membership_retired audit row.
    expect(
      screen.queryByRole("button", { name: "Avsluta medlemskap" }),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(spara()).toBeEnabled());
    fireEvent.click(spara());
    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    expect(updateMembershipMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ membership_status: "inactive" }),
    );
  });
});

describe("MembershipFormCard — retired state", () => {
  const person = (role: string) =>
    ({ role, end_date: null }) as MembershipDetail["persons"][number];
  const inactive = (...roles: string[]) => ({
    ...MEMBERSHIP,
    membership_status: "inactive" as const,
    persons: roles.map(person),
  });
  const avsluta = () =>
    screen.queryByRole("button", { name: "Avsluta medlemskap" });
  const locked = () =>
    screen.getByRole("combobox").getAttribute("aria-disabled") === "true";

  it("locks the select and hides Avsluta when inactive with no active person", () => {
    render(<MembershipFormCard membership={inactive()} />);

    expect(locked()).toBe(true);
    expect(screen.getByText(/kan inte återaktiveras/)).toBeInTheDocument();
    expect(avsluta()).not.toBeInTheDocument();
  });

  it("still offers Avsluta when inactive but the main member remains", () => {
    render(<MembershipFormCard membership={inactive("huvudmedlem")} />);

    expect(avsluta()).toBeInTheDocument();
    expect(locked()).toBe(false);
  });

  // The backend answers 409 here: inactive without a huvudmedlem is its RETIRED.
  it("locks the select but keeps Avsluta when only a family member is left", () => {
    render(<MembershipFormCard membership={inactive("familjemedlem")} />);

    expect(locked()).toBe(true);
    expect(screen.getByText(/saknar huvudmedlem/)).toBeInTheDocument();
    expect(avsluta()).toBeInTheDocument();
  });
});

describe("MembershipFormCard — annan fakturaadress", () => {
  const billingBox = () =>
    screen.getByRole("checkbox", { name: "Annan fakturaadress" });

  it("is folded away and saves an empty billing address by default", async () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);

    expect(billingBox()).not.toBeChecked();
    expect(screen.queryByLabelText("Fakturamottagare")).not.toBeInTheDocument();
    expect(
      screen.getByText("Fakturan går till postadressen."),
    ).toBeInTheDocument();

    fireEvent.click(spara());
    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    expect(updateMembershipMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        billing_name: null,
        billing_address: null,
        billing_postal_code: null,
        billing_city: null,
        billing_email: null,
        billing_reference: null,
      }),
    );
  });

  it("unfolds, validates the postnummer and sends the billing fields", async () => {
    render(<MembershipFormCard membership={MEMBERSHIP} />);

    fireEvent.click(billingBox());
    fireEvent.change(screen.getByLabelText("Fakturamottagare"), {
      target: { value: "Djurparken i Exempelby" },
    });
    fireEvent.change(screen.getByLabelText("Fakturaadress"), {
      target: { value: "Box 99" },
    });
    const postal = screen.getByLabelText("Fakturapostnummer");
    fireEvent.change(postal, { target: { value: "987" } });
    expect(spara()).toBeDisabled();
    fireEvent.change(postal, { target: { value: "98765" } });
    fireEvent.blur(postal);
    expect(postal).toHaveValue("987 65");
    fireEvent.change(screen.getByLabelText("Fakturapostort"), {
      target: { value: "Annanstad" },
    });
    fireEvent.change(screen.getByLabelText("Fakturareferens"), {
      target: { value: "Kostnadsställe 4711" },
    });
    expect(spara()).toBeEnabled();

    fireEvent.click(spara());
    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    expect(updateMembershipMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        billing_name: "Djurparken i Exempelby",
        billing_address: "Box 99",
        billing_postal_code: "987 65",
        billing_city: "Annanstad",
        billing_email: null,
        billing_reference: "Kostnadsställe 4711",
        // The postal address is sent unchanged next to it.
        postal_code: "623 55",
        city: "Klintehamn",
      }),
    );
  });

  it("opens with a stored billing address and clears it when unticked", async () => {
    render(
      <MembershipFormCard
        membership={{
          ...MEMBERSHIP,
          billing_name: "Gården",
          billing_city: "Annanstad",
        }}
      />,
    );

    expect(billingBox()).toBeChecked();
    expect(screen.getByLabelText("Fakturamottagare")).toHaveValue("Gården");

    fireEvent.click(billingBox());
    expect(
      screen.getByText("Fakturaadressen tas bort när du sparar."),
    ).toBeInTheDocument();
    fireEvent.click(spara());
    await waitFor(() => expect(updateMembershipMock).toHaveBeenCalledTimes(1));
    expect(updateMembershipMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ billing_name: null, billing_city: null }),
    );
  });
});
