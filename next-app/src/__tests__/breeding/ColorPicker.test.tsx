import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ColorPicker } from "@/components/herd/ColorPicker";

const getFargatlas = vi.hoisted(() => vi.fn());
vi.mock("@/app/(app)/stamboken/(dashboard)/fargatlas/actions", () => ({
  getFargatlas,
}));

const options = [
  { id: 22, name: "Viltgrå", comment: "Som en vildkanin" },
  { id: 3, name: "Svart", comment: null },
];

afterEach(cleanup);

describe("ColorPicker", () => {
  it('visar "22 Viltgrå"', () => {
    render(
      <ColorPicker
        options={options}
        value="Viltgrå"
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
      "22 Viltgrå",
    );
  });

  it("visar kommentaren", () => {
    render(
      <ColorPicker
        options={options}
        value=""
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    fireEvent.mouseDown(screen.getByRole("combobox"));
    expect(screen.getByText("Som en vildkanin")).toBeDefined();
    expect(screen.getByText("3 Svart")).toBeDefined();
  });

  it("skickar färgens namn vid val", () => {
    const onChange = vi.fn();
    render(
      <ColorPicker
        options={options}
        value=""
        onChange={onChange}
        genebank="Gotlandskanin"
      />,
    );
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(screen.getByText("22 Viltgrå"));
    expect(onChange).toHaveBeenCalledWith("Viltgrå");
  });

  it("fritext när listan är tom", () => {
    const onChange = vi.fn();
    render(
      <ColorPicker
        options={[]}
        value=""
        onChange={onChange}
        genebank="Gotlandskanin"
      />,
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Viltgrå" },
    });
    expect(onChange).toHaveBeenCalledWith("Viltgrå");
  });

  it("söker även i kommentaren", async () => {
    render(
      <ColorPicker
        options={options}
        value=""
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "vildkanin" } });
    await waitFor(() => expect(screen.queryByText("3 Svart")).toBeNull());
    expect(screen.getByText("22 Viltgrå")).toBeDefined();
  });

  it("kan inte rensas till tom färg", () => {
    render(
      <ColorPicker
        options={options}
        value="Viltgrå"
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    expect(screen.queryByLabelText("Clear")).toBeNull();
  });

  it("visar en sparad färg som inte finns i listan", () => {
    render(
      <ColorPicker
        options={options}
        value="Havanna"
        valueId={7}
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
      "7 Havanna",
    );
  });

  it("är en combobox medan listan laddas", () => {
    render(
      <ColorPicker
        options={[]}
        loading
        value=""
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    expect(screen.getByRole("combobox")).toBeDefined();
  });

  it("visar den lagrade färgens id när två genbanker har samma namn", () => {
    render(
      <ColorPicker
        options={[{ id: 101, name: "Albino", comment: null }]}
        value="Albino"
        valueId={12}
        onChange={() => {}}
        genebank="Mellerudskanin"
      />,
    );
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
      "12 Albino",
    );
  });

  it('"Visa färgen" öppnar färgens kort ur atlasen', async () => {
    getFargatlas.mockResolvedValue({
      fotoBas: "/api",
      atlas: {
        version: "test",
        grupper: {},
        farger: [
          {
            id: 22,
            name: "Viltgrå",
            comment: "Som en vildkanin",
            beskrivning: "Testbeskrivning",
            skiljs_fran: null,
            foton: [],
          },
        ],
      },
    });
    render(
      <ColorPicker
        options={options}
        value="Viltgrå"
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa färgen" }));
    expect(
      await screen.findByRole("heading", { name: "22 Viltgrå" }),
    ).toBeDefined();
    expect(screen.getByText("Testbeskrivning")).toBeDefined();
    expect(getFargatlas).toHaveBeenCalledTimes(1);
  });

  it("läser atlasen igen när kortet öppnas efter ett fel", async () => {
    getFargatlas.mockReset();
    getFargatlas.mockRejectedValueOnce(new Error("nätet")).mockResolvedValue({
      fotoBas: "/api",
      atlas: { version: "test", grupper: {}, farger: [] },
    });
    render(
      <ColorPicker
        options={options}
        value="Viltgrå"
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa färgen" }));
    expect(
      await screen.findByText(/Färgatlasen gick inte att hämta/),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Visa färgen" }));
    // while the new read is on its way, the old error is not shown
    expect(screen.queryByText(/Färgatlasen gick inte att hämta/)).toBeNull();
    expect(screen.getByLabelText("Hämtar färgen")).toBeDefined();
    expect(
      await screen.findByText("Färgen finns inte i färgatlasen."),
    ).toBeDefined();
    expect(getFargatlas).toHaveBeenCalledTimes(2);
  });

  it('ingen "Visa färgen" innan en färg är vald', () => {
    render(
      <ColorPicker
        options={options}
        value=""
        onChange={() => {}}
        genebank="Gotlandskanin"
      />,
    );
    expect(screen.queryByRole("button", { name: "Visa färgen" })).toBeNull();
  });
});
