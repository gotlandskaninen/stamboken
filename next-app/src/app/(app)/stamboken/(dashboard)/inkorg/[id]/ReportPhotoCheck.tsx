import Link from "next/link";
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
const shown = (key: keyof CertForm, value: unknown) =>
  value == null || value === ""
    ? "–"
    : key === "sex"
      ? (SEX[String(value)] ?? String(value))
      : String(value);

/**
 * A certificate photo from the yearly report (4b, G5): the member registered
 * the rabbit at once, so the queue sets the image reading beside what was
 * registered, field by field, and marks where they differ.
 */
export function ReportPhotoCheck({
  doc,
  registered,
}: {
  doc: InboxDocument;
  registered: NonNullable<InboxDetail["registered"]>;
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
        className={styles.table}
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
            const differs =
              fromPhoto != null &&
              registered[key] != null &&
              String(fromPhoto).trim().toUpperCase() !==
                String(registered[key]).trim().toUpperCase();
            return (
              <tr key={key} data-differs={differs || undefined}>
                <th scope="row">{label}</th>
                <td>{shown(key, fromPhoto)}</td>
                <td>
                  {shown(key, registered[key])}
                  {differs && <strong> Avviker</strong>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
