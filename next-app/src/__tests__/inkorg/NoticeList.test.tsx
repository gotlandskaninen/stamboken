import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/app/(app)/stamboken/(dashboard)/notiser/actions", () => ({
  markNoticesRead: vi.fn(),
}));

import { NoticeList } from "@/app/(app)/stamboken/(dashboard)/notiser/NoticeList";

afterEach(cleanup);

describe("NoticeList", () => {
  it("shows the time in Stockholm, not in the server's or browser's zone", () => {
    render(
      <NoticeList
        unread={0}
        notices={[
          {
            id: 1,
            kind: "klar",
            text: "Ditt inskick är klart",
            item_id: 7,
            individual_number: null,
            created_at: "2026-11-14T23:30:00+00:00",
            read_at: null,
          },
        ]}
      />,
    );
    expect(screen.getByText("2026-11-15 00:30:00")).toBeInTheDocument();
  });

  it("links a notice about a rabbit to the rabbit's page", () => {
    render(
      <NoticeList
        unread={0}
        notices={[
          {
            id: 2,
            kind: "kopare_borttagen",
            text: "En köpare har tagit bort sina uppgifter",
            item_id: null,
            individual_number: "G1-2111",
            created_at: "2026-11-14T10:00:00+00:00",
            read_at: null,
          },
        ]}
      />,
    );
    const link = screen.getByRole("link", { name: /\(G1-2111\)/ });
    expect(link).toHaveAttribute("href", "/stamboken/individ/G1-2111");
  });
});
