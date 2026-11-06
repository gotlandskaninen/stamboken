import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TabBar } from "@/components/shell/TabBar";
import type { SbIconName } from "@/components/shell/SbIcon";

const tabs = [
  { key: "oversikt", label: "Översikt", icon: "home" },
  { key: "kaniner", label: "Kaniner", icon: "rabbit" },
] as const satisfies readonly {
  key: string;
  label: string;
  icon: SbIconName;
}[];

afterEach(cleanup);

describe("TabBar", () => {
  it("renders one tab per entry with hrefs from makeHref", () => {
    const makeHref = vi.fn((key: string) => `?tab=${key}`);

    render(<TabBar tabs={[...tabs]} active="oversikt" makeHref={makeHref} />);

    const tabList = screen.getByRole("tablist", { name: "Vyer" });
    const renderedTabs = within(tabList).getAllByRole("tab");

    expect(renderedTabs).toHaveLength(2);
    expect(renderedTabs[1]).toHaveAttribute("href", "?tab=kaniner");
    expect(makeHref).toHaveBeenNthCalledWith(1, "oversikt");
    expect(makeHref).toHaveBeenNthCalledWith(2, "kaniner");
  });

  it("wires tab ids and aria-controls to external tabpanels via idBase", () => {
    render(
      <TabBar
        tabs={[...tabs]}
        active="oversikt"
        makeHref={(key) => `?tab=${key}`}
        idBase="herd"
      />,
    );

    const tab = screen.getByRole("tab", { name: /Kaniner/ });
    expect(tab).toHaveAttribute("id", "herd-tab-kaniner");
    expect(tab).toHaveAttribute("aria-controls", "herd-tabpanel-kaniner");
  });

  it("renders no ids without idBase", () => {
    render(
      <TabBar
        tabs={[...tabs]}
        active="oversikt"
        makeHref={(key) => `?tab=${key}`}
      />,
    );

    const tab = screen.getByRole("tab", { name: /Kaniner/ });
    expect(tab).not.toHaveAttribute("id");
    expect(tab).not.toHaveAttribute("aria-controls");
  });

  it("marks the active tab with aria-selected", () => {
    render(
      <TabBar
        tabs={[...tabs]}
        active="kaniner"
        makeHref={(key) => `?tab=${key}`}
      />,
    );

    expect(screen.getByRole("tab", { name: /Kaniner/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /Översikt/ })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });
});
