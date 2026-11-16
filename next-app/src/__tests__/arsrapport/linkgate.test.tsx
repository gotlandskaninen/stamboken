import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
}));
const getMine = vi.fn();
vi.mock("@/app/(app)/rapport/actions", () => ({ getMine: () => getMine() }));

import { LinkGate, resetLinkQueue } from "@/app/(app)/rapport/LinkGate";
import { CLEAR_HASH_SCRIPT } from "@/app/(app)/rapport/clearHash";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  resetLinkQueue(); // the queue is module state: one test's hung request must not block the next
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

  it("the inline script takes the token out of the address bar before the app starts", () => {
    history.replaceState(null, "", "/rapport#12.abc");
    new Function(CLEAR_HASH_SCRIPT)();
    expect(location.hash).toBe("");
    expect(location.pathname).toBe("/rapport");
    expect((window as { __rapportToken?: string }).__rapportToken).toBe(
      "12.abc",
    );
    // LinkGate takes the token from memory and posts it; the variable is gone afterwards.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ status: 403, ok: false })),
    );
    render(<LinkGate missing="ute" />);
    return waitFor(() => {
      expect(replace).toHaveBeenCalledWith("/rapport/ogiltig");
      expect((window as { __rapportToken?: string }).__rapportToken).toBe(
        undefined,
      );
    });
  });

  it("a link opened inside the open page (hash change only) is cleared and exchanged", async () => {
    replace.mockReset();
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: { body: string }) => {
        bodies.push(init.body);
        return Promise.resolve({ status: 403, ok: false });
      }),
    );
    history.replaceState(null, "", "/rapport");
    render(<LinkGate missing="ute" />);
    await screen.findByText(/Sidan stängdes efter två timmar/);
    await act(async () => {
      history.pushState(null, "", "/rapport#7.other");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await waitFor(() => expect(bodies).toEqual(['{"token":"7.other"}']));
    expect(location.hash).toBe("");
  });

  it("a late answer for an older link never overrides the newer one", async () => {
    replace.mockReset();
    const pending: Record<string, (r: unknown) => void> = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: { body: string }) =>
          new Promise((resolve) => {
            pending[JSON.parse(init.body).token] = resolve;
          }),
      ),
    );
    getMine.mockResolvedValue({
      ok: true,
      data: [{ code_id: 2, herd: "M2", herd_name: null, year: 2025 }],
    });
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await waitFor(() => expect(pending.A).toBeTruthy());
    await act(async () => {
      history.pushState(null, "", "/rapport#B");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await act(async () => {
      pending.A({ status: 403, ok: false }); // the old link answers first, and is stale
    });
    await waitFor(() => expect(pending.B).toBeTruthy());
    await act(async () => {
      pending.B({ status: 200, ok: true, json: () => ({ herd: "M2" }) });
    });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/rapport?kod=2"));
    expect(replace).not.toHaveBeenCalledWith("/rapport/ogiltig");
  });

  it("the script also takes a hash set before the app has started", () => {
    history.replaceState(null, "", "/rapport");
    delete (window as { __rapportToken?: string }).__rapportToken;
    new Function(CLEAR_HASH_SCRIPT)();
    history.pushState(null, "", "/rapport#5.early");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(location.hash).toBe("");
    expect((window as { __rapportToken?: string }).__rapportToken).toBe(
      "5.early",
    );
  });

  it("the script does nothing on other pages", () => {
    history.replaceState(null, "", "/stamboken#section");
    new Function(CLEAR_HASH_SCRIPT)();
    expect(location.hash).toBe("#section");
  });

  const deferred = () => {
    const sent: string[] = [];
    const pending: Record<string, (r: unknown) => void> = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: { body: string }) =>
          new Promise((resolve) => {
            const t = JSON.parse(init.body).token;
            sent.push(t);
            pending[t] = resolve;
          }),
      ),
    );
    return { sent, pending };
  };
  const hashTo = (t: string) =>
    act(async () => {
      history.pushState(null, "", `/rapport#${t}`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
  const good = (herd: string) => ({
    status: 200,
    ok: true,
    json: () => ({ herd }),
  });

  it("runs one exchange at a time: B is not sent before A has answered", async () => {
    replace.mockReset();
    const { sent, pending } = deferred();
    getMine.mockResolvedValue({
      ok: true,
      data: [{ code_id: 2, herd: "M2", herd_name: null, year: 2025 }],
    });
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await waitFor(() => expect(sent).toEqual(["A"]));
    await hashTo("B");
    await act(async () => {}); // time for a wrongly eager second request
    expect(sent).toEqual(["A"]);
    await act(async () => {
      pending.A(good("M1"));
    });
    await waitFor(() => expect(sent).toEqual(["A", "B"]));
    await act(async () => {
      pending.B(good("M2"));
    });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/rapport?kod=2"));
    expect(replace).toHaveBeenCalledTimes(1); // only the latest link navigates
  });

  it("a link replaced while queued is never sent", async () => {
    const { sent, pending } = deferred();
    getMine.mockResolvedValue({ ok: true, data: [] });
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await waitFor(() => expect(sent).toEqual(["A"]));
    await hashTo("B");
    await hashTo("C");
    await act(async () => {
      pending.A(good("M1"));
    });
    await waitFor(() => expect(sent).toEqual(["A", "C"]));
  });

  it("no continuation after unmount", async () => {
    replace.mockReset();
    const { sent, pending } = deferred();
    (window as { __rapportToken?: string }).__rapportToken = "A";
    const { unmount } = render(<LinkGate />);
    await waitFor(() => expect(sent).toEqual(["A"]));
    unmount();
    await act(async () => {
      pending.A({ status: 403, ok: false });
    });
    expect(replace).not.toHaveBeenCalled();
  });

  it("the first exchange survives Strict Mode's effect replay", async () => {
    replace.mockReset();
    const { sent, pending } = deferred();
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(
      <React.StrictMode>
        <LinkGate />
      </React.StrictMode>,
    );
    await waitFor(() => expect(sent).toEqual(["A"]));
    await act(async () => {
      pending.A({ status: 403, ok: false });
    });
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/rapport/ogiltig"),
    );
    expect(sent).toEqual(["A"]); // not sent twice either
  });

  it("a new mount queues behind the exchange of the one before", async () => {
    const { sent, pending } = deferred();
    getMine.mockResolvedValue({ ok: true, data: [] });
    (window as { __rapportToken?: string }).__rapportToken = "A";
    const first = render(<LinkGate />);
    await waitFor(() => expect(sent).toEqual(["A"]));
    first.unmount();
    (window as { __rapportToken?: string }).__rapportToken = "B";
    render(<LinkGate />);
    await act(async () => {});
    expect(sent).toEqual(["A"]);
    await act(async () => {
      pending.A(good("M1"));
    });
    await waitFor(() => expect(sent).toEqual(["A", "B"]));
  });

  it("a request that never answers is aborted after 20 s, shows the retry and lets the next link run", async () => {
    vi.useFakeTimers();
    const { sent } = deferred();
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await act(async () => {});
    expect(sent).toEqual(["A"]);
    const signal = (
      fetch as unknown as {
        mock: { calls: [string, { signal: AbortSignal }][] };
      }
    ).mock.calls[0][1].signal;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(signal.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
    await act(async () => {
      history.pushState(null, "", "/rapport#B");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await act(async () => {});
    expect(sent).toEqual(["A", "B"]);
  });

  it("a getMine that never answers shows the retry too", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(good("M1"))),
    );
    getMine.mockReturnValue(new Promise(() => {}));
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it("nothing continues when the page goes away while the body is read", async () => {
    getMine.mockReset();
    let release: (v: unknown) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          status: 200,
          ok: true,
          json: () => new Promise((r) => (release = r)),
        }),
      ),
    );
    (window as { __rapportToken?: string }).__rapportToken = "A";
    const { unmount } = render(<LinkGate />);
    await act(async () => {});
    unmount();
    await act(async () => {
      release({ herd: "M1" });
    });
    expect(getMine).not.toHaveBeenCalled();
  });
});
