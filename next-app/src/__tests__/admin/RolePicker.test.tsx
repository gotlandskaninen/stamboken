import { describe, it, expect, vi, afterEach } from "vitest";
// jest-dom matchers on vitest's expect (this project has no global setup —
// each render test registers them, matching landing.test.tsx/DemoBanner.test.tsx).
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { RolePicker } from "@/app/(app)/stamboken/(dashboard)/admin/_components/RolePicker";

const genebanks = [
  { id: 1, name: "Gotlandskaninen" },
  { id: 2, name: "Mellerudskaninen" },
];
const herds = [{ id: 42, herd: "G12", herd_name: "Testgården" }];

describe("RolePicker (grant role — numeric ids only)", () => {
  afterEach(cleanup);

  it("admin level needs no secondary picker and submits {level:'admin'}", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker
        genebanks={genebanks}
        herds={herds}
        defaultLevel="admin"
        onGrant={onGrant}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "admin" });
  });

  it("matrikel_admin level needs no secondary picker and submits {level:'matrikel_admin'}", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker
        genebanks={genebanks}
        herds={herds}
        defaultLevel="matrikel_admin"
        onGrant={onGrant}
      />,
    );
    expect(screen.queryByLabelText("Genbank")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "matrikel_admin" });
  });

  it("offers Matrikeladministratör in the role select and submits it without a secondary picker", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker genebanks={genebanks} herds={herds} onGrant={onGrant} />,
    );
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Roll" }));
    fireEvent.click(
      screen.getByRole("option", { name: "Matrikeladministratör" }),
    );
    expect(screen.queryByLabelText("Genbank")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "matrikel_admin" });
  });

  it("manager level shows genebank picker and submits numeric genebank id", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker
        genebanks={genebanks}
        herds={herds}
        defaultLevel="manager"
        onGrant={onGrant}
      />,
    );
    const combo = screen.getByLabelText("Genbank");
    fireEvent.mouseDown(combo);
    fireEvent.click(screen.getByText("Gotlandskaninen"));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "manager", genebank: 1 });
  });

  it("owner level shows herd picker and submits numeric Herd.id (not the code)", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker
        genebanks={genebanks}
        herds={herds}
        defaultLevel="owner"
        onGrant={onGrant}
      />,
    );
    const combo = screen.getByLabelText("Besättning");
    fireEvent.mouseDown(combo);
    fireEvent.click(screen.getByText("G12 — Testgården"));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "owner", herd: 42 });
  });

  it("submit is disabled while the required secondary picker is empty", () => {
    render(
      <RolePicker
        genebanks={genebanks}
        herds={herds}
        defaultLevel="viewer"
        onGrant={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Lägg till roll" }),
    ).toBeDisabled();
  });
});
