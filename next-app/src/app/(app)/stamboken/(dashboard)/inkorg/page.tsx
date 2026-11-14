import Link from "next/link";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { fetchHandlers, requireQueueWorker } from "@/lib/inkorg-server";
import { Masthead } from "@/components/shell/Masthead";
import { GmailAlarm } from "./GmailAlarm";
import { AssignHerd, RowActions } from "./QueueControls";
import {
  CLOSED_STATES,
  itemActions,
  kindLabel,
  KIND_LABEL,
  manages,
  OPEN_STATES,
  people,
  STATE_LABEL,
  waited,
  type Person,
  type QueueList,
} from "./lib";
import styles from "./inkorg.module.css";

export const dynamic = "force-dynamic";

const PATH = "/stamboken/inkorg";
const LIMIT = 50;
const FILTER_KEYS = [
  "mine",
  "untaken",
  "assigned_to",
  "genebank_id",
  "herd",
  "state",
  "kind",
] as const;

export default async function InkorgPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const user = await requireUser();
  await requireQueueWorker();
  const sp = await searchParams;
  const filters = new URLSearchParams();
  for (const k of FILTER_KEYS) if (sp[k]) filters.set(k, sp[k] as string);
  const offset = /^\d+$/.test(sp.offset ?? "") ? Number(sp.offset) : 0;
  const api = new URLSearchParams(filters);
  api.set("limit", String(LIMIT));
  api.set("offset", String(offset));

  let data: QueueList | null = null;
  let problem: string | null = null;
  try {
    data = await fetchApi<QueueList>(`/v2/inkorg?${api}`);
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 400) throw e;
    problem = e.detail;
  }
  const [genebanks, extra] = await Promise.all([
    fetchApi<{ genebanks: { id: number; name: string }[] }>("/genebanks")
      .then((r) => r.genebanks ?? [])
      .catch(() => []),
    fetchHandlers(),
  ]);
  const me: Person = { id: user.id, name: user.fullname || `Konto ${user.id}` };
  const pickable = people(me, data?.items ?? [], extra);

  const href = (changes: Record<string, string | null>) => {
    const q = new URLSearchParams(filters);
    for (const [k, v] of Object.entries(changes))
      v === null ? q.delete(k) : q.set(k, v);
    const s = q.toString();
    return s ? `${PATH}?${s}` : PATH;
  };
  const counts = data?.counts ?? {};
  const reading = data?.interpretation;
  const openCount = OPEN_STATES.reduce((n, s) => n + (counts[s] ?? 0), 0);
  const stateTabs: [string | null, string, number | null][] = [
    [null, "Öppna", openCount],
    ...[...OPEN_STATES, ...CLOSED_STATES]
      .filter((s) => counts[s])
      .map((s): [string, string, number] => [
        s,
        STATE_LABEL[s],
        counts[s] ?? 0,
      ]),
    ["alla", "Alla", null],
  ];

  return (
    <>
      <Masthead
        eyebrow="Stamboken"
        title="Inkorg"
        meta="Foton av pappersintyg och bevis som ska läggas in."
      />
      <div className={styles.container}>
        <GmailAlarm />
        <nav className={styles.counts} aria-label="Lägen">
          {stateTabs.map(([state, label, n]) => (
            <Link
              key={label}
              href={href({ state, offset: null })}
              className={styles.count}
              aria-current={(sp.state ?? null) === state ? "page" : undefined}
            >
              {label}
              {n !== null && <strong>{n}</strong>}
            </Link>
          ))}
        </nav>

        {reading && reading.interpreter !== "av" && (
          <p className={styles.muted}>
            Bildtolkning: {reading.waiting}{" "}
            {reading.waiting === 1 ? "foto väntar" : "foton väntar"}
            {reading.last_done_at &&
              `, senast klar ${new Date(reading.last_done_at).toLocaleString("sv-SE", { timeZone: "Europe/Stockholm" })}`}
            .
          </p>
        )}
        {reading?.alarm && (
          <p role="alert" className={styles.error}>
            Tre foton i rad gick inte att tolka. Kontrollera att bildtolkningen
            är igång.
          </p>
        )}

        <section className={`sb-card ${styles.card}`}>
          {/* Plain GET form: the filters live in the URL. */}
          <form method="get" action={PATH} className={styles.filters}>
            <label className={styles.check}>
              <input
                type="checkbox"
                name="mine"
                value="1"
                defaultChecked={sp.mine === "1"}
              />
              Mina
            </label>
            <label className={styles.check}>
              <input
                type="checkbox"
                name="untaken"
                value="1"
                defaultChecked={sp.untaken === "1"}
              />
              Otagna
            </label>
            <label>
              Handläggare
              <select
                name="assigned_to"
                defaultValue={sp.assigned_to ?? ""}
                className="sb-input"
              >
                <option value="">Alla</option>
                {pickable.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            {genebanks.length > 0 && (
              <label>
                Genbank
                <select
                  name="genebank_id"
                  defaultValue={sp.genebank_id ?? ""}
                  className="sb-input"
                >
                  <option value="">Alla</option>
                  {genebanks.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Besättning
              <input
                type="text"
                name="herd"
                defaultValue={sp.herd ?? ""}
                placeholder="G1274"
                className="sb-input"
                size={8}
              />
            </label>
            <label>
              Typ
              <select
                name="kind"
                defaultValue={sp.kind ?? ""}
                className="sb-input"
              >
                <option value="">Alla</option>
                {Object.entries(KIND_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            {sp.state && <input type="hidden" name="state" value={sp.state} />}
            <button type="submit" className="sb-btn sb-btn-sm">
              Filtrera
            </button>
            <Link href={PATH} className="sb-btn sb-btn-secondary sb-btn-sm">
              Rensa
            </Link>
          </form>
        </section>

        {problem !== null || data === null ? (
          <p role="alert" className={styles.error}>
            {problem ?? "Kunde inte läsa kön."}
          </p>
        ) : data.items.length === 0 ? (
          <p className={styles.muted}>Inga ärenden matchar filtren.</p>
        ) : (
          <section className="sb-card">
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Ärende</th>
                  <th>Besättning</th>
                  <th>Inskickat av</th>
                  <th>Typ</th>
                  <th>Läge</th>
                  <th>Handläggare</th>
                  <th>Väntat</th>
                  <th>Åtgärd</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => {
                  const actions = itemActions(item, user);
                  return (
                    <tr key={item.id}>
                      <td>
                        <Link
                          href={`${PATH}/${item.id}`}
                          className={styles.caseLink}
                        >
                          Ärende {item.id}
                        </Link>
                        <div className={styles.badges}>
                          <span className="sb-badge">
                            {item.documents_done} av {item.documents} klara
                          </span>
                          {item.missing_proof && (
                            <span className={`sb-badge ${styles.badgeWarn}`}>
                              bevis saknas
                            </span>
                          )}
                          {item.maybe_blurry && (
                            <span className={`sb-badge ${styles.badgeWarn}`}>
                              kan vara oskarp
                            </span>
                          )}
                          {item.stalled && (
                            <span className={`sb-badge ${styles.badgeWarn}`}>
                              står still
                            </span>
                          )}
                        </div>
                      </td>
                      <td data-label="Besättning">{item.herd ?? "–"}</td>
                      <td data-label="Inskickat av">
                        {item.sender?.name ?? "–"}
                      </td>
                      <td data-label="Typ">{kindLabel(item.kind)}</td>
                      <td data-label="Läge">
                        {STATE_LABEL[item.state] ?? item.state}
                      </td>
                      <td data-label="Handläggare">
                        {item.assigned_to?.name ?? "–"}
                      </td>
                      <td data-label="Väntat">{waited(item.received_at)}</td>
                      <td>
                        <RowActions
                          id={item.id}
                          canTake={actions.includes("ta")}
                          canAssign={actions.includes("tilldela")}
                          people={pickable}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className={`${styles.foot} ${styles.card}`}>
              <span className="sb-meta">
                {offset + 1}–{offset + data.items.length} av {data.total}
              </span>
              {offset > 0 && (
                <Link
                  href={href({ offset: String(Math.max(0, offset - LIMIT)) })}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Föregående
                </Link>
              )}
              {offset + LIMIT < data.total && (
                <Link
                  href={href({ offset: String(offset + LIMIT) })}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Nästa
                </Link>
              )}
            </div>
          </section>
        )}

        {manages(user, null) && <AssignHerd people={pickable} />}
      </div>
    </>
  );
}
