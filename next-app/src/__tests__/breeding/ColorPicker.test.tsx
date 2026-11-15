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
});
