import { describe, expect, it } from "vitest";
import { roleSummaryLabel } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/roleSummaryLabel";

describe("roleSummaryLabel", () => {
  it.each([
    ["ingen roll", "Ingen roll"],
    ["admin", "Administratör"],
    ["manager(G,M)", "Genbanksansvarig (G,M)"],
    ["viewer(G)", "Granskare (G)"],
    ["owner(2 besättningar)", "Besättningsägare (2 besättningar)"],
  ])("%s -> %s", (raw, label) => {
    expect(roleSummaryLabel(raw)).toBe(label);
  });

  // matrikel_admin must show, alone or next to a studbook role.
  it.each([
    ["matrikel_admin", "Matrikeladministratör"],
    [
      "manager(G) + matrikel_admin",
      "Genbanksansvarig (G) + Matrikeladministratör",
    ],
    ["admin + matrikel_admin", "Administratör + Matrikeladministratör"],
  ])("%s -> %s", (raw, label) => {
    expect(roleSummaryLabel(raw)).toBe(label);
  });
});
