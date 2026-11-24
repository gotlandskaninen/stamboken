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

const updateHerd = vi.hoisted(() => vi.fn());
const saveHerdContact = vi.hoisted(() => vi.fn());
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/besattningar/actions", () => ({
  updateHerd,
  saveHerdContact,
}));

import { HerdEditClient } from "@/app/(app)/stamboken/(dashboard)/admin/besattningar/[herdId]/HerdEditClient";
import type { HerdDetail } from "@/app/(app)/stamboken/(dashboard)/admin/besattningar/[herdId]/page";
import {
  CONFLICT_TEXT,
  type ReaderContact,
} from "@/components/herd-contact/contactTypes";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const persons = [
  { id: 1, name: "Anna Exempel", role: "huvudmedlem" },
  { id: 2, name: "Ida Exempel", role: "familjemedlem" },
];
const row = (
  source: "egen" | "person" | "medlemskap",
  privacy = "private",
) => ({
  source,
  privacy: privacy as "private",
  pending: false,
  alternative: null,
});
const contact = (over: Partial<ReaderContact> = {}): ReaderContact => ({
  mode: "person",
  contact_member: persons[0],
  persons,
  rows: {
    name: row("person"),
    email: row("person"),
    mobile_phone: row("egen"),
    physical_address: row("medlemskap"),
  },
  ...over,
});
const herd = (over: Partial<HerdDetail> = {}): HerdDetail => ({
  id: 5,
  herd: "G1274",
  herd_name: "Exempelgården",
  name: "Anna Exempel",
  name_privacy: "private",
  physical_address: "Byvägen 1|623 00|Roma",
  email: "anna@example.invalid",
  mobile_phone: "070-000 00 00",
  wire_phone: null,
  www: null,
  is_active: true,
  genebank_id: 1,
  genebank_name: "Gotlandskaninen",
  owners: [],
  contact: contact(),
  ...over,
});

