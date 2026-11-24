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

const { updateHerd, refresh, showSnackbar, addNotification } = vi.hoisted(
  () => ({
    updateHerd: vi.fn(),
    refresh: vi.fn(),
    showSnackbar: vi.fn(),
    addNotification: vi.fn(),
  }),
);
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  updateHerd,
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification }),
}));

import BesattningCard from "@/app/(app)/stamboken/(dashboard)/min-besattning/BesattningCard";
import { CONFLICT_TEXT } from "@/components/herd-contact/contactTypes";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const herd = (over: Record<string, unknown> = {}) => ({
  herd: "G1274",
  herd_name: "Exempelgården",
  location: "Roma",
  location_privacy: "authenticated",
  wire_phone: "0498-11 11 11",
  wire_phone_privacy: null, // stored NULL: shown and sent as private
  www: "exempelgarden.invalid",
  www_privacy: "public",
  ...over,
});

const edit = () =>
  fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));

describe("BesattningCard place fields", () => {
  it("a privacy change sends what the form showed of the row", async () => {
    updateHerd.mockResolvedValue({ success: true, data: {} });
    render(<BesattningCard herd={herd()} herdNumber="G1274" />);
    edit();
    const chips = screen.getByRole("group", {
      name: "Vem ser fasta telefonen",
    });
    fireEvent.click(
      within(chips).getByRole("button", { name: "Inloggade besättningar" }),
    );
    save();
    await waitFor(() => expect(updateHerd).toHaveBeenCalledTimes(1));
    expect(updateHerd.mock.calls[0]).toStrictEqual([
      "G1274",
      {
        wire_phone_privacy: "authenticated",
        place_shown: {
          wire_phone: { value: "0498-11 11 11", privacy: "private" },
        },
      },
    ]);
  });

  it("a changed website or place is sent with the row it replaces; the name needs none", async () => {
    updateHerd.mockResolvedValue({ success: true, data: {} });
    render(<BesattningCard herd={herd()} herdNumber="G1274" />);
    edit();
    fireEvent.change(screen.getByRole("textbox", { name: "Hemsida" }), {
      target: { value: "" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Besättningens namn" }),
      { target: { value: "Nya gården" } },
    );
    save();
    await waitFor(() => expect(updateHerd).toHaveBeenCalledTimes(1));
    expect(updateHerd.mock.calls[0][1]).toStrictEqual({
      herd_name: "Nya gården",
      www: null,
      place_shown: {
        www: { value: "exempelgarden.invalid", privacy: "public" },
      },
    });
    cleanup();
    vi.clearAllMocks();
    updateHerd.mockResolvedValue({ success: true, data: {} });
    render(<BesattningCard herd={herd()} herdNumber="G1274" />);
    edit();
    fireEvent.change(screen.getByRole("textbox", { name: "Ort" }), {
      target: { value: "Visby" },
    });
    save();
    await waitFor(() => expect(updateHerd).toHaveBeenCalledTimes(1));
    expect(updateHerd.mock.calls[0][1]).toStrictEqual({
      location: "Visby",
      place_shown: { location: { value: "Roma", privacy: "authenticated" } },
    });
  });

  it("an unknown stored privacy is shown and sent as private", async () => {
    updateHerd.mockResolvedValue({ success: true, data: {} });
    render(
      <BesattningCard
        herd={herd({ www_privacy: "Public " })}
        herdNumber="G1274"
      />,
    );
    edit();
    const chips = screen.getByRole("group", { name: "Vem ser hemsidan" });
    expect(
      within(chips).getByRole("button", { name: "Endast genbanksansvarig" }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      within(chips).getByRole("button", { name: "Inloggade besättningar" }),
    );
    save();
    await waitFor(() => expect(updateHerd).toHaveBeenCalledTimes(1));
    expect(updateHerd.mock.calls[0][1]).toStrictEqual({
      www_privacy: "authenticated",
      place_shown: {
        www: { value: "exempelgarden.invalid", privacy: "private" },
      },
    });
  });

  it("a 409 reloads the herd and the form follows the new data", async () => {
    updateHerd.mockResolvedValue({
      success: false,
      error: "Kontaktuppgifterna har ändrats sedan sidan öppnades.",
      status: 409,
      type: "contact-changed",
    });
    const { rerender } = render(
      <BesattningCard herd={herd()} herdNumber="G1274" />,
    );
    edit();
    const chips = screen.getByRole("group", {
      name: "Vem ser fasta telefonen",
    });
    fireEvent.click(
      within(chips).getByRole("button", { name: "Inloggade besättningar" }),
    );
    save();
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(addNotification).toHaveBeenCalledWith(
      expect.objectContaining({ message: CONFLICT_TEXT, type: "error" }),
    );
    // the number an admin set meanwhile, private: the form shows it, with its own privacy
    rerender(
      <BesattningCard
        herd={herd({ wire_phone: "0498-22 22 22" })}
        herdNumber="G1274"
      />,
    );
    expect(screen.getByRole("textbox", { name: "Fast telefon" })).toHaveValue(
      "0498-22 22 22",
    );
    const fresh = screen.getByRole("group", {
      name: "Vem ser fasta telefonen",
    });
    expect(
      within(fresh).getByRole("button", { name: "Endast genbanksansvarig" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
