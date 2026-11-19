"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { formatTime } from "@/lib/inkorg";
import { useMode } from "@/lib/mode-context";
import type { GenebankHerd } from "@/utils/saleRules";
import {
  changeState,
  confirmMask,
  checkReportPhoto,
  reinterpretDocument,
  takeItem,
  updateDocument,
  waitForParent,
  type ActionResult,
} from "../actions";
import {
  initialRects,
  MAX_RECTS,
  rotateRect,
  toApiRects,
  turn,
} from "../image";
import {
  accountOrLink,
  ACTION_LABEL,
  canEditDocuments,
  canSave,
  CERT_FORMAT_LABEL,
  CLOSED_STATES,
  DOC_STATUS_LABEL,
  DOC_TYPE_LABEL,
  itemActions,
  manages,
  nextOpenDocument,
  STATE_LABEL,
  waited,
  WARNING_LABEL,
  type InboxDetail,
  type InboxDocument,
  type InboxEvent,
  type ItemAction,
  type ItemState,
  type Person,
  type QueueUser,
  type Rect,
} from "../lib";
import { fmtDate } from "../../arsrapport/lib";
import { RowActions } from "../QueueControls";
import { AskBreeder } from "./AskBreeder";
import { CertificateForm } from "./CertificateForm";
import { ReportPhotoCheck } from "./ReportPhotoCheck";
import { MailFacts, SenderUnconfirmed } from "./MailFacts";
import { PhotoViewer } from "./PhotoViewer";
import { SalePanel } from "./SalePanel";
import styles from "../inkorg.module.css";

const EVENT_LABEL: Record<string, string> = {
  inkommen: "Inkommet",
  oppnad: "Öppnat",
  tagen: "Taget",
  overtagen: "Övertaget",
  tilldelad: "Tilldelat",
  lage: "Nytt läge",
  dokument: "Dokument ändrat",
  sparad: "Sparat",
  kopia: "Kopia lagd på kaninen",
  original_visat: "Originalet visat",
  foralder_inlagd: "Förälder inlagd",
  fraga: "Fråga till uppfödaren",
  svar: "Svar från uppfödaren",
  tolka_igen: "Tolkas igen",
  kontrollerad: "Kontrollerat",
};

function eventText(e: InboxEvent): string {
  const d = (e.detail ?? {}) as Record<string, string>;
  const label = EVENT_LABEL[e.kind] ?? e.kind;
  if (e.kind === "lage")
    return `${label}: ${STATE_LABEL[d.from as ItemState] ?? d.from} → ${STATE_LABEL[d.to as ItemState] ?? d.to}${d.note ? ` (${d.note})` : ""}`;
  if (e.kind === "sparad")
    return `${label}: ${d.individual}${d.action === "overlatelse" ? `, såld till ${d.herd}` : ""}`;
  if (e.kind === "foralder_inlagd") return `${label}: ${d.individual}`;
  if (e.kind === "kontrollerad")
    return `${label}: ${d.outcome === "rattat" ? "Rättat" : "Stämmer"}`;
  // The personal link has no account: the history names it instead (a purchase notice).
  if (e.kind === "inkommen" && d.via) return `${label} via ${d.via}`;
  if (e.kind === "fraga" || e.kind === "svar")
    return d.text ? `${label}: ${d.text}` : label;
  return label;
}

// Who sent the item: its account, else the link or the account its arrival names (a purchase notice has no
// sender_user: a link's history says `via`, an account's is the event's user), else the mail's address.
function senderText(item: InboxDetail): string {
  const arrived = item.events.find((e) => e.kind === "inkommen");
  const via = arrived?.detail?.via;
  return (
    item.sender?.name ??
    (typeof via === "string" ? via : null) ??
    arrived?.user?.name ??
    accountOrLink(item) ??
    item.sender_address ??
    "–"
  );
}

