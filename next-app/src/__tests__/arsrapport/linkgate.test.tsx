import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
const goTo = vi.fn();
vi.mock("@/app/(app)/rapport/navigate", () => ({
  goTo: (url: string) => goTo(url),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
}));
// The code list: what the stubbed /mina request answers with. `deferred` and the inline stubs answer /oppna only.
const getMine = vi.fn();
const mina = (data: unknown) => ({ status: 200, ok: true, json: () => data });
const isMina = (url: string) => url === "/api/v2/rapport/mina";
// Wraps the stubbed fetch: /mina goes to getMine, everything else (the exchange) to the stub.
const routeMina = () => {
  const inner = globalThis.fetch as unknown as (
    url: string,
    init: { body: string; signal: AbortSignal },
  ) => Promise<unknown>;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: { body: string; signal: AbortSignal }) =>
      isMina(url) ? getMine(init) : inner(url, init),
    ),
  );
};

import { LinkGate, resetLinkQueue } from "@/app/(app)/rapport/LinkGate";
import { CLEAR_HASH_SCRIPT } from "@/app/(app)/rapport/clearHash";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  goTo.mockReset();
  getMine.mockReset();
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
    routeMina();
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
    routeMina();
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
    routeMina();
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
    getMine.mockResolvedValue(
      mina([{ code_id: 2, herd: "M2", herd_name: null, year: 2025 }]),
    );
    (window as { __rapportToken?: string }).__rapportToken = "A";
    routeMina();
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
    await waitFor(() => expect(goTo).toHaveBeenCalledWith("/rapport?kod=2"));
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

  it("the script keeps a token whose hash is rewritten between popstate and hashchange", () => {
    history.replaceState(null, "", "/rapport?kod=2");
    delete (window as { __rapportToken?: string }).__rapportToken;
    new Function(CLEAR_HASH_SCRIPT)();
    history.pushState(null, "", "/rapport?kod=2#6.inpage");
    window.dispatchEvent(new PopStateEvent("popstate"));
    // A React commit before hashchange: Next writes its canonical address back, without the hash.
    history.replaceState(null, "", "/rapport?kod=2");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(location.hash).toBe("");
    expect((window as { __rapportToken?: string }).__rapportToken).toBe(
      "6.inpage",
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
    routeMina();
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
    getMine.mockResolvedValue(
      mina([{ code_id: 2, herd: "M2", herd_name: null, year: 2025 }]),
    );
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
    await waitFor(() => expect(goTo).toHaveBeenCalledWith("/rapport?kod=2"));
    expect(goTo).toHaveBeenCalledTimes(1); // only the latest link navigates
    expect(replace).not.toHaveBeenCalled();
  });

  it("a link replaced while queued is never sent", async () => {
    const { sent, pending } = deferred();
    getMine.mockResolvedValue(mina([]));
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
    getMine.mockResolvedValue(mina([]));
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

  it("a code list that never answers shows the retry too", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(good("M1"))),
    );
    getMine.mockReturnValue(new Promise(() => {}));
    (window as { __rapportToken?: string }).__rapportToken = "A";
    routeMina();
    render(<LinkGate />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it("nothing continues when the page goes away while the body is read", async () => {
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
    routeMina();
    const { unmount } = render(<LinkGate />);
    await act(async () => {});
    unmount();
    await act(async () => {
      release({ herd: "M1" });
    });
    expect(getMine).not.toHaveBeenCalled();
  });

  it("a hash change is exchanged whichever listener sees it first", async () => {
    // The root script's listener is registered before LinkGate mounts, as in the served page.
    history.replaceState(null, "", "/rapport");
    delete (window as { __rapportToken?: string }).__rapportToken;
    new Function(CLEAR_HASH_SCRIPT)();
    const { sent, pending } = deferred();
    getMine.mockResolvedValue(
      mina([{ code_id: 1, herd: "M1", herd_name: null, year: 2025 }]),
    );
    render(<LinkGate missing="ute" />);
    await screen.findByText(/Sidan stängdes efter två timmar/);
    await act(async () => {
      history.pushState(null, "", "/rapport#9.late"); // the root listener clears it first
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await waitFor(() => expect(sent).toEqual(["9.late"]));
    await act(async () => {
      pending["9.late"](good("M1"));
    });
    await waitFor(() => expect(goTo).toHaveBeenCalledWith("/rapport?kod=1"));
    expect(location.hash).toBe("");
  });

  it("a code list that stalls is aborted, and the retry gets through", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(good("M1"))),
    );
    routeMina();
    getMine
      .mockImplementationOnce(
        (init: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signals.push(init.signal);
            init.signal.addEventListener("abort", () =>
              reject(new Error("aborted")),
            );
          }),
      )
      .mockResolvedValueOnce(
        mina([{ code_id: 5, herd: "M1", herd_name: null, year: 2025 }]),
      );
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(true);
    await act(async () => {
      screen.getByRole("button", { name: "Försök igen" }).click();
    });
    await act(async () => {});
    expect(goTo).toHaveBeenCalledWith("/rapport?kod=5");
  });

  it("a code list body that stalls is aborted too", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(good("M1"))),
    );
    routeMina();
    let signal: AbortSignal | undefined;
    getMine.mockImplementation((init: { signal: AbortSignal }) => {
      signal = init.signal;
      return Promise.resolve({
        status: 200,
        ok: true,
        json: () => new Promise(() => {}),
      });
    });
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it("an exchange body that stalls is aborted after 20 s and shows the retry", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        status: 200,
        ok: true,
        json: () => new Promise(() => {}),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    (window as { __rapportToken?: string }).__rapportToken = "A";
    render(<LinkGate />);
    await act(async () => {});
    const signal = (
      fetchMock.mock.calls as unknown as [string, { signal: AbortSignal }][]
    )[0][1].signal;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(signal.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });
});
