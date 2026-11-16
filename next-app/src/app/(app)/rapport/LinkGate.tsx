"use client";

import React from "react";
import { useRouter } from "next/navigation";
import styles from "../stamboken/(dashboard)/arsrapport/arsrapport.module.css";
import { getMine } from "./actions";

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

  const open = React.useCallback(async () => {
    setPending(true);
    setPhase("idle");
    try {
      const res = await fetch("/api/v2/rapport/oppna", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.current }),
      });
      if (res.status === 403) return router.replace("/rapport/ogiltig");
      if (!res.ok) throw new Error(String(res.status));
      const { herd } = (await res.json()) as { herd: string };
      const mine = await getMine();
      if (!mine.ok) throw new Error(String(mine.problem.status));
      const entry = mine.data.find((m) => m.herd === herd);
      // The link was good but the cookie did not stay: the browser blocks it.
      if (!entry) return setPhase("cookies");
      token.current = "";
      setPhase("idle");
      // The server page renders again; the placeholder stays until it has.
      startTransition(() => router.replace(`/rapport?kod=${entry.code_id}`));
    } catch {
      setPhase("net");
    } finally {
      setPending(false);
    }
  }, [router]);

  React.useEffect(() => {
    if (started.current) return; // Strict Mode runs effects twice; the token is read once
    started.current = true;
    if (location.hash) {
      token.current = location.hash.slice(1);
      history.replaceState(null, "", "/rapport"); // before anything else, the token must leave the address bar
    }
    if (token.current === "prov") {
      token.current = "";
      setPhase("test");
      return;
    }
    if (token.current) {
      void open();
      return;
    }
    setPhase("idle");
  }, [open]);

  if (phase === "test") return <Message text={TEST_LINK_TEXT} />;
  if (phase === "cookies") return <Message text={COOKIES_TEXT} />;
  if (phase === "net") return <Message text={NET_TEXT} retry={open} />;
  if (pending || navigating || (phase === "start" && missing))
    return <Skeleton />;
  if (missing === "ute") return <Message text={EXPIRED_TEXT} />;
  if (missing === "fel") return <Message text={NET_TEXT} />;
  return <>{children}</>;
}