// A purchase notice (4a Task 5) in the main column: the rabbit, both herds and the date, and the way to register
// the sale, filled in on the rabbit's page (?salj=1&till&datum), or to approve the seller's pending one.
function PurchaseCard({ item }: { item: InboxDetail }) {
  const data = item.ref_data!;
  const pendingSale = !!(item.report_year && item.genebank_id);
  const sale = new URLSearchParams({
    salj: "1",
    till: item.herd ?? "",
    datum: data.date,
  });
  return (
    <div className={styles.purchase}>
      <h2 className={styles.cardTitle}>Anmält köp</h2>
      <dl className={styles.purchaseFacts}>
        <dt>Kanin</dt>
        <dd className={styles.number}>{data.number}</dd>
        <dt>Säljare</dt>
        <dd>{data.from_herd}</dd>
        <dt>Köpare</dt>
        <dd>{item.herd ?? "–"}</dd>
        <dt>Datum</dt>
        <dd>{fmtDate(data.date)}</dd>
      </dl>
      {pendingSale ? (
        <p>
          Säljarens försäljning väntar. Godkänn den i årsrapportens statusvy.{" "}
          <Link
            href={`/stamboken/arsrapport/status/${item.report_year}?genebank_id=${item.genebank_id}`}
          >
            Öppna statusvyn
          </Link>
        </p>
      ) : (
        <Link
          className="sb-btn"
          href={`/stamboken/individ/${encodeURIComponent(data.number)}?${sale}`}
        >
          Registrera försäljningen
        </Link>
      )}
    </div>
  );
}

// What the asking actions ask for before they change the state.
const ASK: Partial<Record<ItemAction, string>> = {
  vantar_foralder: "Förälderns individnummer (två med komma emellan)",
  ofullstandig: "Vad saknas?",
  dubblett: "Dubblett av ärende nummer",
  skrap: "",
};

