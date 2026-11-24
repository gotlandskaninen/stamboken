import Link from "next/link";
import type { TFunction } from "i18next";
import { formatTime } from "@/lib/inkorg";
import type { InboxDetail, InboxEvent } from "../lib";
import styles from "../inkorg.module.css";

type MailProps = { item: InboxDetail; paneT?: TFunction };

export function MailThread({ item, paneT }: MailProps) {
  const arrived = item.events.find((e) => e.kind === "inkommen");
  const mail = item.kind === "mail" || item.kind === "meddelande";
  const messages = [
    {
      id: 0,
      label: mail
        ? (paneT?.("queueDetail.mail") ?? "Mejl")
        : (paneT?.("queue.kinds.meddelande") ?? "Meddelande"),
      subject: paneT ? null : arrived?.detail?.subject,
      text: item.message,
    },
    ...item.events
      .filter((e) => e.kind === "svar")
      .map((e) => ({
        id: e.id,
        label:
          paneT?.("queueDetail.reply", { date: formatTime(e.at) }) ??
          `Svar · ${formatTime(e.at)}`,
        subject: e.detail?.subject,
        text: e.detail?.text,
      })),
  ].filter((m) => m.subject || m.text);
  if (!messages.length) return null;
  const Heading = paneT ? "h3" : "h2";
  return (
    <section
      aria-label={paneT?.("queue.kinds.meddelande") ?? "Meddelande"}
      className={
        paneT ? styles.caseMail : `sb-card ${styles.card} ${styles.mailThread}`
      }
    >
      {messages.map(({ id, label, subject, text }) => (
        <article key={id}>
          <Heading className={paneT ? undefined : styles.cardTitle}>
            {label}
          </Heading>
          {typeof subject === "string" && (
            <dl>
              <dt className="sb-meta">
                {paneT?.("queueDetail.subject") ?? "Ämne"}
              </dt>
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
export function SenderUnconfirmed({ item, paneT }: MailProps) {
  if (item.sender_authenticated !== false) return null;
  return (
    <>
      {" "}
      <strong>
        {paneT?.("queueDetail.unverified") ?? "Avsändaren är inte bekräftad"}
      </strong>
      <br />
      <span className="sb-meta">
        {paneT?.("queueDetail.noEmail") ?? "Inget mejl skickas till adressen."}
      </span>
    </>
  );
}

/** Files omitted from one incoming email, including older events that only kept names. */
export function skippedFiles({ kind, detail }: InboxEvent): string[] {
  if (kind !== "inkommen" && kind !== "svar") return [];
  if (Array.isArray(detail?.not_saved_reasons))
    return detail.not_saved_reasons.map(
      ({ name, reason }) => `${name} – ${reason}`,
    );
  return Array.isArray(detail?.not_saved) ? detail.not_saved : [];
}

export function RabbitLinks({ numbers }: { numbers: string[] }) {
  return numbers.map((number) => (
    <div key={number}>
      <Link href={`/stamboken/individ/${encodeURIComponent(number)}`}>
        {number}
      </Link>
    </div>
  ));
}

export function RelatedCase({ item, paneT }: MailProps) {
  const maybe = item.events.find((e) => e.kind === "inkommen")?.detail
    ?.maybe_item;
  return typeof maybe === "number" ? (
    <>
      <dt>{paneT?.("queueDetail.related") ?? "Gäller kanske"}</dt>
      <dd>
        <Link prefetch={false} href={`/stamboken/inkorg/${maybe}`}>
          {paneT?.("queueDetail.caseNumber", { id: maybe }) ??
            `Ärende ${maybe}`}
        </Link>
      </dd>
    </>
  ) : null;
}

export function MailFacts({ item }: { item: InboxDetail }) {
  const mentioned = item.mentioned_individuals ?? [];
  const notSaved = item.events.flatMap(skippedFiles);
  return (
    <>
      {mentioned.length > 0 && (
        <>
          <dt>Nämnda kaniner</dt>
          <dd>
            <RabbitLinks numbers={mentioned} />
          </dd>
        </>
      )}
      <RelatedCase item={item} />
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
