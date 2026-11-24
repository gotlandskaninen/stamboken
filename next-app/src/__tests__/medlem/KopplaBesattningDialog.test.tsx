import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { KopplaBesattningButton } from "@/app/(app)/medlem/matrikel/[id]/KopplaBesattningDialog";
import type { HerdLinkPreview } from "@/app/(app)/medlem/matrikel/types";

const { link, snackbar, notify } = vi.hoisted(() => ({
  link: vi.fn(),
  snackbar: vi.fn(),
  notify: vi.fn(),
}));
vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  linkMembershipHerd: link,
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: snackbar }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: notify }),
}));

const herd = { id: 8, herd: "G12", herd_name: "Testgården", is_active: false };
const preview: HerdLinkPreview = {
  herd: { ...herd, genebank_id: 1, genebank_name: "Gotland" },
  membership: { id: 3, member_number: 19, membership_status: "active" },
  new_access: {
    id: 41,
    username: "testkonto",
    already_edits: false,
    already_manages: false,
  },
  inactive_main_account: null,
  new_readers: [{ id: 44, username: "laskonto" }],
  legacy_owners: [
    {
      id: 42,
      username: "tidigare",
      in_membership: false,
      gains_household_grants: false,
    },
  ],
  grant_holders: [{ id: 45, username: "skotarkonto" }],
  contact_rows: [
    {
      field: "name",
      label: "Namn",
      case: "bara_matrikeln",
      effect:
        "Test Kontakt blir kontaktperson. Raden visas inte förrän någon väljer.",
    },
    {
      field: "email",
      label: "E-post",
      case: "lika",
      effect: "Besättningens kopia töms.",
    },
  ],
};

