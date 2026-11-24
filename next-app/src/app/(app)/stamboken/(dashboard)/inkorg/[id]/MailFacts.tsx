import Link from "next/link";
import { formatTime } from "@/lib/inkorg";
import type { InboxDetail } from "../lib";
import styles from "../inkorg.module.css";

export function MailThread({ item }: { item: InboxDetail }) {
  const arrived = item.events.find((e) => e.kind === "inkommen");
  const messages = [
    {
      id: 0,
      label:
        item.kind === "mail" || item.kind === "meddelande"
          ? "Mejl"
          : "Meddelande",
      subject: arrived?.detail?.subject,
      text: item.message,
    },
    ...item.events
      .filter((e) => e.kind === "svar")
      .map((e) => ({
        id: e.id,
        label: `Svar från uppfödaren · ${formatTime(e.at)}`,
        subject: e.detail?.subject,
        text: e.detail?.text,
      })),
  ].filter((m) => m.subject || m.text);
  if (!messages.length) return null;
  return (
    <section
      aria-label="Meddelande"
      className={`sb-card ${styles.card} ${styles.mailThread}`}
    >
      {messages.map(({ id, label, subject, text }) => (
        <article key={id}>
          <h2 className={styles.cardTitle}>{label}</h2>
          {typeof subject === "string" && (
            <dl>
              <dt className="sb-meta">Ämne</dt>
              <dd className="sb-h5">{subject}</dd>
            </dl>
          )}
          {typeof text === "string" && <p>{text}</p>}
        </article>
      ))}
    </section>
  );
}

/** Beside the sender address of a mail whose sender could not be confirmed. */
export function SenderUnconfirmed({ item }: { item: InboxDetail }) {
  if (item.sender_authenticated !== false) return null;
  return (
    <>
      {" "}
      <strong>Avsändaren är inte bekräftad</strong>
      <br />
      <span className="sb-meta">Inget mejl skickas till adressen.</span>
    </>
  );
}

/**
 * What a mailed item's "inkommen" event says beside its documents: the case a
 * reply from someone else may be about, and the files that were not stored.
 */
export function MailFacts({ item }: { item: InboxDetail }) {
  const arrived = item.events.find((e) => e.kind === "inkommen")?.detail ?? {};
  const maybe =
    typeof arrived.maybe_item === "number" ? arrived.maybe_item : null;
  const notSaved = item.events.flatMap(({ kind, detail }) => {
    if (kind !== "inkommen" && kind !== "svar") return [];
    if (Array.isArray(detail?.not_saved_reasons))
      return detail.not_saved_reasons.map(
        ({ name, reason }) => `${name} – ${reason}`,
      );
    return Array.isArray(detail?.not_saved) ? detail.not_saved : [];
  });
  return (
    <>
      {item.mentioned_individuals.length > 0 && (
        <>
          <dt>Nämnda kaniner</dt>
          <dd>
            {item.mentioned_individuals.map((number) => (
              <div key={number}>
                <Link href={`/stamboken/individ/${encodeURIComponent(number)}`}>
                  {number}
                </Link>
              </div>
            ))}
          </dd>
        </>
      )}
      {maybe !== null && (
        <>
          <dt>Gäller kanske</dt>
          <dd>
            <Link href={`/stamboken/inkorg/${maybe}`}>Ärende {maybe}</Link>
          </dd>
        </>
      )}
      {notSaved.length > 0 && (
        <>
          <dt>Sparades inte</dt>
          <dd>
            {notSaved.map((file, index) => (
              <div key={index}>{file}</div>
            ))}
          </dd>
        </>
      )}
    </>
  );
}
