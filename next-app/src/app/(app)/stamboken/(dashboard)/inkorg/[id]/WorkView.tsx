"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useMode } from "@/lib/mode-context";
import type { GenebankHerd } from "@/utils/saleRules";
import {
  changeState,
  confirmMask,
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
  ACTION_LABEL,
  canEditDocuments,
  canSave,
  CERT_FORMAT_LABEL,
  CLOSED_STATES,
  DOC_STATUS_LABEL,
  DOC_TYPE_LABEL,
  itemActions,
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
import { RowActions } from "../QueueControls";
import { AskBreeder } from "./AskBreeder";
import { CertificateForm } from "./CertificateForm";
import { MailFacts } from "./MailFacts";
import { PhotoViewer } from "./PhotoViewer";
import { SalePanel } from "./SalePanel";
import styles from "../inkorg.module.css";

const time = (iso: string) =>
  new Date(iso).toLocaleString("sv-SE", { timeZone: "Europe/Stockholm" });

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
};

function eventText(e: InboxEvent): string {
  const d = (e.detail ?? {}) as Record<string, string>;
  const label = EVENT_LABEL[e.kind] ?? e.kind;
  if (e.kind === "lage")
    return `${label}: ${STATE_LABEL[d.from as ItemState] ?? d.from} → ${STATE_LABEL[d.to as ItemState] ?? d.to}${d.note ? ` (${d.note})` : ""}`;
  if (e.kind === "sparad")
    return `${label}: ${d.individual}${d.action === "overlatelse" ? `, såld till ${d.herd}` : ""}`;
  if (e.kind === "foralder_inlagd") return `${label}: ${d.individual}`;
  if (e.kind === "fraga" || e.kind === "svar")
    return d.text ? `${label}: ${d.text}` : label;
  return label;
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
}: {
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
  const editable = canEditDocuments(item, user);
  const saving = canSave(item, user);
  const allActions = itemActions(item, user);
  const actions = allActions.filter((a) => a !== "tilldela");
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [asking, setAsking] = useState<ItemAction | null>(null);
  const [answer, setAnswer] = useState("");

  // The photo and masking state of the selected document, reset when it or its step changes.
  const masking = doc?.doc_type === "intyg" && doc.status === "sparad";
  // Nothing saved from it yet: its type can change and it can be dismissed.
  const fresh = doc?.status === "ny" || doc?.status === "vantar_foralder";
  const step = `${doc?.id}:${doc?.status}`;
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

  return (
    <div className={styles.container}>
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
            <dd>{item.sender?.name ?? item.sender_address ?? "–"}</dd>
            <MailFacts item={item} />
            <dt>Besättning</dt>
            <dd>{item.herd ?? "–"}</dd>
            <dt>Inkommet</dt>
            <dd>
              {time(item.received_at)} ({waited(item.received_at)})
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
                    {ACTION_LABEL[a]}
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

          {item.state === "tagen" && item.assigned_to?.id === user.id && (
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
                  {time(e.at)} · {eventText(e)}
                  {e.user ? ` · ${e.user.name}` : ""}
                </li>
              ))}
            </ol>
          </details>
        </aside>

        {/* Middle: the photo */}
        <section className={`sb-card ${styles.card}`} aria-label="Fotot">
          {doc ? (
            <>
              <PhotoViewer
                key={doc.id}
                src={`${apiBase}/v2/inkorg/${item.id}/dokument/${doc.id}/original`}
                rotation={rotation}
                onRotate={rotate}
                mask={
                  masking && editable
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
          ) : (
            <p className={styles.muted}>Ärendet har inga dokument.</p>
          )}
        </section>

        {/* Right: what the document shows */}
        <section className={`sb-card ${styles.card}`} aria-label="Registrering">
          {doc && !saving && (
            <div className={styles.note}>
              {CLOSED_STATES.includes(item.state)
                ? "Ärendet är stängt."
                : item.ref_type
                  ? `Ärendet gäller ${item.ref_type} ${item.ref_id ?? ""} och avgörs där, inte i kön.`
                  : item.assigned_to?.id === user.id
                    ? "Ärendet väntar. Arbeta vidare för att spara."
                    : item.assigned_to
                      ? `${item.assigned_to.name} har ärendet. Ta över det för att spara.`
                      : "Ta ärendet för att spara."}
              {!item.ref_type && takeButtons.length > 0 && (
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

          {!doc ? null : doc.status === "klar" || doc.status === "avfardad" ? (
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
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                onClick={() => advance(doc, true)}
              >
                Nästa dokument
              </button>
            </div>
          ) : doc.doc_type === "intyg" && doc.status === "sparad" ? (
            <>
              <div className={styles.card}>
                <h2 className={styles.cardTitle}>Dölj säljare och köpare</h2>
                <p className={styles.muted}>
                  {doc.individual} är sparad. Täck säljarens och köparens
                  uppgifter med svarta rutor innan kopian läggs på kaninen. Dra
                  en ruta eller dess hörn, eller välj den och använd
                  piltangenterna (Skift ändrar storleken).
                </p>
                {editable ? (
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
                    <button
                      type="button"
                      className="sb-btn"
                      disabled={pending}
                      onClick={() =>
                        run(
                          () => confirmMask(item.id, doc.id, toApiRects(rects)),
                          (d) => advance(d.document),
                        )
                      }
                    >
                      {rects.length
                        ? "Bekräfta maskningen och nästa"
                        : "Bekräfta: inget att dölja"}
                    </button>
                  </>
                ) : (
                  <p className={styles.muted}>Ta ärendet för att maskera.</p>
                )}
              </div>
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
