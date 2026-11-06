import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import "@/i18n";
import { RegisterRabbitDialog } from "@/components/herd/RegisterRabbitDialog";

const { registerIndividual, suggestIndividualNumber, checkIndividualNumber } =
  vi.hoisted(() => ({
    registerIndividual: vi.fn(),
    suggestIndividualNumber: vi.fn(),
    checkIndividualNumber: vi.fn(),
  }));

vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  registerIndividual,
  suggestIndividualNumber,
  checkIndividualNumber,
}));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

const parent = (number: string, name: string, sex: string) => ({
  number,
  name,
  sex,
  birth_date: null,
  status: "active",
  herd: "G1",
  color: null,
  has_photo: false,
  litter_size: null,
  litter_size6w: null,
  mother_number: null,
  mother_name: null,
  father_number: null,
  father_name: null,
});

// The parent pickers' search: one doe, one buck
vi.mock("@/redux/api/apiSlice", async () => {
  const actual = await vi.importActual("@/redux/api/apiSlice");
  return {
    ...actual,
    useFetchIndividualsQuery: ({ sex }: { sex: string }) => ({
      data: {
        items: [
          sex === "female"
            ? parent("G1-1911", "Saga", "female")
            : parent("G2-1711", "Storm", "male"),
        ],
      },
      isFetching: false,
    }),
  };
});

const suggestion = {
  suggested: "G1-2511",
  suggested_position: 1,
  used_positions: [],
  available_positions: [1, 2, 3, 4, 5, 6, 7, 8, 9],
  current_count: 0,
  max_count: 9,
  limited_by: "ceiling",
  can_register: true,
  certified_count: 0,
  certified_max_count: null,
  past_6w: true,
  can_issue_certificate: false,
  certificate_blocked_reason: "litter_size6w_required",
  breeding_id: null,
  litter_number: 1,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// The dialog's selects have no accessible name: find one by the value it shows
const selectShowing = (text: string) =>
  screen.getAllByRole("combobox").find((c) => c.textContent === text);

function pick(label: RegExp, option: RegExp) {
  const input = screen.getByRole("combobox", { name: label });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: option }));
}

