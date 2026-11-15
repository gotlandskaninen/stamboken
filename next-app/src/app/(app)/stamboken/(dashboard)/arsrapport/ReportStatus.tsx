import React from "react";
import Link from "next/link";
import { CONFLICT_TEXT, TIMEOUT_TEXT } from "./lib";
import styles from "./arsrapport.module.css";

// The state card of the report page (design brief section 6). Sparat is never
// green: the "done" tone belongs to a submitted report alone.
export type StatusKind =
  | { kind: "saved"; at: string | null; changing: boolean }
  | { kind: "saving" }
  | { kind: "offline"; device: "telefonen" | "webbläsaren" }
  | { kind: "loggedout"; href: string }
  | { kind: "conflict" }
  | { kind: "sending" }
  | { kind: "timeout" }
  | { kind: "withdrawn"; date: string }
  | { kind: "closed" }
  | { kind: "late"; deadline: string }
  | { kind: "deadline"; deadline: string }
  | { kind: "editor"; herd: string }
  | { kind: "submitted"; text: string };

const TONE: Record<StatusKind["kind"], string> = {
  saved: "",
  saving: "",
  offline: styles.warning,
  loggedout: styles.warning,
  conflict: styles.info,
  sending: "",
  timeout: styles.warning,
  withdrawn: styles.warning,
  closed: styles.info,
  late: styles.info,
  deadline: "",
  editor: styles.info,
  submitted: styles.done,
};

function text(s: StatusKind): React.ReactNode {
  switch (s.kind) {
    case "saved":
      return s.changing
        ? `Ändringar som inte är inskickade${s.at ? ` (sparade ${s.at})` : ""}. Den inskickade rapporten gäller tills du skickar.`
        : s.at
          ? `Inte inskickad. Det du fyllt i är sparat (senast ${s.at}).`
          : "Inte inskickad. Det du fyller i sparas medan du skriver.";
    case "saving":
      return "Sparar …";
    case "offline":
      return `Inte sparat än, ingen anslutning. Det du fyllt i finns kvar i ${s.device}.`;
    case "loggedout":
      return (
        <>
          Du har loggats ut. <Link href={s.href}>Logga in igen</Link>. Det du
          fyllt i finns kvar i webbläsaren.
        </>
      );
    case "conflict":
      return `${CONFLICT_TEXT}. Vi har läst in den senaste.`;
    case "sending":
      return "Skickar…";
    case "timeout":
      return TIMEOUT_TEXT;
    case "withdrawn":
      return `Dragen tillbaka ${s.date}. Inte inskickad. Det du fyllt i är sparat.`;
    case "closed":
      return "Rundan är stängd. Kontakta genbanksansvarig om något behöver ändras.";
    case "late":
      return `Sista dag för stödet var ${s.deadline}. Rapportera ändå, så räknas dina kaniner.`;
    case "deadline":
      return `Sista dag för stödet är ${s.deadline}.`;
    case "editor":
      return `Du ser ${s.herd}:s rapport som genbanksansvarig.`;
    case "submitted":
      return s.text;
  }
}

export function ReportStatus({
  status,
  children,
}: {
  status: StatusKind;
  children?: React.ReactNode;
}) {
  const urgent = status.kind === "offline" || status.kind === "timeout";
  return (
    <div
      className={`${styles.status} ${TONE[status.kind]}`}
      role={urgent ? "alert" : "status"}
    >
      <p>{text(status)}</p>
      {children}
    </div>
  );
}
