// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));

import { ApplicationsGridClient } from "@/app/(app)/medlem/ansokningar/ApplicationsGridClient";
import type { ApplicationRow } from "@/app/(app)/medlem/ansokningar/ApplicationsGridClient";

// MUI X DataGrid measures its container; jsdom reports 0×0 and would render no
// rows at all without these two stubs.
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      width: 900,
      height: 600,
      top: 0,
      left: 0,
      right: 900,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON: () => {},
    }),
  });
});

const rows: ApplicationRow[] = [
  {
    id: 41,
    first_name: "Anna",
    last_name: "Lindqvist",
    email: "anna@example.com",
    created_at: "2026-08-20T09:15:00",
  },
  {
    id: 42,
    first_name: "Bertil",
    last_name: "Ek",
    email: "bertil@example.com",
    created_at: "2026-08-21T14:40:00",
  },
];

// Same formatting the grid uses — computed here so the assertion follows the
// runner's timezone instead of hard-coding one.
const swedish = (iso: string) => new Date(iso).toLocaleString("sv-SE");

beforeEach(() => {
  pushMock.mockReset();
});

afterEach(cleanup);

describe("ApplicationsGridClient", () => {
  it("renders one row per application with name, e-post and Swedish date", () => {
    render(<ApplicationsGridClient rows={rows} />);

    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
    expect(
      screen.getByRole("columnheader", { name: "Namn" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "E-post" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Inskickad" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Anna Lindqvist")).toBeInTheDocument();
    expect(screen.getByText("Bertil Ek")).toBeInTheDocument();
    expect(screen.getByText("anna@example.com")).toBeInTheDocument();
    expect(screen.getByText("bertil@example.com")).toBeInTheDocument();
    expect(
      screen.getByText(swedish("2026-08-20T09:15:00")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(swedish("2026-08-21T14:40:00")),
    ).toBeInTheDocument();
  });

  it("renders the Namn cell as a link to the detail page", () => {
    render(<ApplicationsGridClient rows={rows} />);
    expect(screen.getByRole("link", { name: "Bertil Ek" })).toHaveAttribute(
      "href",
      "/medlem/ansokningar/42",
    );
  });

  it("navigates to the application detail page on row click", () => {
    render(<ApplicationsGridClient rows={rows} />);
    // A non-link cell: the Namn anchor stops propagation and navigates itself.
    fireEvent.click(screen.getByText("bertil@example.com"));
    expect(pushMock).toHaveBeenCalledWith("/medlem/ansokningar/42");
  });

  it("shows the empty state when the queue is empty", () => {
    render(<ApplicationsGridClient rows={[]} />);
    expect(
      screen.getByText("Inga ansökningar att granska."),
    ).toBeInTheDocument();
  });
});
