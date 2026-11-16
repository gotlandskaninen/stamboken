import { redirect } from "next/navigation";
import { LinkGate, type Missing } from "./LinkGate";
import {
  dryRun,
  getGenebankHerds,
  getMine,
  getReport,
  reportPurchase,
  saveDraft,
  submitReport,
  withdrawReport,
} from "./actions";
import { ReportForm } from "../stamboken/(dashboard)/arsrapport/ReportForm";
import styles from "../stamboken/(dashboard)/arsrapport/arsrapport.module.css";

export const dynamic = "force-dynamic";

const actions = {
  saveDraft,
  dryRun,
  submitReport,
  withdrawReport,
  reportPurchase,
};

// The page behind a member's personal link. The server renders from the code session in the cookie; LinkGate, in the
// browser, first turns a link's #token into that session (the server never sees what follows #).
export default async function RapportPage({
  searchParams,
}: {
  searchParams: Promise<{ kod?: string }>;
}) {
  const { kod } = await searchParams;
  const wanted = /^\d{1,18}$/.test(kod ?? "") ? Number(kod) : null;
  const mine = await getMine();
  if (!mine.ok)
    return <LinkGate missing={mine.problem.status === 401 ? "ute" : "fel"} />;

  const entries = mine.data;
  const entry =
    wanted !== null
      ? entries.find((m) => m.code_id === wanted)
      : entries.length === 1
        ? entries[0]
        : undefined;
  if (wanted === null && entries.length > 1)
    return (
      <LinkGate>
        <div className={styles.root}>
          <h1 className={styles.title}>Välj besättning</h1>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {entries.map((m) => (
              <li key={m.code_id} style={{ margin: "0 0 12px" }}>
                <a
                  href={`/rapport?kod=${m.code_id}`}
                  className={`sb-btn ${styles.btn}`}
                >
                  {m.herd}
                  {m.herd_name ? ` · ${m.herd_name}` : ""}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </LinkGate>
    );
  if (!entry) return <LinkGate missing="ute" />;

  const report = await getReport(entry.herd, entry.year);
  if (!report.ok) {
    const { status, extensions } = report.problem;
    if (
      (status === 403 && extensions?.code === "lank_ogiltig") ||
      status === 404
    )
      redirect("/rapport/ogiltig");
    const missing: Missing = status === 401 ? "ute" : "fel";
    return <LinkGate missing={missing} />;
  }
  return (
    <LinkGate>
      <ReportForm
        key={`${entry.herd}-${entry.year}`}
        link
        env="prod"
        view={report.data}
        actions={{
          ...actions,
          getGenebankHerds: getGenebankHerds.bind(null, entry.herd, entry.year),
        }}
        stickyTop={0}
      />
    </LinkGate>
  );
}
