import React from "react";
import { describe, it, expect, afterEach, beforeAll } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { PedigreeTree } from "@/components/individual/PedigreeTree";
import type { PedigreeNode } from "@/redux/api/apiSlice";

// Initialize i18n so useTranslation works
beforeAll(async () => {
  await import("@/i18n");
});

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const fullTree: PedigreeNode = {
  id: 1,
  name: "Subject",
  number: "G1-2301",
  sex: "female",
  mother: {
    id: 2,
    name: "Mor",
    number: "G1-2001",
    sex: "female",
    mother: {
      id: 4,
      name: "Mormor",
      number: "G1-1801",
      sex: "female",
      mother: null,
      father: null,
    },
    father: {
      id: 5,
      name: "Morfar",
      number: "G1-1802",
      sex: "male",
      mother: null,
      father: null,
    },
  },
  father: {
    id: 3,
    name: "Far",
    number: "G1-2002",
    sex: "male",
    mother: {
      id: 6,
      name: "Farmor",
      number: "G1-1803",
      sex: "female",
      mother: null,
      father: null,
    },
    father: {
      id: 7,
      name: "Farfar",
      number: "G1-1804",
      sex: "male",
      mother: null,
      father: null,
    },
  },
};

afterEach(cleanup);

describe("PedigreeTree", () => {
  it("renders parent numbers", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(screen.getByText("G1-2001")).toBeDefined();
    expect(screen.getByText("G1-2002")).toBeDefined();
  });

  it("renders grandparent numbers", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(screen.getByText("G1-1801")).toBeDefined();
    expect(screen.getByText("G1-1802")).toBeDefined();
    expect(screen.getByText("G1-1803")).toBeDefined();
    expect(screen.getByText("G1-1804")).toBeDefined();
  });

  it("renders data-testid pedigree-tree", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(screen.getByTestId("pedigree-tree")).toBeDefined();
  });

  it("shows Okänd for missing ancestors", () => {
    const sparseTree: PedigreeNode = {
      id: 1,
      name: "Subject",
      number: "G1-2301",
      sex: "female",
      mother: null,
      father: null,
    };
    renderWithTheme(<PedigreeTree tree={sparseTree} />);
    const unknowns = screen.getAllByText("Okänd");
    // 2 parents + 4 grandparents + 8 great-grandparents = 14 unknowns
    expect(unknowns.length).toBe(14);
  });

  it("ancestor nodes link to individual detail page", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    const motherLink = screen.getByText("G1-2001").closest("a");
    expect(motherLink).toBeDefined();
    expect(motherLink?.getAttribute("href")).toBe("/stamboken/individ/G1-2001");
  });

  it("renders generation labels", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(screen.getByText("Föräldrar")).toBeDefined();
    expect(screen.getByText("Mor-/farföräldrar")).toBeDefined();
    expect(screen.getByText("Gammelföräldrar")).toBeDefined();
  });

  it("marks highlighted ancestors with the text 'gemensam', not colour alone", () => {
    renderWithTheme(
      <PedigreeTree tree={fullTree} highlight={new Set(["G1-1801"])} />,
    );
    const marks = screen.getAllByTestId("pedigree-common-ancestor");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("gemensam");
    expect(marks[0].closest("a")?.getAttribute("href")).toBe(
      "/stamboken/individ/G1-1801",
    );
  });

  it("renders no 'gemensam' marks without a highlight prop", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(screen.queryAllByTestId("pedigree-common-ancestor")).toHaveLength(0);
  });

  it("renders an unregistered parent as 'Ej registrerad'", () => {
    renderWithTheme(
      <PedigreeTree
        tree={{
          ...fullTree,
          mother: {
            id: null,
            name: null,
            number: null,
            sex: "female",
            unregistered: true,
            mother: null,
            father: null,
          },
        }}
      />,
    );
    expect(screen.getByText("Ej registrerad")).toBeDefined();
  });

  describe("layout=stacked (mobile)", () => {
    it("renders every generation as nested lists, not the 400 px grid", () => {
      renderWithTheme(<PedigreeTree tree={fullTree} layout="stacked" />);
      const tree = screen.getByTestId("pedigree-tree");
      expect(tree.getAttribute("data-layout")).toBe("stacked");
      expect(tree.querySelector("ul ul")).not.toBeNull();
      for (const n of ["G1-2001", "G1-2002", "G1-1801", "G1-1802", "G1-1803"])
        expect(screen.getByText(n)).toBeDefined();
      expect(screen.getByText("Avkomma")).toBeDefined();
    });

    it("keeps the 'gemensam' text mark on highlighted ancestors", () => {
      renderWithTheme(
        <PedigreeTree
          tree={fullTree}
          layout="stacked"
          highlight={new Set(["G1-1801", "G1-2002"])}
        />,
      );
      const marks = screen.getAllByTestId("pedigree-common-ancestor");
      expect(marks).toHaveLength(2);
      expect(marks.every((m) => m.textContent === "gemensam")).toBe(true);
    });

    it("does not expand the parents of an unknown ancestor", () => {
      renderWithTheme(
        <PedigreeTree
          tree={{ ...fullTree, mother: null, father: null }}
          layout="stacked"
        />,
      );
      expect(screen.getAllByText("Okänd")).toHaveLength(2);
    });

    it("lists the stated parents of an unregistered animal", () => {
      renderWithTheme(
        <PedigreeTree
          layout="stacked"
          tree={{
            ...fullTree,
            mother: {
              id: null,
              name: null,
              number: null,
              sex: "female",
              unregistered: true,
              mother: fullTree.mother?.mother ?? null,
              father: fullTree.mother?.father ?? null,
            },
          }}
        />,
      );
      expect(screen.getByText("Ej registrerad")).toBeDefined();
      expect(screen.getByText("G1-1801")).toBeDefined();
    });
  });

  it("grid layout stays the default", () => {
    renderWithTheme(<PedigreeTree tree={fullTree} />);
    expect(
      screen.getByTestId("pedigree-tree").getAttribute("data-layout"),
    ).toBeNull();
  });

  it("stacked layout: every list is an explicit list (list-style: none drops semantics)", () => {
    const { container } = renderWithTheme(
      <PedigreeTree tree={fullTree} layout="stacked" />,
    );
    const lists = container.querySelectorAll("ul");
    expect(lists.length).toBeGreaterThan(1);
    lists.forEach((ul) => expect(ul.getAttribute("role")).toBe("list"));
    expect(screen.getAllByRole("list").length).toBe(lists.length);
  });

  it("interactive ancestor nodes are at least 44px tall (stacked and grid)", () => {
    for (const layout of ["stacked", "grid"] as const) {
      const { unmount } = renderWithTheme(
        <PedigreeTree tree={fullTree} layout={layout} />,
      );
      const link = screen.getByText("G1-2001").closest("a")!;
      expect(getComputedStyle(link).minHeight).toBe("44px");
      unmount();
    }
  });
});