describe("RegisterRabbitDialog without a litter (Lägg till kanin)", () => {
  it("asks for the litter, defaults to digital and sends no breeding_id", async () => {
    suggestIndividualNumber.mockResolvedValue({
      success: true,
      data: suggestion,
    });
    registerIndividual.mockResolvedValue({
      success: true,
      data: {
        individual: { number: "G1-2511", name: null },
        certificate: "100500",
        certificate_error: null,
      },
    });
    render(
      <RegisterRabbitDialog
        open
        onClose={() => {}}
        herdId="G1"
        genebankId={1}
      />,
    );

    expect(
      screen.getByRole("dialog", { name: "Lägg till kanin" }),
    ).toBeDefined();
    expect(screen.getByRole("group", { name: /Födelsedatum/ })).toBeDefined();
    expect(selectShowing("Digitalt")).toBeDefined();

    pick(/^Mor/, /Saga/);
    pick(/^Far/, /Storm/);
    const birth = screen
      .getByRole("group", { name: /Födelsedatum/ })
      .parentElement!.querySelector("input")!;
    fireEvent.change(birth, { target: { value: "2025-05-10" } });

    await waitFor(() =>
      expect(suggestIndividualNumber).toHaveBeenCalledWith({
        mother: "G1-1911",
        father: "G2-1711",
        birth_date: "2025-05-10",
      }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Registrera kanin — G1-2511" }),
    ).toBeDefined();

    fireEvent.change(screen.getByRole("spinbutton", { name: /Antal födda/ }), {
      target: { value: "5" },
    });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: /Levande i kullen/ }),
      { target: { value: "4" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: /^Färg(\s*\*)?$/ }), {
      target: { value: "Viltgrå" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Registrera" }));

    await waitFor(() => expect(registerIndividual).toHaveBeenCalledOnce());
    const payload = registerIndividual.mock.calls[0][0];
    expect(payload).not.toHaveProperty("breeding_id");
    expect(payload).toMatchObject({
      mother: "G1-1911",
      father: "G2-1711",
      birth_date: "2025-05-10",
      litter_size: 5,
      litter_size6w: 4,
      certificate_type: "digital",
    });
    const certificate = await screen.findByRole("link", { name: "Visa intyg" });
    expect(certificate.getAttribute("href")).toBe(
      "/api/v2/certificates/G1-2511",
    );
  }, 20000); // the full MUI dialog renders slowly under the parallel suite

  it("reaches the conflict when the new litter is born before a numbered one", async () => {
    // No number to suggest (409 litter_order_conflict); the paper's dry run says why
    suggestIndividualNumber.mockResolvedValue({
      success: false,
      error: "Kullen är född före en kull som redan har kullnummer det året.",
      errorTitle: "litter_order_conflict",
    });
    const litterOrder = {
      stamboken_number: null,
      paper_number: "G1-2511",
      status: "conflict",
      conflicts: [
        {
          kind: "litter_order",
          paper: "1",
          stamboken: null,
          holder: {
            number: "G1-2511",
            herd: "G1",
            breeding_id: 3,
            litter_number: 1,
            litter: "född 2025-08-01",
          },
        },
      ],
      choices: ["paper_is_right"],
      actions: [
        {
          kind: "litter_order",
          text: "Kullen är född före kull 1 som redan har nummer.",
          self_service: "/stamboken/min-besattning?herd=G1&tab=breeding",
          manager_message:
            "Pappersintyget säger G1-2511, Stamboken ger inget nummer.",
        },
      ],
    };
    checkIndividualNumber.mockResolvedValue({
      success: true,
      data: litterOrder,
    });
    registerIndividual.mockResolvedValue({
      success: false,
      error: "Individnumret på pappersintyget stämmer inte med Stambokens.",
      numberCheck: litterOrder,
    });
    render(
      <RegisterRabbitDialog
        open
        onClose={() => {}}
        herdId="G1"
        genebankId={1}
      />,
    );
    pick(/^Mor/, /Saga/);
    pick(/^Far/, /Storm/);
    const birth = screen
      .getByRole("group", { name: /Födelsedatum/ })
      .parentElement!.querySelector("input")!;
    fireEvent.change(birth, { target: { value: "2025-05-10" } });
    await waitFor(() => expect(suggestIndividualNumber).toHaveBeenCalled());
    fireEvent.change(screen.getByRole("spinbutton", { name: /Antal födda/ }), {
      target: { value: "5" },
    });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: /Levande i kullen/ }),
      { target: { value: "4" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: /^Färg(\s*\*)?$/ }), {
      target: { value: "Viltgrå" },
    });
    fireEvent.mouseDown(selectShowing("Digitalt")!);
    fireEvent.click(
      within(screen.getByRole("listbox")).getByRole("option", {
        name: /Papper/,
      }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: /^Intygsnummer/ }), {
      target: { value: "P-77" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: /^Individnummer på pappret/ }),
      { target: { value: "G1-2511" } },
    );
    await waitFor(() => expect(checkIndividualNumber).toHaveBeenCalled());
    const save = screen.getByRole("button", { name: "Registrera" });
    await waitFor(() =>
      expect((save as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(save);
    const conflict = await screen.findByRole("dialog", {
      name: "Individnumret på pappret stämmer inte med Stamboken",
    });
    expect(
      within(conflict).queryByRole("button", { name: "Pappret rättas" }),
    ).toBeNull();
    expect(
      within(conflict).getByRole("button", { name: "Pappret stämmer" }),
    ).toBeDefined();
  }, 20000);

  it("keeps the litter-row mode on paper with digital disabled", async () => {
    suggestIndividualNumber.mockResolvedValue({
      success: true,
      data: { ...suggestion, breeding_id: 4 },
    });
    render(
      <RegisterRabbitDialog
        open
        onClose={() => {}}
        herdId="G1"
        breeding={{ id: 4, birth_date: "2025-05-10", litter_number: 1 }}
      />,
    );
    await waitFor(() =>
      expect(suggestIndividualNumber).toHaveBeenCalledWith(4),
    );
    expect(screen.queryByRole("combobox", { name: /^Mor/ })).toBeNull();
    const select = selectShowing("Papper");
    expect(select).toBeDefined();
    fireEvent.mouseDown(select!);
    const digital = within(screen.getByRole("listbox")).getByRole("option", {
      name: /Digitalt/,
    });
    expect(digital.getAttribute("aria-disabled")).toBe("true");
  });
});

// The paper says kull 1, Stamboken kull 2 (spec 2026-10-30)
const conflictCheck = {
  stamboken_number: "G1-2522",
  paper_number: "G1-2512",
  status: "conflict",
  conflicts: [
    {
      kind: "litter",
      paper: "1",
      stamboken: "2",
      holder: {
        number: "G1-2511",
        herd: "G1",
        breeding_id: 3,
        litter_number: 1,
        litter: "parning 2025-03-03, född 2025-04-03",
      },
    },
  ],
  choices: ["use_stamboken_number", "paper_is_right"],
  actions: [
    {
      kind: "litter",
      text: "Kull 1 år 2025 är kullen parning 2025-03-03, född 2025-04-03 (G1-2511…).",
      self_service: "/stamboken/min-besattning?herd=G1&tab=breeding",
      manager_message: "Pappersintyget säger G1-2512, Stamboken ger G1-2522.",
    },
  ],
};

