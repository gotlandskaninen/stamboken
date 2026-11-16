import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const getMine = vi.fn();
vi.mock("@/app/(app)/rapport/actions", () => ({ getMine: () => getMine() }));

import { LinkGate } from "@/app/(app)/rapport/LinkGate";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

describe("LinkGate", () => {
  it("#prov clears the address bar, shows the test text and posts nothing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    history.replaceState(null, "", "/rapport#prov");
    render(<LinkGate missing="ute" />);
    expect(
      await screen.findByText(
        "Provlänken fungerar. I det riktiga mejlet öppnar länken besättningens årsrapport.",
      ),
    ).toBeTruthy();
    expect(location.hash).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a token leaves the address bar before the post, then goes to the exchange", async () => {
    let hashAtPost: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        hashAtPost = location.hash;
        return Promise.resolve({ status: 403, ok: false });
      }),
    );
    history.replaceState(null, "", "/rapport#12.abc");
    render(<LinkGate missing="ute" />);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/rapport/ogiltig"),
    );
    expect(hashAtPost).toBe("");
  });
});
