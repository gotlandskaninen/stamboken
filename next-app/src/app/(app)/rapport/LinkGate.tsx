"use client";

import React from "react";
import { useRouter } from "next/navigation";
import styles from "../stamboken/(dashboard)/arsrapport/arsrapport.module.css";
import { getMine } from "./actions";
import { takeToken } from "./clearHash";

// The personal link is /rapport#<token>. A browser never sends what follows #, so the server cannot see it: this
// component reads it, takes it out of the address bar at once (errorHandling.ts records location.href), posts it to
// the exchange from the browser, so that the session cookie is set on the site's own origin, and lets the server page
// render again with the session.
const NET_TEXT = "Det gick inte att nå servern. Försök igen.";
const EXPIRED_TEXT =
  "Sidan stängdes efter två timmar av säkerhetsskäl. Öppna länken i mejlet igen. Det du fyllt i är sparat.";
// The manager's test mail links to /rapport#prov: the link form is tried in a real mail client, nothing is opened.
const TEST_LINK_TEXT =
  "Provlänken fungerar. I det riktiga mejlet öppnar länken besättningens årsrapport.";
const COOKIES_TEXT =
  "Din webbläsare tog inte emot inloggningen. Öppna länken i en vanlig webbläsare, till exempel Chrome eller Safari.";

// "ute": no code session (never opened, or ended after two hours). "fel": the API could not be reached.
export type Missing = "ute" | "fel";

const Skeleton = () => (
  <div className={styles.root} aria-busy="true">
    <h1 className={styles.title}>Årsrapport</h1>
    {[0, 1, 2].map((i) => (
      <div key={i} className={styles.skeleton} />
    ))}
  </div>
);

const Message = ({ text, retry }: { text: string; retry?: () => void }) => (
  <div className={styles.root}>
    <h1 className={styles.title}>Årsrapport</h1>
    <p className={styles.lead} role="status">
      {text}
    </p>
    {retry && (
      <button type="button" className={`sb-btn ${styles.btn}`} onClick={retry}>
        Försök igen
      </button>
    )}
  </div>
);

// One exchange at a time and only the latest requested one may change the page: each answer sets a session cookie, so a
// second exchange sent before the first has answered could be overwritten by the first one's late Set-Cookie. The queue
// is module state, so it covers every mount of the gate in the tab. A request that never answers is aborted after
// 20 s (its response, Set-Cookie included, is dropped), which releases the queue.
const EXCHANGE_TIMEOUT_MS = 20_000;
let latest = 0;
let queue: Promise<void> = Promise.resolve();
export function resetLinkQueue() {
  latest = 0;
  queue = Promise.resolve();
}

// `work` must settle within the time limit, or it counts as a failure; the controller, when given, is aborted then.
function bounded<T>(work: Promise<T>, controller?: AbortController) {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      controller?.abort();
      reject(new Error("timeout"));
    }, EXCHANGE_TIMEOUT_MS);
    Promise.resolve(work)
      .then(resolve, reject)
      .finally(() => clearTimeout(timer));
  });
}

export function LinkGate({
  missing,
  children,
}: {
  missing?: Missing;
  children?: React.ReactNode;
}) {
  const router = useRouter();
  const [navigating, startTransition] = React.useTransition();
  const [pending, setPending] = React.useState(false);
  const [phase, setPhase] = React.useState<
    "start" | "idle" | "cookies" | "net" | "test"
  >("start");
  const started = React.useRef(false);
  const token = React.useRef("");

  const alive = React.useRef(true); // false after unmount: nothing continues then
  React.useEffect(() => {
    alive.current = true; // Strict Mode replays the effect: the first exchange must survive it
    return () => {
      alive.current = false;
    };
  }, []);

  const run = React.useCallback(
    async (link: string, mine: number) => {
      const current = () => alive.current && mine === latest;
      if (!current()) return; // replaced while it waited its turn
      const controller = new AbortController();
      try {
        const res = await bounded(
          fetch("/api/v2/rapport/oppna", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: link }),
            signal: controller.signal,
          }),
          controller,
        );
        if (!current()) return;
        if (res.status === 403) return router.replace("/rapport/ogiltig");
        if (!res.ok) throw new Error(String(res.status));
        const { herd } = (await bounded(res.json(), controller)) as {
          herd: string;
        };
        if (!current()) return;
        const codes = await bounded(getMine());
        if (!current()) return;
        if (!codes.ok) throw new Error(String(codes.problem.status));
        const entry = codes.data.find((m) => m.herd === herd);
        // The link was good but the cookie did not stay: the browser blocks it.
        if (!entry) return setPhase("cookies");
        token.current = "";
        setPhase("idle");
        // The server page renders again; the placeholder stays until it has.
        startTransition(() => {
          router.replace(`/rapport?kod=${entry.code_id}`);
          router.refresh(); // the same address again does not render again by itself
        });
      } catch {
        if (current()) setPhase("net");
      } finally {
        if (current()) setPending(false);
      }
    },
    [router],
  );

  const open = React.useCallback(
    (link: string) => {
      const mine = ++latest;
      token.current = link; // kept for "Försök igen"
      setPending(true);
      setPhase("idle");
      queue = queue.then(() => run(link, mine));
    },
    [run],
  );

  const begin = React.useCallback(
    (t: string) => {
      if (t === "prov") {
        latest++; // an exchange still running must not replace the test text
        setPending(false);
        return setPhase("test");
      }
      open(t);
    },
    [open],
  );

  React.useEffect(() => {
    // A link opened inside the page that is already open only changes the hash: nothing reloads.
    const onHash = () => {
      const t = takeToken();
      if (t) begin(t);
    };
    window.addEventListener("hashchange", onHash);
    if (!started.current) {
      started.current = true; // Strict Mode runs effects twice; the first token is taken once
      const t = takeToken();
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the hash exists only in the browser
      if (t) begin(t);
      else setPhase("idle");
    }
    return () => window.removeEventListener("hashchange", onHash);
  }, [begin]);

  if (phase === "test") return <Message text={TEST_LINK_TEXT} />;
  if (phase === "cookies") return <Message text={COOKIES_TEXT} />;
  if (phase === "net")
    return <Message text={NET_TEXT} retry={() => open(token.current)} />;
  if (pending || navigating || (phase === "start" && missing))
    return <Skeleton />;
  if (missing === "ute") return <Message text={EXPIRED_TEXT} />;
  if (missing === "fel") return <Message text={NET_TEXT} />;
  return <>{children}</>;
}
