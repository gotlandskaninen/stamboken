import React from "react";
import { describe, it, expect, afterEach, beforeAll } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import type { PedigreeNode } from "@/redux/api/apiSlice";
import { TestbreedTree } from "@/components/provparning/TestbreedTree";

beforeAll(async () => {
  await import("@/i18n");
});
afterEach(cleanup);

const node = (
  number: string,
  sex: "female" | "male",
  parents: { mother?: PedigreeNode | null; father?: PedigreeNode | null } = {},
): PedigreeNode => ({
  id: 1,
  name: null,
  number,
  sex,
  mother: parents.mother ?? null,
  father: parents.father ?? null,
});

const renderTree = (props: React.ComponentProps<typeof TestbreedTree>) =>
  render(
    <ThemeProvider theme={createTheme()}>
      <TestbreedTree {...props} />
    </ThemeProvider>,
  );

describe("TestbreedTree", () => {
  it("renders both partner trees from the response (stacked on a narrow viewport)", () => {
    renderTree({
      female: node("G1-F", "female", {
        mother: node("G1-FM", "female"),
        father: node("G1-FF", "male"),
      }),
      male: node("G1-M", "male", { father: node("G1-MF", "male") }),
      highlight: new Set(["G1-M"]),
    });
    expect(
      screen.getByTestId("pedigree-tree").getAttribute("data-layout"),
    ).toBe("stacked");
    for (const n of ["G1-F", "G1-FM", "G1-FF", "G1-M", "G1-MF"])
      expect(screen.getByText(n)).toBeDefined();
    expect(screen.getByTestId("pedigree-common-ancestor").textContent).toBe(
      "gemensam",
    );
  });

  it("shows a filtered (null) ancestor as unknown, never a number", () => {
    // The server nulls voided / other-genebank ancestors; the tree has no way
    // to show anything else (it fetches nothing itself).
    renderTree({
      female: node("G1-F", "female", { father: node("G1-FF", "male") }),
      male: node("G1-M", "male"),
      highlight: new Set(),
    });
    expect(screen.queryByText("G1-VOID")).toBeNull();
    expect(screen.getAllByText("Okänd").length).toBeGreaterThan(0);
  });

  it("renders an unregistered partner as 'Ej registrerad' over the stated parents", () => {
    const virtual: PedigreeNode = {
      id: null,
      name: null,
      number: null,
      sex: "male",
      unregistered: true,
      mother: node("G1-VM", "female"),
      father: null,
    };
    renderTree({
      female: node("G1-F", "female"),
      male: virtual,
      highlight: new Set(),
    });
    const tree = screen.getByTestId("pedigree-tree");
    expect(within(tree).getByText("Ej registrerad")).toBeDefined();
    expect(within(tree).getByText("G1-VM")).toBeDefined();
  });
});