export function WorkView({
  item,
  user,
  colors,
  herds,
  people,
  noRole = false,
  reportYear = null,
}: {
  noRole?: boolean;
  /** The year of the form entry link; null leaves it out. */
  reportYear?: number | null;
  item: InboxDetail;
  user: QueueUser;
  colors: string[];
  herds: GenebankHerd[];
  people: Person[];
}) {
  const mode = useMode();
  // As RegisterRabbitDialog: demo reads from /api-test when it is configured.
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";
  const docs = item.documents;
  const [selectedId, setSelectedId] = useState<number | null>(
    () => nextOpenDocument(docs, null) ?? docs[0]?.id ?? null,
  );
  const doc = docs.find((d) => d.id === selectedId) ?? null;
  // No role in the item's genebank: read only (the server refuses the rest anyway).
  const editable = !noRole && canEditDocuments(item, user);
  const saving = !noRole && canSave(item, user);
  const allActions = noRole ? [] : itemActions(item, user);
  const actions = allActions.filter((a) => a !== "tilldela");
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [asking, setAsking] = useState<ItemAction | null>(null);
  const [answer, setAnswer] = useState("");

  // The photo and masking state of the selected document, reset when it or its step changes.
  // "Gör om maskningen": the editor on a finished document that has a copy.
  const [redo, setRedo] = useState(false);
  const masking =
    doc?.doc_type === "intyg" &&
    (doc.status === "sparad" || (redo && doc.status === "klar"));
  // The handler of an open item, and a manager or admin at any time once a copy exists.
  const mayMask =
    editable || (!noRole && !!doc?.has_copy && manages(user, item.genebank_id));
  const [noPersonalData, setNoPersonalData] = useState(false);
  // Nothing saved from it yet: its type can change and it can be dismissed.
  const fresh = doc?.status === "ny" || doc?.status === "vantar_foralder";
  // A purchase notice's photo is looked at and dismissed only: never read, so no type, format or Tolka igen.
  const purchase = item.ref_type === "kopanmalan";
  // Also reset when the handler changes: a turn made before the item was taken
  // was never saved, and the masking must start from the stored rotation.
  const step = `${doc?.id}:${doc?.status}:${item.assigned_to?.id ?? ""}`;
  const [shownStep, setShownStep] = useState(step);
  const [rotation, setRotation] = useState(doc?.rotation ?? 0);
  const [rects, setRects] = useState<Rect[]>(() =>
    doc ? initialRects(doc) : [],
  );
  const [selectedRect, setSelectedRect] = useState<number | null>(null);
  // "Bifoga utsnitt": the frame on the photo, in the view's rotation.
  const [crop, setCrop] = useState<Rect | null>(null);
  if (step !== shownStep) {
    setShownStep(step);
    setRotation(doc?.rotation ?? 0);
    setRects(doc ? initialRects(doc) : []);
    setSelectedRect(null);
    setCrop(null);
    setRedo(false);
    setNoPersonalData(false);
  }

  const run = <T,>(
    action: () => Promise<ActionResult<T>>,
    then?: (data: T) => void,
    undo?: () => void,
  ) =>
    start(async () => {
      setError(null);
      setNotice(null);
      const res = await action();
      if (res.ok) return then?.(res.data);
      setError(res.problem.detail);
      undo?.();
    });

  /** On to the next document that needs work (the same one while a certificate waits for its masking). */
  const advance = (updated: InboxDocument, skip = false) => {
    const merged = docs.map((d) => (d.id === updated.id ? updated : d));
    const next = nextOpenDocument(merged, updated.id, skip);
    if (next === null)
      setNotice(
        skip ? "Inga fler dokument att lägga in." : "Alla dokument är klara.",
      );
    else setSelectedId(next);
  };

  const turnView = (quarterTurns: number) => {
    setRotation((r) => turn(r, quarterTurns));
    if (masking) setRects((rs) => rs.map((r) => rotateRect(r, quarterTurns)));
    setCrop((c) => c && rotateRect(c, quarterTurns));
  };

  const rotate = (quarterTurns: number) => {
    if (!doc) return;
    turnView(quarterTurns);
    // The server turns the copy by it. Once the copy exists a new turn would
    // remake it under the old rectangles, so the turn is only for reading then,
    // as it is without the item. A refused turn is turned back.
    if (editable && !doc.has_copy)
      run(
        () =>
          updateDocument(item.id, doc.id, {
            rotation: turn(rotation, quarterTurns),
          }),
        undefined,
        () => turnView(-quarterTurns),
      );
  };

  const toggleAsk = (action: ItemAction) => {
    setAsking(asking === action ? null : action);
    setAnswer("");
  };

  const doAction = (action: ItemAction) => {
    setAsking(null);
    const id = item.id;
    switch (action) {
      case "ta":
      case "arbeta_vidare":
        return run(() => takeItem(id));
      case "ta_over":
        return run(() => takeItem(id, true));
      case "oppna":
        return run(() => changeState(id, "tagen"));
      case "vantar_foralder":
        if (!doc) return setError("Välj dokumentet som väntar.");
        return run(() => waitForParent(id, doc.id, answer.split(",")));
      case "ofullstandig":
        return run(() => changeState(id, "ofullstandig", { note: answer }));
      case "dubblett":
        return run(() =>
          changeState(id, "dubblett", { duplicate_of: Number(answer) }),
        );
      default:
        return run(() => changeState(id, action));
    }
  };

  const takeButtons = actions.filter(
    (a) => a === "ta" || a === "ta_over" || a === "arbeta_vidare",
  );
  // A report photo (4b) is the queue's own to close: taken, compared with its rabbit, closed
  const reportPhoto =
    item.kind === "kontroll" && item.ref_type === "individual";
  const checking =
    reportPhoto &&
    !noRole &&
    item.assigned_to?.id === user.id &&
    item.state === "tagen";

  return (
    <div className={styles.container}>
      {noRole && (
        <p role="status" className={styles.note}>
          Du kan läsa det här ärendet men inte spara: du har inte rollen för den
          här genbanken.
        </p>
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className={styles.muted}>
          {notice} <Link href="/stamboken/inkorg">Till kön</Link>
        </p>
      )}
      <div className={styles.work}>
        {/* Left: documents, the item and its actions */}
        <aside className={`sb-card ${styles.card}`} aria-label="Ärendet">
          <h2 className={styles.cardTitle}>Dokument</h2>
          <ul className={styles.docList}>
            {docs.map((d, i) => (
              <li key={d.id}>
                <button
                  type="button"
                  className={styles.docButton}
                  aria-current={d.id === selectedId}
                  data-status={d.status}
                  onClick={() => setSelectedId(d.id)}
                >
                  <span>
                    {i + 1}. {DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type}
                    {d.individual ? ` ${d.individual}` : ""}
                  </span>
                  <span className={styles.docMeta}>
                    {DOC_STATUS_LABEL[d.status] ?? d.status}
                    {d.waiting_for?.length
                      ? ` ${d.waiting_for.join(", ")}`
                      : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <dl className={styles.facts}>
            <dt>Läge</dt>
            <dd>{STATE_LABEL[item.state] ?? item.state}</dd>
            <dt>Handläggare</dt>
            <dd>{item.assigned_to?.name ?? "ingen"}</dd>
            <dt>Inskickat av</dt>
            <dd>
              {senderText(item)}
              <SenderUnconfirmed item={item} />
            </dd>
            <MailFacts item={item} />
            <dt>Besättning</dt>
            <dd>{item.herd ?? "–"}</dd>
            <dt>Inkommet</dt>
            <dd>
              {formatTime(item.received_at)} ({waited(item.received_at)})
            </dd>
            {item.missing_proof && (
              <>
                <dt>Bevis</dt>
                <dd>saknas</dd>
              </>
            )}
            {item.duplicate_of && (
              <>
                <dt>Dubblett av</dt>
                <dd>
                  <Link href={`/stamboken/inkorg/${item.duplicate_of}`}>
                    Ärende {item.duplicate_of}
                  </Link>
                </dd>
              </>
            )}
            {item.message && (
              <>
                <dt>Meddelande</dt>
                <dd>{item.message}</dd>
              </>
            )}
          </dl>

          {actions.length > 0 && (
            <div className={styles.actions}>
              {actions.map((a) => (
                <div key={a} className={styles.actions}>
                  <button
                    type="button"
                    className={`sb-btn sb-btn-sm ${a === "ta" || a === "arbeta_vidare" ? "" : "sb-btn-secondary"}`}
                    disabled={pending}
                    aria-expanded={a in ASK ? asking === a : undefined}
                    onClick={() => (a in ASK ? toggleAsk(a) : doAction(a))}
                  >
                    {a === "klar" && item.kind === "meddelande"
                      ? "Besvarat"
                      : ACTION_LABEL[a]}
                  </button>
                  {asking === a && (
                    <form
                      className={styles.ask}
                      onSubmit={(e) => {
                        e.preventDefault();
                        doAction(a);
                      }}
                    >
                      {ASK[a] ? (
                        <label className="sb-label">
                          {ASK[a]}
                          <input
                            className="sb-input"
                            value={answer}
                            onChange={(e) => setAnswer(e.target.value)}
                            inputMode={a === "dubblett" ? "numeric" : undefined}
                            required
                            autoFocus
                          />
                        </label>
                      ) : (
                        <p className={styles.muted}>
                          Ärendet stängs utan att något sparas.
                        </p>
                      )}
                      <div className={styles.row}>
                        <button
                          type="submit"
                          className="sb-btn sb-btn-sm"
                          disabled={pending}
                        >
                          {ACTION_LABEL[a]}
                        </button>
                        <button
                          type="button"
                          className="sb-btn sb-btn-ghost sb-btn-sm"
                          onClick={() => setAsking(null)}
                        >
                          Avbryt
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              ))}
            </div>
          )}

          {!noRole &&
            item.state === "tagen" &&
            item.assigned_to?.id === user.id && (
              <AskBreeder
                itemId={item.id}
                documentId={doc && !masking ? doc.id : null}
                crop={
                  crop && doc
                    ? toApiRects([
                        rotateRect(crop, (doc.rotation - rotation) / 90),
                      ])[0]
                    : null
                }
                onFrame={(on) =>
                  setCrop(on ? { x: 0.2, y: 0.2, w: 0.6, h: 0.3 } : null)
                }
              />
            )}

          {allActions.includes("tilldela") && (
            <RowActions
              id={item.id}
              canTake={false}
              canAssign
              people={people}
            />
          )}

          <details className={styles.history}>
            <summary>Historik ({item.events.length})</summary>
            <ol>
              {item.events.map((e) => (
                <li key={e.id}>
                  {formatTime(e.at)} · {eventText(e)}
                  {e.user ? ` · ${e.user.name}` : ""}
                </li>
              ))}
            </ol>
          </details>
        </aside>

        {/* Middle: the photo */}
        <section className={`sb-card ${styles.card}`} aria-label="Fotot">
          {purchase && item.ref_data && <PurchaseCard item={item} />}
          {doc ? (
            <>
              <PhotoViewer
                key={doc.id}
                src={`${apiBase}/v2/inkorg/${item.id}/dokument/${doc.id}/original`}
                rotation={rotation}
                onRotate={rotate}
                mask={
                  masking && mayMask
                    ? {
                        rects,
                        selected: selectedRect,
                        onSelect: setSelectedRect,
                        onChange: (i, r) =>
                          setRects((rs) => rs.map((x, j) => (j === i ? r : x))),
                        onRemove: (i) => {
                          setRects((rs) => rs.filter((_, j) => j !== i));
                          setSelectedRect(null);
                        },
                      }
                    : crop
                      ? {
                          rects: [crop],
                          selected: 0,
                          frame: true,
                          onSelect: () => undefined,
                          onChange: (_, r) => setCrop(r),
                          onRemove: () => setCrop(null),
                        }
                      : undefined
                }
              />
              {(doc.warnings.length > 0 || doc.duplicates.length > 0) && (
                <div className={styles.badges}>
                  {doc.warnings.map((w) => (
                    <span key={w} className={`sb-badge ${styles.badgeWarn}`}>
                      {WARNING_LABEL[w] ?? w}
                    </span>
                  ))}
                  {doc.duplicates.map((o) => (
                    <Link
                      key={o.document_id}
                      href={`/stamboken/inkorg/${o.item_id}`}
                      className="sb-badge"
                    >
                      samma bild i ärende {o.item_id}
                    </Link>
                  ))}
                </div>
              )}
              {editable && (
                <div className={styles.filters}>
                  {!purchase && (
                    <label>
                      Typ
                      <select
                        className="sb-input"
                        value={doc.doc_type}
                        disabled={pending || !fresh}
                        onChange={(e) =>
                          run(() =>
                            updateDocument(item.id, doc.id, {
                              doc_type: e.target.value,
                            }),
                          )
                        }
                      >
                        {Object.entries(DOC_TYPE_LABEL).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {!purchase && (
                    <label>
                      Format
                      <select
                        className="sb-input"
                        value={doc.cert_format ?? ""}
                        disabled={pending}
                        onChange={(e) =>
                          run(() =>
                            updateDocument(item.id, doc.id, {
                              cert_format: e.target.value || null,
                            }),
                          )
                        }
                      >
                        <option value="">Inte angivet</option>
                        {Object.entries(CERT_FORMAT_LABEL).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {fresh && (
                    <button
                      type="button"
                      className="sb-btn sb-btn-secondary sb-btn-sm"
                      disabled={pending}
                      onClick={() =>
                        run(
                          () =>
                            updateDocument(item.id, doc.id, {
                              dismissed: true,
                            }),
                          (d) => advance(d.document, true),
                        )
                      }
                    >
                      Avfärda
                    </button>
                  )}
                  {fresh &&
                    !purchase &&
                    doc.doc_type === "intyg" &&
                    doc.interpretation_status !== "av" && (
                      <button
                        type="button"
                        className="sb-btn sb-btn-secondary sb-btn-sm"
                        disabled={
                          pending || doc.interpretation_status === "vantar"
                        }
                        onClick={() =>
                          run(
                            () => reinterpretDocument(item.id, doc.id),
                            () => setNotice("Fotot tolkas igen."),
                          )
                        }
                      >
                        Tolka igen
                      </button>
                    )}
                  {doc.status === "avfardad" && (
                    <button
                      type="button"
                      className="sb-btn sb-btn-secondary sb-btn-sm"
                      disabled={pending}
                      onClick={() =>
                        run(() =>
                          updateDocument(item.id, doc.id, { dismissed: false }),
                        )
                      }
                    >
                      Ångra avfärda
                    </button>
                  )}
                </div>
              )}
            </>
          ) : purchase ? null : (
            <p className={styles.muted}>Ärendet har inga dokument.</p>
          )}
        </section>

        {/* Right: what the document shows */}
        <section
          className={`sb-card ${styles.card} ${styles.hideEmpty}`}
          aria-label="Registrering"
        >
          {item.ref_type === "sale_proposal" && (
            <p className={styles.note}>
              Avgörs i årsrapportens statusvy.
              {item.report_year && item.genebank_id && (
                <>
                  {" "}
                  <Link
                    href={`/stamboken/arsrapport/status/${item.report_year}?genebank_id=${item.genebank_id}`}
                  >
                    Öppna statusvyn
                  </Link>
                </>
              )}
            </p>
          )}
          {item.kind === "upload" && item.ref_data && (
            // a bought rabbit Stamboken lacks (S7): register it in its birth herd, then transfer it to the buyer
            <p className={styles.note}>
              Köpt av {item.herd}: {item.ref_data.number} från{" "}
              {item.ref_data.from_herd}, {fmtDate(item.ref_data.date)}.
            </p>
          )}
          {doc &&
            !saving &&
            !checking &&
            !noRole &&
            item.ref_type !== "sale_proposal" &&
            item.ref_type !== "kopanmalan" && (
              <div className={styles.note}>
                {CLOSED_STATES.includes(item.state)
                  ? "Ärendet är stängt."
                  : item.ref_type && !reportPhoto
                    ? `Ärendet gäller ${item.ref_type} ${item.ref_id ?? ""} och avgörs där, inte i kön.`
                    : item.assigned_to?.id === user.id
                      ? "Ärendet väntar. Arbeta vidare för att spara."
                      : item.assigned_to
                        ? `${item.assigned_to.name} har ärendet. Ta över det för att spara.`
                        : "Ta ärendet för att spara."}
                {(!item.ref_type || reportPhoto) && takeButtons.length > 0 && (
                  <div className={styles.row} style={{ marginTop: 8 }}>
                    {takeButtons.map((a) => (
                      <button
                        key={a}
                        type="button"
                        className="sb-btn sb-btn-sm"
                        disabled={pending}
                        onClick={() => doAction(a)}
                      >
                        {ACTION_LABEL[a]}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

          {/* a purchase notice's photo is looked at; the purchase is registered on the rabbit's page */}
          {!doc || item.ref_type === "kopanmalan" ? null : item.registered &&
            doc.doc_type === "intyg" ? (
            <ReportPhotoCheck
              doc={doc}
              registered={item.registered}
              canCheck={checking && doc.status === "sparad"}
              pending={pending}
              onCheck={(outcome) =>
                run(
                  () => checkReportPhoto(item.id, doc.id, outcome),
                  () => setNotice("Ärendet är stängt."),
                )
              }
              onReinterpret={() =>
                run(
                  () => reinterpretDocument(item.id, doc.id),
                  () => setNotice("Fotot tolkas igen."),
                )
              }
            />
          ) : (doc.status === "klar" || doc.status === "avfardad") &&
            !masking ? (
            <div className={styles.card}>
              <h2 className={styles.cardTitle}>
                {DOC_STATUS_LABEL[doc.status]}
              </h2>
              {doc.individual && (
                <p>
                  <Link
                    href={`/stamboken/individ/${encodeURIComponent(doc.individual)}`}
                  >
                    {doc.individual}
                  </Link>
                  {doc.has_copy ? ": pappersintyget ligger på kaninen." : ""}
                </p>
              )}
              <div className={styles.row}>
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  onClick={() => advance(doc, true)}
                >
                  Nästa dokument
                </button>
                {doc.doc_type === "intyg" && doc.has_copy && mayMask && (
                  <button
                    type="button"
                    className="sb-btn sb-btn-secondary"
                    onClick={() => {
                      // From the stored pair, not from a turn made for reading.
                      setRotation(doc.rotation);
                      setRects(initialRects(doc));
                      setSelectedRect(null);
                      setRedo(true);
                    }}
                  >
                    Gör om maskningen
                  </button>
                )}
              </div>
            </div>
          ) : masking ? (
            <>
              <div className={styles.card}>
                <h2 className={styles.cardTitle}>Dölj säljare och köpare</h2>
                <p className={styles.muted}>
                  {doc.individual} är sparad.
                  {redo && " Kopian på kaninen ersätts när du bekräftar."} Täck
                  säljarens och köparens uppgifter med svarta rutor innan kopian
                  läggs på kaninen. Dra en ruta eller dess hörn, eller välj den
                  och använd piltangenterna (Skift ändrar storleken).
                </p>
                {mayMask ? (
                  <>
                    <div className={styles.row}>
                      <button
                        type="button"
                        className="sb-btn sb-btn-secondary sb-btn-sm"
                        disabled={rects.length >= MAX_RECTS}
                        onClick={() => {
                          setRects((rs) => [
                            ...rs,
                            { x: 0.35, y: 0.45, w: 0.3, h: 0.1 },
                          ]);
                          setSelectedRect(rects.length);
                        }}
                      >
                        Lägg till ruta
                      </button>
                      <button
                        type="button"
                        className="sb-btn sb-btn-secondary sb-btn-sm"
                        disabled={selectedRect === null}
                        onClick={() => {
                          setRects((rs) =>
                            rs.filter((_, j) => j !== selectedRect),
                          );
                          setSelectedRect(null);
                        }}
                      >
                        Ta bort vald ruta
                      </button>
                    </div>
                    {rects.length === 0 && (
                      <label className={styles.row}>
                        <input
                          type="checkbox"
                          checked={noPersonalData}
                          onChange={(e) => setNoPersonalData(e.target.checked)}
                        />
                        Fotot visar inga säljar- eller köparuppgifter
                      </label>
                    )}
                    <div className={styles.row}>
                      <button
                        type="button"
                        className="sb-btn"
                        disabled={
                          pending || (rects.length === 0 && !noPersonalData)
                        }
                        onClick={() =>
                          run(
                            () =>
                              confirmMask(
                                item.id,
                                doc.id,
                                rotation,
                                toApiRects(rects),
                                noPersonalData,
                              ),
                            (d) => {
                              setRedo(false);
                              advance(d.document);
                            },
                          )
                        }
                      >
                        Bekräfta maskningen och nästa
                      </button>
                      {redo && (
                        <button
                          type="button"
                          className="sb-btn sb-btn-ghost"
                          onClick={() => setRedo(false)}
                        >
                          Avbryt
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <p className={styles.muted}>Ta ärendet för att maskera.</p>
                )}
              </div>
              {doc.status === "sparad" && (
                <details className={styles.history}>
                  <summary>Visar intyget en försäljning?</summary>
                  <SalePanel
                    key={doc.id}
                    itemId={item.id}
                    doc={doc}
                    herds={herds}
                    canSave={saving}
                    onDone={() => undefined}
                  />
                </details>
              )}
            </>
          ) : doc.doc_type === "intyg" ? (
            <CertificateForm
              key={doc.id}
              itemId={item.id}
              doc={doc}
              colors={colors}
              canSave={saving}
              onSaved={(d) => advance(d)}
              onSkip={() => advance(doc, true)}
            />
          ) : doc.doc_type === "bevis" ? (
            <SalePanel
              key={doc.id}
              itemId={item.id}
              doc={doc}
              herds={herds}
              canSave={saving}
              onDone={(d) => advance(d)}
            />
          ) : doc.doc_type === "arsblankett" &&
            saving &&
            item.herd &&
            reportYear ? (
            <div className={styles.card}>
              <p className={styles.muted}>
                Årsblanketten matas in på en egen sida, med fotot bredvid.
              </p>
              <Link
                className="sb-btn"
                href={`/stamboken/arsrapport/${item.herd}/${reportYear}?post=${item.id}`}
              >
                Mata in årsrapporten
              </Link>
            </div>
          ) : (
            <div className={styles.card}>
              <p className={styles.muted}>
                {DOC_TYPE_LABEL[doc.doc_type]} läggs inte in härifrån. Byt typ
                om det är ett intyg eller ett bevis, annars avfärda dokumentet.
              </p>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                onClick={() => advance(doc, true)}
              >
                Hoppa över
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
