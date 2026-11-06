import React, { Suspense } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(),
  ApiError: class extends Error {},
}));
import { fetchApi } from "@/lib/api";
import { IndividualCard } from "@/components/herd/IndividualCard";
import { GeneticsSummary } from "@/components/individual/GeneticsSummary";
import { IndividualGenetics } from "@/components/individual/IndividualGenetics";
import type { Individual } from "@/redux/api/apiSlice";
import type { IndividualGeneticsData } from "@/lib/genetics";

// The dev "unique key" warning seen on the v2 individual page (dead
// animal, failed genetics fetch). The client tree below does not produce it.

const dead: Individual = {
  id: 1,
  number: "G1274-2301",
  name: "Svansen",
  sex: "female",
  herd: { herd: "G1274", herd_name: "Lundbergs", id: 1 },
  genebank_id: 1,
  certificate: null,
  digital_certificate: "D-1234",
  birth_date: "2023-03-15",
  mother: { number: "G1112-1901", name: "Mamma", sex: "female" },
  father: { number: "G1001-1801", name: "Pappa", sex: "male" },
  color: "Svart",
  color_note: null,
  death_date: "2025-01-15",
  death_note: null,
  selling_date: null,
  litter_size: 6,
  litter_size6w: 5,
  notes: null,
  herd_tracking: [],
  herd_active: true,
  is_active: false,
  is_registered: true,
  has_photo: false,
  alive: false,
  belly_color: null,
  eye_color: null,
  claw_color: null,
  hair_notes: "",
  breeding: 1,
  butchered: false,
  castration_date: null,
};

const deadGenetics: IndividualGeneticsData = {
  inbreeding: 0.031,
  mean_kinship: null,
  band: null,
  band_reason: "dead",
  in_reference: false,
  alive: false,
  pedigree_completeness: 0.97,
  reference_size: 820,
  definition_version: 2,
  preliminary: true,
  stale: false,
};

function renderCard(slot: React.ReactNode) {
  return render(
    <ThemeProvider theme={createTheme()}>
      <IndividualCard
        individual={dead}
        geneticsSlot={
          <Suspense fallback={<p>Hämtar genetik…</p>}>{slot}</Suspense>
        }
      />
    </ThemeProvider>,
  );
}

function keyWarnings(spy: ReturnType<typeof vi.spyOn>) {
  return spy.mock.calls.filter((args: unknown[]) =>
    args.some((a: unknown) => String(a).includes('unique "key"')),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("IndividualCard with the genetics slot", () => {
  it("renders a dead animal's genetics without a key warning", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderCard(<GeneticsSummary data={deadGenetics} />);
    expect(screen.getByText(/F 3,1\s%/)).toBeTruthy();
    expect(keyWarnings(spy)).toEqual([]);
  });

  it("renders a failed genetics fetch without a key warning", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(fetchApi).mockRejectedValueOnce(new Error("503"));
    renderCard(await IndividualGenetics({ number: "G1274-2301" }));
    expect(screen.getByText("Genetiken kan inte visas just nu")).toBeTruthy();
    expect(keyWarnings(spy)).toEqual([]);
  });
});

// Root cause: on the real page the slot reaches the client as a not yet
// resolved lazy reference (streamed Server Component). The static-children
// key check in IndividualCard cannot mark it validated, so React warns when
// the lazy later resolves to an unkeyed element inside the Box's children.
describe("IndividualCard with a streamed (lazy) genetics slot", () => {
  it("renders without a key warning once the slot resolves", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    // A lazy resolving to an element, as a streamed Server Component does.
    const slot = React.lazy(async () => ({
      default: (
        <GeneticsSummary data={deadGenetics} />
      ) as unknown as React.ComponentType,
    })) as unknown as React.ReactNode;
    render(
      <ThemeProvider theme={createTheme()}>
        <Suspense fallback={null}>
          <IndividualCard individual={dead} geneticsSlot={slot} />
        </Suspense>
      </ThemeProvider>,
    );
    expect(await screen.findByText(/F 3,1\s%/)).toBeTruthy();
    expect(keyWarnings(spy)).toEqual([]);
  });
});
