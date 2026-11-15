import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
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
});
