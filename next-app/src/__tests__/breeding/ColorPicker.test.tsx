import React from "react";
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ColorPicker } from "@/components/herd/ColorPicker";
import { TESTNYCKEL } from "../fargatlas/testnyckel";

const getFargatlas = vi.hoisted(() => vi.fn());
vi.mock("@/app/(app)/stamboken/(dashboard)/fargatlas/actions", () => ({
  getFargatlas,
}));

const options = [
  { id: 22, name: "Viltgrå", comment: "Som en vildkanin" },
  { id: 3, name: "Svart", comment: null },
];

afterEach(cleanup);
// The picker reads the atlas when it mounts, to know whether the guide has a key; no atlas unless a test says so.
beforeEach(() => {
  getFargatlas.mockReset();
  getFargatlas.mockResolvedValue(null);
});

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
  });

  it("läser atlasen igen när kortet öppnas efter ett fel", async () => {
    getFargatlas.mockReset();
    getFargatlas
      .mockResolvedValueOnce(null) // the read when the picker mounts
      .mockRejectedValueOnce(new Error("nätet"))
      .mockResolvedValue({
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
    expect(getFargatlas).toHaveBeenCalledTimes(3); // mount, failed opening, new opening
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

  describe("Hjälp mig välja", () => {
    const medNyckel = {
      fotoBas: "/api",
      atlas: { version: "test", grupper: {}, farger: [], nyckel: TESTNYCKEL },
    };
    // The made-up key's path to 22.
    const tillViltgra = async () => {
      for (const text of ["Nej", "Ja, testvilt"])
        fireEvent.click(
          await screen.findByRole("button", { name: new RegExp(`^${text}`) }),
        );
    };
    const oppna = async () =>
      fireEvent.click(
        await screen.findByRole("button", { name: "Hjälp mig välja" }),
      );

    it("guiden sätter färgen och påminner om pälsen", async () => {
      getFargatlas.mockResolvedValue(medNyckel);
      const onChange = vi.fn();
      render(
        <ColorPicker
          options={options}
          value=""
          onChange={onChange}
          genebank="Gotlandskanin"
        />,
      );
      await oppna();
      await tillViltgra();
      fireEvent.click(screen.getByRole("button", { name: "Ja" }));
      fireEvent.click(screen.getByRole("button", { name: /^Välj 22/ }));
      expect(onChange).toHaveBeenCalledWith("Viltgrå");
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(
        screen.getByText("Kom ihåg: Testsvar: välj Rex vid Päls."),
      ).toBeDefined();
    });

    it("stäng utan val ändrar inget", async () => {
      getFargatlas.mockResolvedValue(medNyckel);
      const onChange = vi.fn();
      render(
        <ColorPicker
          options={options}
          value="Svart"
          onChange={onChange}
          genebank="Gotlandskanin"
        />,
      );
      await oppna();
      await tillViltgra();
      fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(onChange).not.toHaveBeenCalled();
      expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
        "3 Svart",
      );
    });

    it("ett tryck bredvid dialogen stänger den inte", async () => {
      getFargatlas.mockResolvedValue(medNyckel);
      render(
        <ColorPicker
          options={options}
          value=""
          onChange={() => {}}
          genebank="Gotlandskanin"
        />,
      );
      await oppna();
      fireEvent.click(await screen.findByRole("button", { name: /^Nej/ }));
      fireEvent.click(document.querySelector(".MuiBackdrop-root")!);
      expect(screen.getByRole("dialog")).toBeDefined();
      expect(screen.getByText("Testfråga tre?")).toBeDefined();
    });

    it("Välj stänger inte när färgen saknas i listan", async () => {
      getFargatlas.mockResolvedValue(medNyckel);
      const onChange = vi.fn();
      render(
        <ColorPicker
          options={[{ id: 3, name: "Svart", comment: null }]}
          value="Svart"
          onChange={onChange}
          genebank="Gotlandskanin"
        />,
      );
      await oppna();
      await tillViltgra();
      fireEvent.click(screen.getByRole("button", { name: /^Välj 22/ }));
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByRole("dialog")).toBeDefined();
      expect(screen.getByText(/Färg 22 finns inte i färglistan/)).toBeDefined();
    });

    it("ingen guide utan nyckel i atlaspaketet", async () => {
      getFargatlas.mockResolvedValue({
        ...medNyckel,
        atlas: { ...medNyckel.atlas, nyckel: null },
      });
      render(
        <ColorPicker
          options={options}
          value=""
          onChange={() => {}}
          genebank="Gotlandskanin"
        />,
      );
      await waitFor(() => expect(getFargatlas).toHaveBeenCalled());
      await new Promise((r) => setTimeout(r, 0));
      expect(
        screen.queryByRole("button", { name: "Hjälp mig välja" }),
      ).toBeNull();
    });

    it("ingen guide medan listan laddas", () => {
      getFargatlas.mockResolvedValue(medNyckel);
      render(
        <ColorPicker
          options={[]}
          loading
          value=""
          onChange={() => {}}
          genebank="Gotlandskanin"
        />,
      );
      expect(
        screen.queryByRole("button", { name: "Hjälp mig välja" }),
      ).toBeNull();
    });

    it("ingen guide för mellerud", async () => {
      getFargatlas.mockResolvedValue(medNyckel);
      render(
        <ColorPicker
          options={[{ id: 101, name: "Albino", comment: null }]}
          value=""
          onChange={() => {}}
          genebank="Mellerudskanin"
        />,
      );
      await new Promise((r) => setTimeout(r, 0));
      expect(
        screen.queryByRole("button", { name: "Hjälp mig välja" }),
      ).toBeNull();
      expect(getFargatlas).not.toHaveBeenCalled(); // no read for a genebank without a key
    });
  });
});