describe("RegisterRabbitDialog with a paper certificate", () => {
  it("shows Stamboken's number for a zero-padded paper number", async () => {
    suggestIndividualNumber.mockResolvedValue({
      success: true,
      data: {
        ...suggestion,
        breeding_id: 4,
        can_issue_certificate: true,
        certificate_blocked_reason: null,
      },
    });
    // The server answers with the canonical form of what was typed
    checkIndividualNumber.mockResolvedValue({
      success: true,
      data: {
        stamboken_number: "G1-2512",
        paper_number: "G1-2512",
        status: "match",
        conflicts: [],
        choices: [],
        actions: [],
      },
    });
    render(
      <RegisterRabbitDialog
        open
        onClose={() => {}}
        herdId="G1"
        breeding={{
          id: 4,
          birth_date: "2025-05-10",
          litter_number: 1,
          litter_size6w: 4,
        }}
      />,
    );
    await waitFor(() => expect(suggestIndividualNumber).toHaveBeenCalled());
    fireEvent.change(
      screen.getByRole("textbox", { name: /^Individnummer på pappret/ }),
      { target: { value: "G1-25012" } },
    );
    expect(
      await screen.findByRole("dialog", { name: "Registrera kanin — G1-2512" }),
    ).toBeDefined();
  }, 20000);

  async function fillPaper() {
    suggestIndividualNumber.mockResolvedValue({
      success: true,
      data: {
        ...suggestion,
        suggested: "G1-2521",
        breeding_id: 4,
        litter_number: 2,
        can_issue_certificate: true,
        certificate_blocked_reason: null,
      },
    });
    checkIndividualNumber.mockResolvedValue({
      success: true,
      data: conflictCheck,
    });
    registerIndividual.mockResolvedValueOnce({
      success: false,
      error: "Individnumret på pappersintyget stämmer inte med Stambokens.",
      numberCheck: conflictCheck,
    });
    render(
      <RegisterRabbitDialog
        open
        onClose={() => {}}
        herdId="G1"
        breeding={{
          id: 4,
          birth_date: "2025-05-10",
          litter_number: 2,
          litter_size6w: 4,
        }}
      />,
    );
    await waitFor(() => expect(suggestIndividualNumber).toHaveBeenCalled());
    // The paper's number is typed before Stamboken's is shown
    expect(
      screen.getByRole("dialog", { name: "Registrera kanin" }),
    ).toBeDefined();
    const paperNumber = screen.getByRole("textbox", {
      name: /^Individnummer på pappret/,
    });
    expect((paperNumber as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByRole("textbox", { name: /^Färg(\s*\*)?$/ }), {
      target: { value: "Viltgrå" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /^Intygsnummer/ }), {
      target: { value: "P-77" },
    });
    fireEvent.change(paperNumber, { target: { value: "G1-2512" } });
    await waitFor(() =>
      expect(checkIndividualNumber).toHaveBeenCalledWith({
        breeding_id: 4,
        paper_number: "G1-2512",
      }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Registrera kanin — G1-2522" }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Registrera" }));
    const conflict = await screen.findByRole("dialog", {
      name: "Individnumret på pappret stämmer inte med Stamboken",
    });
    // The choices open once the refused registration has finished
    await waitFor(() =>
      expect(
        (
          within(conflict).getByRole("button", {
            name: "Pappret stämmer",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
    return conflict;
  }

  it("shows the conflict with no choice made and writes nothing for 'Pappret stämmer'", async () => {
    const conflict = await fillPaper();
    const box = within(conflict);
    expect(box.getByText("Pappret säger: G1-2512")).toBeDefined();
    expect(box.getByText("Stamboken säger: G1-2522")).toBeDefined();
    expect(
      box.getByText(/Kull 1 i Stamboken: parning 2025-03-03/),
    ).toBeDefined();
    expect(box.getByText("Inget sparas förrän du väljer.")).toBeDefined();
    const fix = box.getByRole("button", { name: "Pappret rättas" });
    const right = box.getByRole("button", { name: "Pappret stämmer" });
    // Neither choice is preselected
    expect(fix.className).toBe(right.className);
    expect(document.activeElement).not.toBe(fix);
    expect(registerIndividual.mock.calls[0][0]).toMatchObject({
      breeding_id: 4,
      certificate_type: "paper",
      paper_certificate: "P-77",
      paper_number: "G1-2512",
      resolution: undefined,
      position: undefined,
    });

    fireEvent.click(right);
    expect(box.getByText(/Kull 1 år 2025 är kullen/)).toBeDefined();
    const message = box.getByRole("textbox", {
      name: "Meddelande till genbanksansvarig",
    });
    expect((message as HTMLInputElement).value).toBe(
      "Pappersintyget säger G1-2512, Stamboken ger G1-2522.",
    );
    expect(box.getByRole("link", { name: "Gå dit" }).getAttribute("href")).toBe(
      "/stamboken/min-besattning?herd=G1&tab=breeding",
    );
    expect(registerIndividual).toHaveBeenCalledOnce();
  }, 20000);

  it("registers with Stamboken's number for 'Pappret rättas'", async () => {
    const conflict = await fillPaper();
    registerIndividual.mockResolvedValueOnce({
      success: true,
      data: {
        individual: { number: "G1-2522", name: null },
        certificate: "P-77",
        certificate_error: null,
      },
    });
    fireEvent.click(
      within(conflict).getByRole("button", { name: "Pappret rättas" }),
    );
    await waitFor(() => expect(registerIndividual).toHaveBeenCalledTimes(2));
    expect(registerIndividual.mock.calls[1][0]).toMatchObject({
      paper_number: "G1-2512",
      resolution: {
        expected_number: "G1-2522",
        choice: "use_stamboken_number",
      },
    });
    expect(
      await screen.findByText("Kanin registrerad som G1-2522"),
    ).toBeDefined();
  }, 20000);
});
