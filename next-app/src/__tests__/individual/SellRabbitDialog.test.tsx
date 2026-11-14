import React from "react";
import { describe, it, expect, afterEach, vi, beforeAll } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { SellRabbitDialog } from "@/components/individual/SellRabbitDialog";
import type { GenebankHerd } from "@/utils/saleRules";

beforeAll(async () => {
  await import("@/i18n");
});

afterEach(cleanup);

const HERDS: GenebankHerd[] = [
  { herd: "G1", herd_name: "Egna", is_active: true },
  { herd: "G2", herd_name: "Grannen", is_active: true },
  { herd: "GX1", herd_name: null, is_active: true },
];

function dialog(
  props: Partial<React.ComponentProps<typeof SellRabbitDialog>> = {},
) {
  return (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <SellRabbitDialog
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        loadHerds={async () => ({ success: true as const, herds: HERDS })}
        individualName="Majken"
        individualNumber="G1-2111"
        currentHerd={{ herd: "G1", herd_name: "Egna" }}
        birthDate="2021-02-01"
        herdTracking={[{ date: "2021-02-01" }]}
        isRegistered
        isSaving={false}
        {...props}
      />
    </LocalizationProvider>
  );
}

function renderDialog(isRegistered: boolean, onConfirm = vi.fn()) {
  render(dialog({ isRegistered, onConfirm }));
  return onConfirm;
}

async function openHerdOptions() {
  const input = screen.getByRole("combobox");
  fireEvent.mouseDown(input);
  return screen.findAllByRole("option");
}

