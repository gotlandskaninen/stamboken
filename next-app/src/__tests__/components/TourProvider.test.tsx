import "@testing-library/jest-dom/vitest";
import React from "react";
import "@/i18n";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { SnackbarProvider } from "@/components/SnackbarProvider";

const mocks = vi.hoisted(() => ({
  pathname: "/stamboken/min-besattning",
  user: { id: 7 } as unknown,
  steps: [] as unknown[],
  importFails: false,
  drive: vi.fn(),
  driverConfig: null as null | Record<string, unknown>,
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("@/lib/user-context", () => ({ useOptionalUser: () => mocks.user }));
vi.mock("@/components/tour/tour", async (original) => ({
  ...(await original<typeof import("@/components/tour/tour")>()),
  stepsFor: () => mocks.steps,
}));
// A failed chunk load rejects the import; reading the export stands in for it.
vi.mock("driver.js", () => ({
  get driver() {
    if (mocks.importFails) throw new Error("chunk failed");
    return (config: Record<string, unknown>) => {
      mocks.driverConfig = config;
      return { drive: mocks.drive, destroy: vi.fn() };
    };
  },
}));

import {
  TourContext,
  TourOffer,
  TourProvider,
  useHideTourOffer,
  useStartTour,
} from "@/components/tour/Tour.client";

const STEP = {
  id: "tyckTill",
  target: "body",
  element: document.body,
  href: "/stamboken-online/manual#tyck-till",
  textKey: "tyckTill.text",
};
const OFFER = { name: "Rundtur i Stamboken" };

function MenuButton() {
  const start = useStartTour();
  return (
    <button type="button" onClick={start!}>
      Meny: Visa runt
    </button>
  );
}
function Checklist() {
  useHideTourOffer(true);
  return null;
}

const renderShell = (extra?: React.ReactNode) =>
  render(
    <SnackbarProvider>
      <TourProvider>
        <TourOffer />
        <MenuButton />
        {extra}
      </TourProvider>
    </SnackbarProvider>,
  );
// Lets the dynamic import and the state updates after it settle.
const settle = () => act(() => new Promise((r) => setTimeout(r, 0)));

beforeEach(() => {
  window.matchMedia = vi.fn(() => ({ matches: false })) as never;
  localStorage.clear();
  mocks.pathname = "/stamboken/min-besattning";
  mocks.steps = [STEP];
  mocks.importFails = false;
  mocks.drive.mockClear();
  mocks.driverConfig = null;
});
afterEach(cleanup);

describe("the offer", () => {
  it("starts the tour on yes and is then answered for good", async () => {
    const { unmount } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Visa runt" }));
    await settle();
    expect(mocks.drive).toHaveBeenCalledOnce();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
    unmount();
    renderShell();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
  });

  it("goes away at once when the tour starts from the menu", async () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Meny: Visa runt" }));
    await settle();
    expect(mocks.drive).toHaveBeenCalledOnce();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
  });

  it("cancels a start still loading when the user says Nej tack", async () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Visa runt" }));
    fireEvent.click(screen.getByRole("button", { name: "Nej tack" }));
    await settle();
    expect(mocks.drive).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
  });

  it("saves Nej tack at once and never starts the tour", () => {
    const { unmount } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Nej tack" }));
    expect(screen.queryByRole("region", OFFER)).toBeNull();
    unmount();
    renderShell();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
    expect(mocks.drive).not.toHaveBeenCalled();
  });

  it("stays away from other pages, where the user is at work", () => {
    mocks.pathname = "/stamboken/arsrapport";
    renderShell();
    expect(screen.queryByRole("region", OFFER)).toBeNull();
  });

  // A context change while the page hydrates makes React client-render a
  // page still streaming in, and its server HTML stays as a hidden copy.
  it("never changes the context value when the offer shows or hides", () => {
    const values = new Set<unknown>();
    function Probe() {
      values.add(React.useContext(TourContext));
      return null;
    }
    renderShell(
      <>
        <Probe />
        <Checklist />
      </>,
    );
    expect(screen.queryByRole("region", OFFER)).toBeNull();
    expect(values.size).toBe(1);
  });

  it("hides while the checklist shows its own Visa runt", () => {
    const { rerender } = renderShell(<Checklist />);
    expect(screen.queryByRole("region", OFFER)).toBeNull();
    rerender(
      <SnackbarProvider>
        <TourProvider>
          <TourOffer />
        </TourProvider>
      </SnackbarProvider>,
    );
    expect(screen.getByRole("region", OFFER)).toBeInTheDocument();
  });
});

describe("a start that does not get going", () => {
  it.each([
    ["driver.js does not load", () => (mocks.importFails = true)],
    ["the page has no steps", () => (mocks.steps = [])],
  ])("keeps the offer and says so when %s", async (_, arrange) => {
    arrange();
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Visa runt" }));
    await settle();
    expect(mocks.drive).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Rundturen gick inte att starta",
    );
    expect(screen.getByRole("region", OFFER)).toBeInTheDocument();
  });

  it("is dropped when the page changes while driver.js loads", async () => {
    const { rerender } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Meny: Visa runt" }));
    mocks.pathname = "/stamboken/arsrapport";
    rerender(
      <SnackbarProvider>
        <TourProvider>
          <TourOffer />
          <MenuButton />
        </TourProvider>
      </SnackbarProvider>,
    );
    await settle();
    expect(mocks.drive).not.toHaveBeenCalled();
  });
});

describe("the popover", () => {
  it("is a modal dialog and escapes every text", async () => {
    mocks.steps = [{ ...STEP, href: '/x"><script>' }];
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Meny: Visa runt" }));
    await settle();
    const config = mocks.driverConfig as {
      steps: { popover: { title: string; description: string } }[];
      onPopoverRender: (p: { wrapper: HTMLElement }) => void;
    };
    const wrapper = document.createElement("div");
    config.onPopoverRender({ wrapper });
    expect(wrapper.getAttribute("aria-modal")).toBe("true");
    expect(config.steps[0].popover.description).not.toContain("<script>");
    expect(config.steps[0].popover.description).toContain("&lt;script&gt;");
  });
});
