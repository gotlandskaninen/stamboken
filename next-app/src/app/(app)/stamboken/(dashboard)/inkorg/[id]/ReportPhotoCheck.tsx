import Link from "next/link";
import { ProposalChecks } from "@/components/register/RegisterFromCertificate";
import type { CertForm, InboxDetail, InboxDocument } from "../lib";
import styles from "../inkorg.module.css";

// The fields a report photo is checked on, in the certificate form's order and words.
const ROWS: [keyof CertForm, string][] = [
  ["paper_number", "Individnummer"],
  ["paper_certificate", "Intygsnummer"],
  ["name", "Namn"],
  ["sex", "Kön"],
  ["birth_date", "Födelsedatum"],
  ["color", "Färg"],
  ["mother", "Mor"],
  ["father", "Far"],
  ["litter_size", "Antal födda"],
  ["litter_size6w", "Levande i kullen efter 6 veckor"],
];
const SEX: Record<string, string> = { female: "Hona", male: "Hane" };
const NUMBERS: (keyof CertForm)[] = ["paper_number", "mother", "father"]; // never broken at the hyphen
// A value as the table shows it, an individual number in one piece.
const cell = (key: keyof CertForm, value: unknown) =>
  NUMBERS.includes(key) ? (
    <span className={styles.number}>{shown(key, value)}</span>
  ) : (
    shown(key, value)
  );
const shown = (key: keyof CertForm, value: unknown) =>
  value == null || value === ""
    ? "–"
    : key === "sex"
      ? (SEX[String(value)] ?? String(value))
      : String(value);

/**
 * A certificate photo from the yearly report (4b, G5): the member registered
 * the rabbit at once, so the queue sets the image reading beside what was
 * registered, field by field, and marks where they differ: the reading's own
 * avviker against the rabbit, or a value read before the rabbit was saved
 * that is not the registered one. What was unsure says so, and the reading's
 * checks follow. The item's handler closes it with "Stämmer" or "Rättat", and
 * can have the photo read again.
 */
export function ReportPhotoCheck({
  doc,
  registered,
  canCheck = false,
  pending = false,
  onCheck,
  onReinterpret,
}: {
  doc: InboxDocument;
  registered: NonNullable<InboxDetail["registered"]>;
  /** The item's handler, the item taken and the photo not checked yet. */
  canCheck?: boolean;
  pending?: boolean;
  onCheck?: (outcome: "stammer" | "rattat") => void;
  onReinterpret?: () => void;
}) {
  const fields = doc.proposal?.fields ?? {};
  const number = String(registered.paper_number ?? "");
  return (
    <div className={styles.card}>
      <h2 className={styles.cardTitle}>Intyget mot registreringen</h2>
      <p className={styles.muted}>
        Uppfödaren registrerade{" "}
        <Link href={`/stamboken/individ/${encodeURIComponent(number)}`}>
          {number}
        </Link>{" "}
        från fotot i årsrapporten. Jämför fotot och tolkningen med det som
        registrerades.
      </p>
      {doc.interpretation_status === "vantar" && (
        <p className={styles.muted}>
          Fotot tolkas. Tolkningen kommer om några minuter; ladda om sidan då.
        </p>
      )}
      {doc.interpretation_status === "misslyckad" && (
        <p className={styles.muted}>
          Fotot gick inte att tolka. Jämför fotot med registreringen.
        </p>
      )}
      <table
        className={`${styles.table} ${styles.photoCheck}`}
        aria-label="Tolkningen och registreringen"
      >
        <thead>
          <tr>
            <th scope="col">Fält</th>
            <th scope="col">Tolkningen</th>
            <th scope="col">Registrerat</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label]) => {
            const read = fields[key];
            const fromPhoto = read ? (read.value ?? read.read ?? null) : null;
            // `read` is the paper's own text ("250510", "Hona"): only a value is compared
            const differs =
              read?.source === "avviker" ||
              (read?.value != null &&
                registered[key] != null &&
                String(read.value).trim().toUpperCase() !==
                  String(registered[key]).trim().toUpperCase());
            return (
              <tr key={key} data-differs={differs || undefined}>
                <th scope="row">{label}</th>
                <td>
                  {cell(key, fromPhoto)}
                  {(read?.source === "osäker" ||
                    read?.source === "härlett") && (
                    <span className={styles.muted}> ({read.source})</span>
                  )}
                </td>
                <td>
                  {cell(key, registered[key])}
                  {differs && <strong> Avviker</strong>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {doc.proposal && <ProposalChecks checks={doc.proposal.checks} />}
      {canCheck && (
        <>
          <div className={styles.submitRow}>
            <button
              type="button"
              className="sb-btn"
              disabled={pending}
              onClick={() => onCheck?.("stammer")}
            >
              Stämmer
            </button>
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              disabled={pending}
              onClick={() => onCheck?.("rattat")}
            >
              Rättat
            </button>
            {doc.interpretation_status !== "av" && (
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                disabled={pending || doc.interpretation_status === "vantar"}
                onClick={onReinterpret}
              >
                Tolka igen
              </button>
            )}
          </div>
          <p className={styles.muted}>
            Rättat: du har ändrat kaninen i Stamboken så att den stämmer med
            intyget. Båda stänger ärendet.
          </p>
        </>
      )}
    </div>
  );
}
