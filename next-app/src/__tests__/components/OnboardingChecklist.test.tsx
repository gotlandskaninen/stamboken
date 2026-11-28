import "@testing-library/jest-dom/vitest";
import "@/i18n";
import { afterEach, describe, it, expect, beforeEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
const mocks = vi.hoisted(() => ({
  user: { is_owner: ["G9999", "G9998", "G9997"], v2_prod_access: true } as {
    is_owner: string[] | null;
    v2_prod_access: boolean;
  },
}));
vi.mock("@/lib/user-context", () => ({ useUser: () => mocks.user }));

import OnboardingChecklist, {
  onboardingSteps,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/OnboardingChecklist";
import { TourContext } from "@/components/tour/Tour.client";

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
const STÄNG = "Stäng Kom igång med din besättning";

describe("OnboardingChecklist", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = "sb_mode=; max-age=0";
    mocks.user.v2_prod_access = true;
  });
  afterEach(cleanup);

  it("shows the steps for an active herd that has not bred", () => {
    renderList({});
    expect(screen.getByText(TITLE)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("offers the test environment as a fourth step with a manual link", () => {
    renderList({});
    const step = screen.getAllByRole("listitem")[3];
    expect(step).toHaveTextContent("Prova i testmiljön");
    expect(step).toHaveTextContent(
      "Byt till testmiljön i menyn under din bild.",
    );
    expect(step).not.toHaveTextContent("Klart");
    expect(screen.getByRole("link", { name: "Om testmiljön" })).toHaveAttribute(
      "href",
      "/stamboken-online/manual#testmiljön-och-riktiga-stamboken",
    );
  });

  it("hides the test environment step without access to riktiga stamboken", () => {
    mocks.user.v2_prod_access = false;
    renderList({});
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Prova i testmiljön")).toBeNull();
  });

  it("does not tick the test environment step just by rendering in it", () => {
    document.cookie = "sb_mode=demo";
    renderList({});
    expect(screen.getAllByRole("listitem")[3]).not.toHaveTextContent("Klart");
    expect(localStorage.getItem("sb-onboarding-tried-demo")).toBeNull();
  });

  it("ticks the test environment step once the menu has switched there", () => {
    // Written by AvatarMenu on "Ja, byt till testmiljön".
    localStorage.setItem("sb-onboarding-tried-demo", "1");
    renderList({});
    expect(screen.getAllByRole("listitem")[3]).toHaveTextContent("Klart");
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
    fireEvent.click(screen.getByRole("button", { name: STÄNG }));
    expect(screen.queryByText(TITLE)).toBeNull();
    unmount();
    renderList({});
    expect(screen.queryByText(TITLE)).toBeNull();
    renderList({ herdNumber: "G9998" });
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("follows the selected herd when the herd switcher re-renders it", () => {
    localStorage.setItem("sb-onboarding-dismissed-demo-G9998", "1");
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
    fireEvent.click(screen.getByRole("button", { name: STÄNG }));
    rerender(<OnboardingChecklist {...props} herdNumber="G9997" />);
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("offers Ny parning once the herd has a living doe (the buck may be borrowed)", () => {
    const { unmount } = renderList({
      herd: { is_active: true, individuals: [hane] },
    });
    expect(screen.queryByRole("button", { name: "Ny parning" })).toBeNull();
    unmount();
    renderList({ herd: { is_active: true, individuals: [hona] } });
    expect(
      screen.getByRole("button", { name: "Ny parning" }),
    ).toBeInTheDocument();
  });

  it("offers Till Kaniner only when the herd has rabbits", () => {
    const { unmount } = renderList({});
    expect(screen.queryByRole("button", { name: "Till Kaniner" })).toBeNull();
    unmount();
    renderList({ herd: { is_active: true, individuals: [{ ...hane }] } });
    expect(
      screen.getByRole("button", { name: "Till Kaniner" }),
    ).toBeInTheDocument();
  });

  it("keeps Stäng apart for the test environment and the real stamboken", () => {
    const { unmount } = renderList({});
    fireEvent.click(screen.getByRole("button", { name: STÄNG }));
    unmount();
    document.cookie = "sb_mode=prod";
    renderList({});
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("links each step to a heading that exists in the manual", async () => {
    const { readFile } = await import("node:fs/promises");
    const { headingSlugger } = await import("@/lib/headingSlug");
    const md = await readFile("public/stamboken/manual/USER_MANUAL.md", "utf8");
    const slug = headingSlugger();
    const ids = new Set(
      [...md.matchAll(/^#{1,6} (.+)$/gm)].map((m) => slug(m[1])),
    );
    for (const step of onboardingSteps([], [], false)) {
      expect(ids).toContain(step.manual.slice(1));
    }
  });

  it("starts the tour from Visa runt when the page has a tour", () => {
    renderList({});
    expect(screen.queryByRole("button", { name: "Visa runt" })).toBeNull();
    cleanup();
    const start = vi.fn();
    const hideOffer = vi.fn();
    render(
      <TourContext.Provider
        value={{
          start,
          offerOpen: () => false,
          subscribeOffer: () => () => {},
          decline: vi.fn(),
          hideOffer,
        }}
      >
        <OnboardingChecklist
          herd={{ is_active: true, individuals: [] }}
          breedings={[]}
          herdNumber="G9999"
          onGoTab={vi.fn()}
          onNewMating={vi.fn()}
        />
      </TourContext.Provider>,
    );
    // One Visa runt on the page: the offer hides while the list shows.
    expect(hideOffer).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Visa runt" }));
    expect(start).toHaveBeenCalledOnce();
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