describe("HerdEditClient contact", () => {
  it("admin edit shows the two parts and sends contact patch", async () => {
    saveHerdContact.mockResolvedValue({ success: true });
    render(<HerdEditClient herd={herd()} />);
    expect(screen.getByText("Från ditt medlemskap")).toBeInTheDocument();
    expect(screen.getByText("Egna för besättningen")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Redigera kontakt" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-222 22 22" },
    });
    const form = screen
      .getByRole("textbox", { name: "Mobil" })
      .closest("form")!;
    fireEvent.click(within(form).getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(saveHerdContact).toHaveBeenCalledTimes(1));
    expect(saveHerdContact).toHaveBeenCalledWith("G1274", {
      contact: expect.objectContaining({
        rows: {
          mobile_phone: expect.objectContaining({
            source: "egen",
            value: "070-222 22 22",
          }),
        },
      }),
    });
    expect(updateHerd).not.toHaveBeenCalled();
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("admin shows missing contact", () => {
    render(
      <HerdEditClient
        herd={herd({
          name: null,
          email: null,
          mobile_phone: null,
          physical_address: null,
          contact: contact({ mode: "ingen", contact_member: null }),
        })}
      />,
    );
    expect(screen.getByText("Kontakt saknas")).toBeInTheDocument();
  });

  it("the other fields save without contact keys", async () => {
    updateHerd.mockResolvedValue(undefined);
    render(<HerdEditClient herd={herd()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "https://example.invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateHerd).toHaveBeenCalled());
    expect(updateHerd).toHaveBeenCalledWith("G1274", {
      www: "https://example.invalid",
      place_shown: { www: { value: null } },
    });
  });

  it("a phone erased after the form opened is not written back", async () => {
    updateHerd.mockResolvedValue(undefined);
    const { rerender } = render(
      <HerdEditClient herd={herd({ wire_phone: "0498-12 34 56" })} />,
    );
    rerender(<HerdEditClient herd={herd({ wire_phone: null })} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "https://example.invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateHerd).toHaveBeenCalled());
    expect(updateHerd.mock.calls[0][1]).toStrictEqual({
      www: "https://example.invalid",
      place_shown: { www: { value: null } },
    });
  });

  it("a changed phone is sent with the number the form showed", async () => {
    updateHerd.mockResolvedValue(undefined);
    render(<HerdEditClient herd={herd({ wire_phone: "0498-12 34 56" })} />);
    fireEvent.change(
      screen.getByRole("textbox", { name: "Fast telefonnummer" }),
      { target: { value: "0498-99 99 99" } },
    );
    fireEvent.click(screen.getByLabelText("Besättningen är aktiv"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateHerd).toHaveBeenCalled());
    expect(updateHerd.mock.calls[0][1]).toStrictEqual({
      wire_phone: "0498-99 99 99",
      is_active: false,
      place_shown: { wire_phone: { value: "0498-12 34 56" } },
    });
  });

  it("a 409 shows the conflict and the form follows the reloaded herd", async () => {
    updateHerd.mockResolvedValueOnce({
      error: "Kontaktuppgifterna har ändrats sedan sidan öppnades.",
      status: 409,
      type: "contact-changed",
    });
    const { rerender } = render(
      <HerdEditClient herd={herd({ wire_phone: "0498-12 34 56" })} />,
    );
    const phone = () =>
      screen.getByRole("textbox", { name: "Fast telefonnummer" });
    fireEvent.change(phone(), { target: { value: "0498-99 99 99" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(CONFLICT_TEXT);
    expect(refresh).toHaveBeenCalledTimes(1);
    // the number was erased meanwhile: the reloaded form starts from the stored row
    rerender(<HerdEditClient herd={herd({ wire_phone: null })} />);
    expect(phone()).toHaveValue("");
    updateHerd.mockResolvedValueOnce(undefined);
    fireEvent.change(phone(), { target: { value: "0498-99 99 99" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateHerd).toHaveBeenCalledTimes(2));
    expect(updateHerd.mock.calls[1][1]).toStrictEqual({
      wire_phone: "0498-99 99 99",
      place_shown: { wire_phone: { value: null } },
    });
  });

  it("the page's Spara is disabled while the contact editor is open", () => {
    render(<HerdEditClient herd={herd()} />);
    const page = screen.getByRole("button", { name: "Spara" });
    expect(page).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Redigera kontakt" }));
    const form = screen
      .getByRole("textbox", { name: "Mobil" })
      .closest("form")!;
    const all = screen.getAllByRole("button", { name: "Spara" });
    const outside = all.filter((b) => !form.contains(b));
    expect(outside).toHaveLength(1);
    expect(outside[0]).toBeDisabled();
  });

  it("shows missing contact for a kept fritext name without persons", () => {
    const fritext = contact({
      mode: "fritext",
      contact_member: null,
      persons: [],
    });
    render(<HerdEditClient herd={herd({ contact: fritext })} />);
    expect(screen.getByText("Kontakt saknas")).toBeInTheDocument();
    cleanup();
    render(<HerdEditClient herd={herd()} />);
    expect(screen.queryByText("Kontakt saknas")).toBeNull();
  });

  it("a failed save keeps the draft and allows a retry", async () => {
    saveHerdContact
      .mockResolvedValueOnce({
        success: false,
        error: "Kunde inte nå servern. Försök igen.",
      })
      .mockResolvedValueOnce({ success: true });
    render(<HerdEditClient herd={herd()} />);
    fireEvent.click(screen.getByRole("button", { name: "Redigera kontakt" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-222 22 22" },
    });
    const form = screen
      .getByRole("textbox", { name: "Mobil" })
      .closest("form")!;
    fireEvent.click(within(form).getByRole("button", { name: "Spara" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("textbox", { name: "Mobil" })).toHaveValue(
      "070-222 22 22",
    );
    fireEvent.click(within(form).getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(saveHerdContact).toHaveBeenCalledTimes(2));
  });

  it("the contact editor cannot be opened while the page save is pending", async () => {
    let done!: () => void;
    updateHerd.mockReturnValue(new Promise<void>((r) => (done = r)));
    render(<HerdEditClient herd={herd()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "https://example.invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateHerd).toHaveBeenCalled());
    const edit = screen.getByRole("button", { name: "Redigera kontakt" });
    expect((edit as HTMLButtonElement).disabled).toBe(true);
    done();
    await waitFor(() =>
      expect((edit as HTMLButtonElement).disabled).toBe(false),
    );
  });

  const asking = () =>
    herd({
      contact: contact({
        rows: {
          ...contact().rows,
          mobile_phone: {
            ...row("egen"),
            pending: true,
            alternative: "070-111 11 11",
          },
        },
      }),
    });
  const btn = (n: string) =>
    screen.getByRole("button", { name: n }) as HTMLButtonElement;

  it("the answer buttons wait while the page saves", async () => {
    let done!: () => void;
    updateHerd.mockReturnValue(new Promise<void>((r) => (done = r)));
    render(<HerdEditClient herd={asking()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "https://example.invalid" },
    });
    fireEvent.click(btn("Spara"));
    await waitFor(() => expect(updateHerd).toHaveBeenCalled());
    expect(btn("Ja, behåll").disabled).toBe(true);
    fireEvent.click(btn("Ja, behåll"));
    expect(saveHerdContact).not.toHaveBeenCalled();
    done();
    await waitFor(() => expect(btn("Ja, behåll").disabled).toBe(false));
  });

  it("the page Spara waits while an answer is pending", async () => {
    let done!: (r: { success: true }) => void;
    saveHerdContact.mockReturnValue(new Promise((r) => (done = r)));
    render(<HerdEditClient herd={asking()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "https://example.invalid" },
    });
    fireEvent.click(btn("Ja, behåll"));
    await waitFor(() => expect(saveHerdContact).toHaveBeenCalled());
    expect(btn("Spara").disabled).toBe(true);
    expect(btn("Redigera kontakt").disabled).toBe(true);
    fireEvent.click(btn("Spara"));
    expect(updateHerd).not.toHaveBeenCalled();
    done({ success: true });
    await waitFor(() => expect(btn("Spara").disabled).toBe(false));
  });
});
