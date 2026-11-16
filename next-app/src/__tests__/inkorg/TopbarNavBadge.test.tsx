import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TopbarNav } from "@/components/shell/TopbarNav";

vi.mock("next/navigation", () => ({ usePathname: () => "/stamboken/profil" }));

beforeAll(async () => {
  await import("@/i18n");
});
afterEach(cleanup);

describe("TopbarNav intake links", () => {
  it("shows Mina inskick with the count to a non-worker, no Inkorg", () => {
    render(<TopbarNav unread={3} />);
    const link = screen.getByRole("link", { name: /Mina inskick/ });
    expect(link).toHaveAttribute("href", "/stamboken/inskick");
    expect(link).toHaveTextContent("3");
    expect(screen.queryByRole("link", { name: /Inkorg/ })).toBeNull();
  });

  it("shows Inkorg with the count to a queue worker", () => {
    render(<TopbarNav worksInQueue unread={5} />);
    const inkorg = screen.getByRole("link", { name: /Inkorg/ });
    expect(inkorg).toHaveAttribute("href", "/stamboken/inkorg");
    expect(inkorg).toHaveTextContent("5");
    expect(
      screen.getByRole("link", { name: /Mina inskick/ }),
    ).not.toHaveTextContent("5");
  });

  it("shows no badge at zero", () => {
    render(<TopbarNav unread={0} />);
    expect(
      screen.getByRole("link", { name: /Mina inskick/ }),
    ).toHaveTextContent(/^Mina inskick$/);
  });
});
