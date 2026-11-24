import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
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
  new_access: { id: 41, username: "testkonto" },
  legacy_owners: [{ id: 42, username: "tidigare", in_membership: false }],
  contact_rows: [
    {
      field: "email",
      label: "E-post",
      case: "lika",
      effect: "Besättningens kopia töms.",
    },
  ],
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

describe("KopplaBesattningDialog", () => {
  it("filters by number, marks inactive herds and prevents selecting a linked herd", async () => {
    const candidate = await chooseBank();
    expect(candidate).toHaveAccessibleName(/Inaktiv/);
    expect(screen.getByRole("radio", { name: /G25.*27/ })).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: /G26.*detta medlemskap/ }),
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
    fireEvent.click(button("Visa vad kopplingen ger"));
    expect(await screen.findByText(/testkonto/)).toBeInTheDocument();
    expect(
      screen.getByText(/tidigare.*saknar aktiv person i medlemskapet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Besättningens kopia töms/)).toBeInTheDocument();
    expect(link).toHaveBeenCalledWith(3, 8, undefined);

    link.mockResolvedValueOnce({
      ok: false,
      confirmRequired: {
        preview: { ...preview, new_access: { id: 43, username: "nyttkonto" } },
        confirm_token: "next",
      },
    });
    fireEvent.click(button("Koppla"));
    expect(
      await screen.findByText(/Underlaget har ändrats/),
    ).toBeInTheDocument();
    expect(screen.getByText(/nyttkonto/)).toBeInTheDocument();
    expect(screen.queryByText(/testkonto/)).not.toBeInTheDocument();
    expect(link).toHaveBeenLastCalledWith(3, 8, "first");
    expect(snackbar).not.toHaveBeenCalled();

    link.mockResolvedValueOnce({ ok: true });
    fireEvent.click(button("Koppla"));
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
        preview: {
          ...preview,
          membership: { ...preview.membership, membership_status: "inactive" },
          new_access: null,
          contact_rows: null,
        },
      },
    });
    fireEvent.click(button("Visa vad kopplingen ger"));
    expect(
      await screen.findByText(/åtkomst först när medlemskapet blir aktivt/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/jämförs när medlemskapet blir aktivt/i),
    ).toBeInTheDocument();
    fireEvent.click(button("Avbryt"));
    expect(link).toHaveBeenCalledTimes(1);
    fireEvent.click(button("Koppla besättning"));
    await screen.findByRole("option", { name: "Gotland" });
    expect(
      screen.queryByRole("button", { name: "Koppla" }),
    ).not.toBeInTheDocument();
  });
});