const pausedPreview: HerdLinkPreview = {
  ...preview,
  membership: { ...preview.membership, membership_status: "inactive" },
  new_readers: [],
  contact_rows: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v2/genebanks/public") {
        return Response.json({
          genebanks: [
            { id: 1, name: "Gotland" },
            { id: 2, name: "Mellerud" },
          ],
        });
      }
      if (url.endsWith("genebank_id=2")) return Response.json({ herds: [] });
      if (url !== "/api/v2/memberships/3/herd-candidates?genebank_id=1")
        throw new Error("Oväntad adress");
      return Response.json({
        herds: [
          { ...herd, link: "ingen", member_number: null },
          { ...herd, id: 9, herd: "G25", link: "annat", member_number: 27 },
          {
            ...herd,
            id: 11,
            herd: "G27",
            link: "ingen",
            unavailable_reason: "koden finns i flera genbanker",
          },
          { ...herd, id: 10, herd: "G26", link: "detta", member_number: null },
        ],
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function chooseBank() {
  render(<KopplaBesattningButton membershipId={3} />);
  fireEvent.click(screen.getByRole("button", { name: "Koppla besättning" }));
  await screen.findByRole("option", { name: "Gotland" });
  fireEvent.change(screen.getByLabelText("Genbank"), {
    target: { value: "1" },
  });
  return screen.findByRole("radio", { name: /G12/ });
}

const button = (name: string) => screen.getByRole("button", { name });

async function clickButton(name: string) {
  await act(async () => {
    fireEvent.click(button(name));
  });
}

const ownerRights =
  /ge hushållet tillgång och utfärda intyg för kaniner med besättningen som ursprung\. Kontot får också se och ändra besättningens utbetalningskonto/;

describe("KopplaBesattningDialog", () => {
  it("filters by number, marks inactive herds and prevents selecting a linked herd", async () => {
    const candidate = await chooseBank();
    expect(candidate).toHaveAccessibleName(/Inaktiv/);
    expect(screen.getByRole("radio", { name: /G25.*27/ })).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: /G26.*detta medlemskap/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: /G27.*koden finns i flera genbanker/ }),
    ).toBeDisabled();
    expect(button("Visa vad kopplingen ger")).toBeDisabled();
    fireEvent.click(candidate);
    expect(button("Visa vad kopplingen ger")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Filtrera på besättningsnummer"), {
      target: { value: "g25" },
    });
    expect(
      screen.queryByRole("radio", { name: /G12/ }),
    ).not.toBeInTheDocument();
    expect(button("Visa vad kopplingen ger")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Genbank"), {
      target: { value: "2" },
    });
    expect(
      await screen.findByText("Inga besättningar hittades."),
    ).toBeInTheDocument();
  });

  it("shows changed access and confirms only the latest preview", async () => {
    fireEvent.click(await chooseBank());
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: { preview, confirm_token: "first" },
    });
    await clickButton("Visa vad kopplingen ger");
    expect(
      await screen.findByText(
        /testkonto.*innehavare.*ändra, sälja och flytta kaniner/,
      ),
    ).toHaveTextContent(ownerRights);
    expect(
      screen.getByText(/tidigare.*saknar aktiv person i medlemskapet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Besättningens kopia töms/)).toBeInTheDocument();
    expect(
      screen.getByText(/laskonto.*läsa matrikelns kontaktuppgifter/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/skotarkonto.*skötartillstånd/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Test Kontakt blir kontaktperson.*visas inte förrän någon väljer/,
      ),
    ).toBeInTheDocument();
    expect(link).toHaveBeenCalledWith(3, 8, undefined);

    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: {
        preview: {
          ...preview,
          new_access: {
            id: 43,
            username: "nyttkonto",
            already_edits: true,
            already_manages: false,
          },
        },
        confirm_token: "next",
      },
    });
    await clickButton("Koppla");
    expect(
      await screen.findByText(/Underlaget har ändrats/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /nyttkonto.*redan ändra kaniner.*också sälja och flytta dem/,
      ),
    ).toHaveTextContent(ownerRights);
    expect(screen.queryByText(/testkonto/)).not.toBeInTheDocument();
    expect(link).toHaveBeenLastCalledWith(3, 8, "first");
    expect(snackbar).not.toHaveBeenCalled();

    link.mockResolvedValueOnce({ ok: true });
    await clickButton("Koppla");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(link).toHaveBeenLastCalledWith(3, 8, "next");
    expect(snackbar).toHaveBeenCalledWith("Besättning kopplad", "success");
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success" }),
    );
  });

  it("explains deferred access and comparison, and cancel never confirms", async () => {
    fireEvent.click(await chooseBank());
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: {
        confirm_token: "inactive",
        preview: pausedPreview,
      },
    });
    await clickButton("Visa vad kopplingen ger");
    expect(
      await screen.findByText(
        /Huvudmedlemmen kan genast ge hushållet skötartillstånd/,
      ),
    ).toHaveTextContent(/Åtkomsten börjar när medlemskapet blir aktivt/);
    expect(
      screen.getByText(/jämförs när medlemskapet blir aktivt/i),
    ).toBeInTheDocument();
    await clickButton("Avbryt");
    expect(link).toHaveBeenCalledTimes(1);
    await clickButton("Koppla besättning");
    await screen.findByRole("option", { name: "Gotland" });
    expect(
      screen.queryByRole("button", { name: "Koppla" }),
    ).not.toBeInTheDocument();
  });

  it.each([null, { id: 41, username: "vilande" }])(
    "only shows deferred access for a paused membership without an active main account (%j)",
    async (inactive_main_account) => {
      fireEvent.click(await chooseBank());
      link.mockResolvedValueOnce({
        ok: false,
        confirmRequired: {
          confirm_token: "inactive",
          preview: {
            ...pausedPreview,
            new_access: null,
            inactive_main_account,
          },
        },
      });
      await clickButton("Visa vad kopplingen ger");
      expect(
        await screen.findByText(
          "Åtkomsten börjar när medlemskapet blir aktivt.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/genast ge hushållet/)).not.toBeInTheDocument();
    },
  );

  it("shows which rights a main account with administrative access already has", async () => {
    fireEvent.click(await chooseBank());
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: {
        confirm_token: "manager",
        preview: {
          ...preview,
          new_access: {
            id: 46,
            username: "ansvarig",
            already_edits: false,
            already_manages: true,
          },
        },
      },
    });
    await clickButton("Visa vad kopplingen ger");
    expect(
      await screen.findByText(
        /ansvarig.*innehavare.*redan ändra, sälja och flytta kaniner/,
      ),
    ).toHaveTextContent(ownerRights);
  });

  it("identifies an inactive main account even when a family member gains read access", async () => {
    fireEvent.click(await chooseBank());
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: {
        confirm_token: "inactive-account",
        preview: {
          ...preview,
          new_access: null,
          inactive_main_account: { id: 41, username: "vilande" },
        },
      },
    });
    await clickButton("Visa vad kopplingen ger");
    expect(
      await screen.findByText(/Huvudmedlemmens konto vilande är inaktivt/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/laskonto.*läsa matrikelns kontaktuppgifter/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Inget konto får ny åtkomst/),
    ).not.toBeInTheDocument();
  });

  it("keeps the choice and confirmation on retryable errors and clears old errors on retry", async () => {
    fireEvent.click(await chooseBank());
    link.mockRejectedValueOnce(new Error("Failed to fetch"));
    await clickButton("Visa vad kopplingen ger");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kunde inte nå servern",
    );
    expect(screen.getByRole("radio", { name: /G12/ })).toBeChecked();
    const error = { ok: false, error: "Försök igen", resetSelection: false };
    link.mockResolvedValueOnce(error);
    await clickButton("Visa vad kopplingen ger");
    expect(await screen.findByText("Försök igen")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByRole("radio", { name: /G12/ })).toBeChecked();
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: { preview, confirm_token: "first" },
    });
    await clickButton("Visa vad kopplingen ger");
    await screen.findByRole("button", { name: "Koppla" });
    expect(screen.queryByText("Försök igen")).not.toBeInTheDocument();
    link.mockResolvedValueOnce(error);
    await clickButton("Koppla");
    expect(await screen.findByText("Försök igen")).toHaveAttribute(
      "role",
      "alert",
    );
    link.mockResolvedValueOnce({ ok: true });
    await clickButton("Koppla");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(link).toHaveBeenLastCalledWith(3, 8, "first");
  });

  it("returns to the bank when the selected herd becomes unavailable", async () => {
    fireEvent.click(await chooseBank());
    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: { preview, confirm_token: "first" },
    });
    await clickButton("Visa vad kopplingen ger");
    await screen.findByRole("button", { name: "Koppla" });
    link.mockResolvedValueOnce({
      ok: false,
      error: "Redan kopplad",
      resetSelection: true,
    });
    await clickButton("Koppla");
    expect(await screen.findByRole("alert")).toHaveTextContent("Redan kopplad");
    expect(screen.getByLabelText("Genbank")).toHaveValue("");
    expect(button("Visa vad kopplingen ger")).toBeDisabled();
  });
});
