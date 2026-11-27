import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { PaperChanges } from "@/app/(app)/stamboken/(dashboard)/arsrapport/PaperChanges";
import {
  CONSENT_TEXT,
  UTOM_ALL,
  emptyPaperFields,
  type PaperFields,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const show = (fields: PaperFields) => {
  const onChange = vi.fn();
  render(
    <PaperChanges fields={fields} onChange={onChange} accountEnd={null} />,
  );
  return onChange;
};
const radio = (name: string) =>
  screen.getByRole("radio", { name }) as HTMLInputElement;
const empty = emptyPaperFields();

describe("PaperChanges' Koharen question (PublicationFields)", () => {
  it("asks the profile's question, with a choice for no answer on the form", () => {
    show(empty);
    expect(
      screen.getByRole("radiogroup", { name: "Publicering i Koharen" }),
    ).toBeDefined();
    expect(screen.getByText(CONSENT_TEXT)).toBeDefined();
    expect(radio("Inget svar på blanketten").checked).toBe(true);
    expect(radio("Ja").checked).toBe(false);
    expect(radio("Nej").checked).toBe(false);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("starts Ja with nothing ticked", () => {
    const onChange = show(empty);
    fireEvent.click(radio("Ja"));
    expect(onChange).toHaveBeenCalledWith({
      ...empty,
      consent: "ja",
      utom: UTOM_ALL,
    });
  });

  it("takes a ticked item out of what is left out", () => {
    const onChange = show({ ...empty, consent: "ja", utom: UTOM_ALL });
    fireEvent.click(screen.getByRole("checkbox", { name: "telefonnummer" }));
    expect(onChange).toHaveBeenCalledWith({
      ...empty,
      consent: "ja",
      utom: ["email", "address"],
    });
  });

  it("clears the answer with Inget svar på blanketten", () => {
    const onChange = show({ ...empty, consent: "nej" });
    expect(radio("Nej").checked).toBe(true);
    fireEvent.click(radio("Inget svar på blanketten"));
    expect(onChange).toHaveBeenCalledWith({ ...empty, consent: "", utom: [] });
  });
});