describe("SellRabbitDialog", () => {
  it("shows the title and offers other herds, not the current one", async () => {
    renderDialog(true);
    expect(screen.getByText("Sälj Majken")).toBeTruthy();
    const options = await openHerdOptions();
    expect(options.map((o) => o.textContent)).toEqual([
      "GX1 – Utanför genbanken",
      "G2 – Grannen",
    ]);
  });

  it("limits an unregistered rabbit to the outside-genebank herd", async () => {
    renderDialog(false);
    const options = await openHerdOptions();
    expect(options.map((o) => o.textContent)).toEqual([
      "GX1 – Utanför genbanken",
    ]);
  });

  it("submits herd and ISO date after choosing a herd and acknowledging", async () => {
    const onConfirm = renderDialog(true);
    const options = await openHerdOptions();
    fireEvent.click(options[1]);
    const confirm = screen.getByRole("button", {
      name: "Bekräfta försäljning",
    });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() =>
      expect((confirm as HTMLButtonElement).disabled).toBe(false),
    );
    expect(screen.getByTestId("sell-summary").textContent).toContain(
      "G2 – Grannen",
    );
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toBe("G2");
    expect(onConfirm.mock.calls[0][1]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  describe("buyer outside the association", () => {
    const CONSENT =
      "Köparen har kryssat ja: föreningen får spara adress, e-post och telefon så länge köparen har kaninen";
    const OPTIN =
      "Köparen har kryssat ja: föreningen får kontakta köparen om medlemskap";

    async function chooseOutside(onConfirm = vi.fn()) {
      render(dialog({ onConfirm }));
      const options = await openHerdOptions();
      fireEvent.click(options[0]); // GX1
      return onConfirm;
    }
    const type = (label: RegExp, value: string) =>
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    const confirmButton = () =>
      screen.getByRole("button", {
        name: "Bekräfta försäljning",
      }) as HTMLButtonElement;
    const acknowledge = () =>
      fireEvent.click(
        screen.getByRole("checkbox", { name: /Jag har tagit del/ }),
      );

    it("asks for name and town only for the outside herd", async () => {
      render(dialog());
      const options = await openHerdOptions();
      fireEvent.click(options[1]); // G2
      expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
      fireEvent.mouseDown(screen.getByRole("combobox"));
      fireEvent.click((await screen.findAllByRole("option"))[0]);
      expect(screen.getByLabelText(/Köparens namn/)).toBeTruthy();
      expect(screen.getByLabelText(/^Ort/)).toBeTruthy();
      expect(
        screen.getByText(
          "Ge köparen överlåtelsebeviset. Där står föreningens information till köparen.",
        ),
      ).toBeTruthy();
    });

    it("requires name and town before the sale can be confirmed", async () => {
      await chooseOutside();
      acknowledge();
      expect(confirmButton().disabled).toBe(true);
      type(/Köparens namn/, "Anna Köpare");
      expect(confirmButton().disabled).toBe(true);
      type(/^Ort/, "Visby");
      await waitFor(() => expect(confirmButton().disabled).toBe(false));
    });

    it("shows the contact fields only after the matching yes", async () => {
      await chooseOutside();
      const shown = () =>
        ["Postadress", "E-post", "Telefon"].filter(
          (label) => screen.queryByLabelText(label) !== null,
        );
      expect(shown()).toEqual([]);
      fireEvent.click(screen.getByRole("checkbox", { name: OPTIN }));
      expect(shown()).toEqual(["E-post", "Telefon"]);
      fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
      expect(shown()).toEqual(["Postadress", "E-post", "Telefon"]);
    });

    it("sends the buyer, without fields hidden by an unticked box", async () => {
      const onConfirm = await chooseOutside();
      type(/Köparens namn/, " Anna Köpare ");
      type(/^Ort/, "Visby");
      fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
      type(/Postadress/, "Väg 1");
      type(/E-post/, "anna@example.org");
      fireEvent.click(screen.getByRole("checkbox", { name: CONSENT })); // takes it back
      fireEvent.click(screen.getByRole("checkbox", { name: OPTIN }));
      acknowledge();
      await waitFor(() => expect(confirmButton().disabled).toBe(false));
      fireEvent.click(confirmButton());
      expect(onConfirm).toHaveBeenCalledWith("GX1", expect.any(String), {
        name: "Anna Köpare",
        town: "Visby",
        contact_consent: false,
        membership_optin: true,
        email: "anna@example.org",
      });
    });

    it("offers GX1 again for a rabbit already in GX1", async () => {
      render(dialog({ currentHerd: { herd: "GX1", herd_name: null } }));
      const options = await openHerdOptions();
      expect(options[0].textContent).toBe("GX1 – Utanför genbanken");
    });
  });

  it("starts from a clean slate on every opening", async () => {
    const { rerender } = render(dialog());
    const options = await openHerdOptions();
    fireEvent.click(options[1]);
    fireEvent.click(screen.getByRole("checkbox"));
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
      "G2 – Grannen",
    );
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      true,
    );

    rerender(dialog({ open: false }));
    rerender(dialog({ open: true }));

    await waitFor(() =>
      expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(""),
    );
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      false,
    );
  });

  it("closes on Escape when idle", () => {
    const onClose = vi.fn();
    render(dialog({ onClose }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and backdrop clicks while saving", () => {
    const onClose = vi.fn();
    render(dialog({ onClose, isSaving: true }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    const backdrop = document.querySelector(".MuiBackdrop-root");
    expect(backdrop).toBeTruthy();
    fireEvent.mouseDown(backdrop!);
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows the problem detail inline as an alert", () => {
    render(dialog({ error: "Individen finns redan i den besättningen." }));
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Individen finns redan");
  });

  it("shows no error alert by default", () => {
    render(dialog());
    expect(screen.queryByTestId("sell-error")).toBeNull();
  });

  describe("Idag action", () => {
    const originalTz = process.env.TZ;

    afterEach(() => {
      vi.useRealTimers();
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    });

    it("selects today in Stockholm, not in the browser's timezone", async () => {
      // 17:00Z = 2026-10-01 19:00 in Stockholm but already 2026-10-02 in Kiritimati (UTC+14).
      process.env.TZ = "Pacific/Kiritimati";
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date("2026-10-01T17:00:00Z"));
      expect(new Date().getDate()).toBe(2);

      const onConfirm = renderDialog(true);
      const openPicker = () =>
        fireEvent.click(screen.getByRole("button", { name: /choose date/i }));

      // Move off today first, so the Idag click is what selects it.
      openPicker();
      fireEvent.click(
        await screen.findByRole("button", { name: /previous month/i }),
      );
      // The month slide can render both months for a while (slow under
      // load); October 15 is in the future and disabled, so pick the enabled
      // 15th — September's.
      const fifteenth = await waitFor(() => {
        const day = screen
          .getAllByRole("gridcell", { name: "15" })
          .find((el) => !(el as HTMLButtonElement).disabled);
        expect(day).toBeDefined();
        return day as HTMLElement;
      });
      fireEvent.click(fifteenth);
      await waitFor(
        () => expect(screen.queryByRole("gridcell", { name: "15" })).toBeNull(),
        { timeout: 10_000 },
      );

      openPicker();
      fireEvent.click(
        await screen.findByRole("button", { name: /idag|today/i }),
      );

      const options = await openHerdOptions();
      fireEvent.click(options[1]);
      fireEvent.click(screen.getByRole("checkbox"));
      const confirm = screen.getByRole("button", {
        name: "Bekräfta försäljning",
      });
      await waitFor(() =>
        expect((confirm as HTMLButtonElement).disabled).toBe(false),
      );
      fireEvent.click(confirm);
      expect(onConfirm).toHaveBeenCalledWith("G2", "2026-10-01");
    }, 20_000); // full MUI picker interaction; slow under a parallel run
  });
});
