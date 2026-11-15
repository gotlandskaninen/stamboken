import "@testing-library/jest-dom/vitest";
import { afterEach, describe, it, expect, beforeEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
const mocks = vi.hoisted(() => ({
  user: { is_owner: ["G9999", "G9998", "G9997"] } as {
    is_owner: string[] | null;
  },
}));
vi.mock("@/lib/user-context", () => ({ useUser: () => mocks.user }));

import OnboardingChecklist, {
  onboardingSteps,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/OnboardingChecklist";

const hane = { sex: "male", has_photo: false, is_active: true } as any;
const hona = { sex: "female", has_photo: true, is_active: true } as any;

describe("onboardingSteps", () => {
  it("needs both a buck and a doe before the start animals count", () => {
    expect(onboardingSteps([hane], [])[0].done).toBe(false);
    expect(onboardingSteps([hane, hona], [])[0].done).toBe(true);
  });
  it("counts only living, uncastrated breeding stock", () => {
    const dead = { ...hane, death_date: "2026-01-01" };
    const castrated = { ...hane, castration_date: "2026-01-01" };
    expect(onboardingSteps([dead, hona], [])[0].done).toBe(false);
    expect(onboardingSteps([castrated, hona], [])[0].done).toBe(false);
  });
  it("ticks the photo and mating steps from the herd's data", () => {
    const [, foto, parning] = onboardingSteps([hane, hona], []);
    expect(foto.done).toBe(true);
    expect(parning.done).toBe(false);
    expect(onboardingSteps([], [{} as any])[2].done).toBe(true);
  });
});

function renderList(props: Partial<Parameters<typeof OnboardingChecklist>[0]>) {
  return render(
    <OnboardingChecklist
      herd={{ is_active: true, individuals: [] }}
      breedings={[]}
      herdNumber="G9999"
      onGoTab={vi.fn()}
      onNewMating={vi.fn()}
      {...props}
    />,
  );
}

const TITLE = "Kom igång med din besättning";

describe("OnboardingChecklist", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("shows the steps for an active herd that has not bred", () => {
    renderList({});
    expect(screen.getByText(TITLE)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it.each([
    ["has bred", { breedings: [{} as any] }],
    ["is inactive", { herd: { is_active: false, individuals: [] } }],
    ["failed to load its breedings", { breedings: null }],
    ["is someone else's", { herdNumber: "G1234" }],
  ])("stays away from a herd that %s", (_why, props) => {
    renderList(props);
    expect(screen.queryByText(TITLE)).toBeNull();
  });

  it("remembers Stäng per herd", () => {
    const { unmount } = renderList({});
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
    expect(screen.queryByText(TITLE)).toBeNull();
    unmount();
    renderList({});
    expect(screen.queryByText(TITLE)).toBeNull();
    renderList({ herdNumber: "G9998" });
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("follows the selected herd when the herd switcher re-renders it", () => {
    localStorage.setItem("sb-onboarding-dismissed-G9998", "1");
    const { rerender } = renderList({});
    const props = {
      herd: { is_active: true, individuals: [] },
      breedings: [],
      onGoTab: vi.fn(),
      onNewMating: vi.fn(),
    };
    rerender(<OnboardingChecklist {...props} herdNumber="G9998" />);
    expect(screen.queryByText(TITLE)).toBeNull();
    rerender(<OnboardingChecklist {...props} herdNumber="G9999" />);
    expect(screen.getByText(TITLE)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
    rerender(<OnboardingChecklist {...props} herdNumber="G9997" />);
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("offers Ny parning only once the herd has a buck and a doe", () => {
    const { unmount } = renderList({});
    expect(screen.queryByRole("button", { name: "Ny parning" })).toBeNull();
    unmount();
    renderList({ herd: { is_active: true, individuals: [hane, hona] } });
    expect(
      screen.getByRole("button", { name: "Ny parning" }),
    ).toBeInTheDocument();
  });

  it("marks done steps and drops their action", () => {
    renderList({ herd: { is_active: true, individuals: [hane, hona] } });
    expect(screen.getAllByText("Klart")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Till Kaniner" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Ny parning" }),
    ).toBeInTheDocument();
  });
});
