import Link from "next/link";
import type { InboxDetail } from "../lib";

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
  const notSaved = Array.isArray(arrived.not_saved) ? arrived.not_saved : [];
  return (
    <>
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
          <dd>{notSaved.join(", ")}</dd>
        </>
      )}
    </>
  );
}
