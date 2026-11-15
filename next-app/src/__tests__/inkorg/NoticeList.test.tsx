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
            created_at: "2026-11-14T23:30:00+00:00",
            read_at: null,
          },
        ]}
      />,
    );
    expect(screen.getByText("2026-11-15 00:30:00")).toBeInTheDocument();
  });
});
