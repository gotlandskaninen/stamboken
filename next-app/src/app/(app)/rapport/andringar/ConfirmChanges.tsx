"use client";

import React from "react";
import styles from "../../stamboken/(dashboard)/arsrapport/arsrapport.module.css";
import { fmtDate } from "../../stamboken/(dashboard)/arsrapport/lib";
import { takeToken } from "../clearHash";

const labels = {
  adress: "Adress",
  telefon: "Telefon",
  epost: "E-post",
  konto: "Konto för stödet",
  publicering: "Svar om Koharen",
};

type Change = {
  id: number;
  falt: keyof typeof labels;
  state: "vantar" | "bekraftad" | "forfallen" | "aterkallad" | "inte_jag";
  nu: string | null;
  nytt: string | null;
  datum: string;
};
type View = { herd: string; changes: Change[]; version: string };
type Confirmation = { version: string; konto: boolean };

function changeDetails({ state, nu, nytt, datum }: Change) {
  switch (state) {
    case "vantar":
      return (
        <>
          <div>Nu: {nu ?? "Inget"}</div>
          <div>Nytt: {nytt ?? "Inget"}</div>
          <div className={styles.meta}>Bekräfta senast {fmtDate(datum)}.</div>
        </>
      );
    case "bekraftad":
      return `Redan bekräftat ${fmtDate(datum)}`;
    case "forfallen":
      return `Gällde till ${fmtDate(datum)}`;
    case "aterkallad":
      return "Gäller inte längre";
    case "inte_jag":
      return "Det var inte jag";
  }
}

export function ConfirmChanges() {
  const token = React.useRef<string | null>(null);
  const [view, setView] = React.useState<View | null>(null);
  const [konto, setKonto] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [retry, setRetry] = React.useState(false);
  const [message, setMessage] = React.useState("");

  const request = React.useCallback(
    async (
      path: "" | "/bekrafta" | "/inte-jag" = "",
      confirmation?: Confirmation,
    ) => {
      const post = (suffix: string, fields?: Confirmation) =>
        fetch(`/api/v2/rapport/andringar${suffix}`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: token.current, ...fields }),
        });

      setBusy(true);
      setRetry(false);
      setMessage("");
      try {
        let response = await post(path, confirmation);
        const conflict = response.status === 409;
        if (conflict) {
          setMessage((await response.json()).detail);
          response = await post("");
        }
        if (!response.ok) {
          if (
            response.status === 403 &&
            (await response.json()).code === "lank_ogiltig"
          ) {
            setView(null);
            setMessage(
              "Länken gäller inte längre. Har du fått ett nyare mejl från Stamboken? Använd länken i det.",
            );
            return;
          }
          throw new Error();
        }

        const next: View = await response.json();
        setView(next);
        setKonto(false);
        if (conflict) return;
        if (path === "/bekrafta") {
          const kontoVantar = next.changes.some(
            (c) => c.falt === "konto" && c.state === "vantar",
          );
          setMessage(
            "Klart. Ändringarna är sparade." +
              (kontoVantar
                ? " Kontot ändras inte förrän du har kryssat i rutan."
                : ""),
          );
        } else if (path === "/inte-jag") {
          setMessage(
            "Ändringarna är stoppade. Genbanksansvarig ser att det inte var du.",
          );
        }
      } catch {
        setView(null);
        setRetry(true);
        setMessage("Det gick inte att nå servern. Försök igen.");
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  React.useEffect(() => {
    if (token.current !== null) return;
    token.current = takeToken();
    if (token.current) void request();
    else setMessage("Öppna länken i mejlet igen.");
  }, [request]);

  const pending = view?.changes.filter((c) => c.state === "vantar") ?? [];
  return (
    <div className={styles.root}>
      <h1 className={styles.title}>Bekräfta dina ändringar</h1>
      {view && (
        <p className={styles.lead}>
          Ändringarna kom med årsrapporten för {view.herd}. De gäller först när
          du har bekräftat dem.
        </p>
      )}
      {(message || !view) && (
        <p role="status" className={retry ? styles.errorText : styles.lead}>
          {message || "Hämtar ändringarna …"}
        </p>
      )}
      {retry && (
        <button
          type="button"
          className={`sb-btn ${styles.btn}`}
          onClick={() => request()}
        >
          Försök igen
        </button>
      )}
      {view && (
        <ul className={styles.cardList} style={{ overflowWrap: "anywhere" }}>
          {view.changes.map((change) => (
            <li key={change.id} className={`sb-card-flat ${styles.row}`}>
              <strong>{labels[change.falt]}</strong>
              <div>{changeDetails(change)}</div>
            </li>
          ))}
        </ul>
      )}
      {pending.some((c) => c.falt === "epost") && (
        <p className={styles.lead}>
          Den gamla e-postadressen får ett meddelande om bytet. Den nya gäller
          för inloggning efter sju dagar.
        </p>
      )}
      {pending.some((c) => c.falt === "konto") && (
        <label className={styles.line} style={{ minHeight: 48 }}>
          <input
            type="checkbox"
            checked={konto}
            disabled={busy}
            onChange={(e) => setKonto(e.target.checked)}
          />
          Jag bekräftar det nya kontot för stödet.
        </label>
      )}
      {view && pending.length > 0 && (
        <div className={styles.line}>
          <button
            type="button"
            className={`sb-btn ${styles.btn}`}
            disabled={busy}
            onClick={() =>
              request("/bekrafta", { version: view.version, konto })
            }
          >
            Bekräfta
          </button>
          <button
            type="button"
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            disabled={busy}
            onClick={() => request("/inte-jag")}
          >
            Det var inte jag
          </button>
        </div>
      )}
    </div>
  );
}
