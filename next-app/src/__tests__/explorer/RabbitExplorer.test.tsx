import React from "react";
import { describe, it, expect, afterEach, beforeAll, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { Provider } from "react-redux";
import { store } from "@/redux/store";
import RabbitExplorer from "@/components/explorer/RabbitExplorer";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const urls: string[] = [];
beforeAll(async () => {
  await import("@/i18n");
  // fetchBaseQuery builds a Request from the relative /api URL; node needs an origin
  const NativeRequest = Request;
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(
          typeof input === "string" && input.startsWith("/")
            ? `http://localhost${input}`
            : input,
          init,
        );
      }
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      urls.push(typeof input === "string" ? input : (input as Request).url);
      return new Response(
        JSON.stringify({
          items: [],
          total_count: 0,
          page: 1,
          per_page: 25,
          total_pages: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
});
afterEach(cleanup);

describe("RabbitExplorer päls-filter", () => {
  it("skickar rex=true bara när Päls: Rex är vald (av: ingen rex-parameter)", async () => {
    render(
      <Provider store={store}>
        <RabbitExplorer initialData={null} initialGenebank={1} />
      </Provider>,
    );
    await waitFor(() => expect(urls.length).toBeGreaterThan(0));
    expect(urls.every((u) => !u.includes("rex"))).toBe(true);

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Päls" }));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Rex"));
    await waitFor(() =>
      expect(urls.some((u) => u.includes("rex=true"))).toBe(true),
    );
  });
});
