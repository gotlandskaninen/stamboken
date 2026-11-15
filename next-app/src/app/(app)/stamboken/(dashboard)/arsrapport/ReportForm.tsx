"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MbCard } from "../min-besattning/min-besattning-ui";
import type * as Actions from "./actions";
import {
  CONFLICT_TEXT,
  DISEASES,
  EMPTY_ENTRY,
  emptyState,
  fmtDate,
  fmtTime,
  fromBody,
  isDone,
  keyAfter,
  newKey,
  refusalText,
  toBody,
  toDraft,
  type DraftData,
  type Entry,
  type FormState,
  type Membership,
  type Receipt as ReceiptData,
  type Refusal,
  type ReportView,
  type SaldState,
  type Submission,
} from "./lib";
import { RabbitRow } from "./RabbitRow";
import { Receipt } from "./Receipt";
import { ReportStatus, type StatusKind } from "./ReportStatus";
import { SoldDialog } from "./SoldDialog";
import styles from "./arsrapport.module.css";

export type ReportActions = Pick<
  typeof Actions,
  "saveDraft" | "dryRun" | "submitReport" | "withdrawReport"
>;

type Filter = "inte_klara" | "kvar" | "dod" | "sald" | "alla";
type Phase = "idle" | "checking" | "sending" | "timeout";
type SaveState =
  | "saved"
  | "saving"
  | "offline"
  | "loggedout"
  | "conflict"
  | "closed";
type Problem = {
  status: number;
  detail: string;
  extensions?: Record<string, unknown>;
};

const AUTOSAVE_MS = 2000;
const BIG_LIST = 30;

// localStorage holds what the server has not confirmed yet. It never gets a
// buyer or a matrikel: toDraft strips them.
const localKey = (herd: string, year: number) => `arsrapport:${herd}:${year}`;
const readLocal = (herd: string, year: number): DraftData | null => {
  try {
    const raw = window.localStorage.getItem(localKey(herd, year));
    return raw ? (JSON.parse(raw) as DraftData) : null;
  } catch {
    return null;
  }
};
const writeLocal = (herd: string, year: number, data: DraftData | null) => {
  try {
    if (data)
      window.localStorage.setItem(localKey(herd, year), JSON.stringify(data));
    else window.localStorage.removeItem(localKey(herd, year));
  } catch {
    /* storage can be blocked: the server draft still works */
  }
};

const focusId = (id: string) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.focus();
  el.scrollIntoView?.({ block: "center" });
};

// Logged in, the page asks nothing about the matrikel: the profile holds the
// address, the phone and the answer about Koharen (D13).
const ProfileCard = (
  <MbCard title="Dina uppgifter">
    <p style={{ margin: "0 0 12px" }}>
      Adress, telefon och svaret om Koharen ändrar du i din profil.
    </p>
    <Link href="/stamboken/profil" className="sb-btn sb-btn-secondary">
      Gå till profilen
    </Link>
  </MbCard>
);

export function ReportForm({
  view,
  actions,
  contactSlot = ProfileCard,
  stickyTop = 56,
  post,
}: {
  view: ReportView;
  actions: ReportActions;
  contactSlot?: React.ReactNode;
  stickyTop?: number;
  post?: number;
}) {
  const router = useRouter();
  const routerRef = React.useRef(router);
  routerRef.current = router;
  const actionsRef = React.useRef(actions);
  actionsRef.current = actions;
  const { herd, year, round } = view;
  const editor = view.access === "manager" || view.access === "admin";
  const canEdit = round.open || (editor && round.activated);

  const [state, setState] = React.useState<FormState>(() =>
    fromBody(view.draft?.data ?? view.report?.submitted ?? {}),
  );
  const [mode, setMode] = React.useState<"form" | "receipt">(
    view.report ? "receipt" : "form",
  );
  const [version, setVersion] = React.useState(0);
  const [retry, setRetry] = React.useState(0);
  const [saveState, setSaveState] = React.useState<SaveState>("saved");
  const [savedAt, setSavedAt] = React.useState<string | null>(
    view.draft ? fmtTime(view.draft.updated_at) : null,
  );
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [refusals, setRefusals] = React.useState<Refusal[] | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [receipt, setReceipt] = React.useState<ReceiptData | null>(null);
  const [withdrawn, setWithdrawn] = React.useState<string | null>(null);
  const [localCopy, setLocalCopy] = React.useState(false);
  const [filter, setFilter] = React.useState<Filter>("alla");
  const [snapshot, setSnapshot] = React.useState<Set<number>>(new Set());
  const [search, setSearch] = React.useState("");
  const [soldFor, setSoldFor] = React.useState<number | null>(null);
  const [seenEnd, setSeenEnd] = React.useState(false);
  const [askRest, setAskRest] = React.useState(false);

  const stateRef = React.useRef(state);
  stateRef.current = state;
  const viewRef = React.useRef(view);
  viewRef.current = view;
  const versionRef = React.useRef(0);
  versionRef.current = version;
  const keyRef = React.useRef<string | null>(null);
  if (keyRef.current === null)
    keyRef.current = view.draft?.submission_key ?? newKey();
  const updatedAt = React.useRef<string | null>(view.draft?.updated_at ?? null);
  const frozen = React.useRef<Submission | null>(null);
  const visibleIds = React.useRef<number[]>([]);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const endRef = React.useRef<HTMLDivElement>(null);
  const stopped = React.useRef(false);

  const edit = React.useCallback((fn: (s: FormState) => FormState) => {
    setState(fn);
    setVersion((v) => v + 1);
  }, []);

  // A copy the server never confirmed (closed tab, lost connection) wins.
  React.useEffect(() => {
    const local = readLocal(herd.herd, year);
    if (local) {
      setState(fromBody(local));
      setLocalCopy(true);
      setVersion((v) => v + 1);
    }
  }, [herd.herd, year]);

  // Autosave: 2 s after the last change, from the revision the page started from.
  React.useEffect(() => {
    if (version === 0 || mode !== "form" || !canEdit || stopped.current) return;
    writeLocal(herd.herd, year, toDraft(stateRef.current));
    const mine = version;
    const t = setTimeout(async () => {
      const slow = setTimeout(() => setSaveState("saving"), 1000);
      const res = await actionsRef.current.saveDraft(
        herd.herd,
        year,
        toDraft(stateRef.current),
        updatedAt.current,
        keyRef.current!,
        viewRef.current.report?.revision ?? null,
        post,
      );
      clearTimeout(slow);
      if (res.ok) {
        updatedAt.current = res.data.updated_at;
        setSavedAt(fmtTime(res.data.updated_at));
        setSaveState("saved");
        if (versionRef.current === mine) writeLocal(herd.herd, year, null);
        return;
      }
      const p = res.problem;
      const ext = p.extensions ?? {};
      if (p.status === 409 && "draft" in ext) {
        const d = ext.draft as {
          data: DraftData;
          updated_at: string;
          submission_key: string | null;
        } | null;
        if (d) {
          setState(fromBody(d.data));
          updatedAt.current = d.updated_at;
          if (d.submission_key) keyRef.current = d.submission_key;
          setSavedAt(fmtTime(d.updated_at));
          writeLocal(herd.herd, year, null);
        } else routerRef.current.refresh(); // already submitted elsewhere: show its receipt
        setSaveState("conflict");
      } else if (p.status === 409 && ext.code === "rundan_stangd") {
        stopped.current = true;
        setSaveState("closed");
      } else if (p.status === 401) setSaveState("loggedout");
      else {
        setSaveState("offline");
        setTimeout(() => setRetry((n) => n + 1), 5000); // the page tries again
      }
    }, AUTOSAVE_MS);
    return () => clearTimeout(t);
  }, [version, retry, mode, canEdit, herd.herd, year, post]);

  // The "Markera resten" button waits until the last row has been seen.
  React.useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return setSeenEnd(true);
    const el = endRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setSeenEnd(true);
    });
    io.observe(el);
    return () => io.disconnect();
  }, [mode]);

  React.useEffect(() => {
    if (refusals) boxRef.current?.focus();
  }, [refusals]);

  const rabbits = view.rabbits;
  const done = React.useMemo(() => {
    const m = new Map<number, boolean>();
    for (const r of rabbits)
      m.set(r.id, isDone(r, state.rabbits[r.id], state.ending));
    return m;
  }, [rabbits, state.rabbits, state.ending]);
  const notDone = rabbits.filter((r) => !done.get(r.id));
  const doneCount = rabbits.length - notDone.length;

  const rowErrors = React.useMemo(() => {
    const m = new Map<number, string>();
    for (const r of refusals ?? [])
      if (r.individual_id !== null && !m.has(r.individual_id))
        m.set(r.individual_id, refusalText(r));
    return m;
  }, [refusals]);

  const chooseFilter = (f: Filter) => {
    if (f === "inte_klara")
      setSnapshot(new Set([...notDone.map((r) => r.id), ...rowErrors.keys()])); // a snapshot: a row that becomes done stays until the filter is chosen again
    setFilter(f);
  };

  const q = search.trim().toLowerCase();
  const visible = rabbits.filter((r) => {
    if (
      q &&
      !r.number.toLowerCase().includes(q) &&
      !(r.name ?? "").toLowerCase().includes(q)
    )
      return false;
    if (filter === "alla") return true;
    if (filter === "inte_klara") return snapshot.has(r.id);
    return state.rabbits[r.id]?.val === filter;
  });
  visibleIds.current = visible.map((r) => r.id);

  const onRow = React.useCallback(
    (id: number, patch: Partial<Entry>) =>
      edit((s) => ({
        ...s,
        rabbits: {
          ...s.rabbits,
          [id]: { ...(s.rabbits[id] ?? EMPTY_ENTRY), ...patch },
        },
      })),
    [edit],
  );
  const onSell = React.useCallback((id: number) => setSoldFor(id), []);
  const onNextWeight = React.useCallback((id: number) => {
    const ids = visibleIds.current;
    const s = stateRef.current;
    const lacks = (rid: number) => {
      const r = viewRef.current.rabbits.find((x) => x.id === rid);
      const e = s.rabbits[rid];
      return (
        !!r &&
        r.adult &&
        e?.val === "kvar" &&
        !e.vikt.trim() &&
        !e.ej_vagd?.trim()
      );
    };
    const next = ids.slice(ids.indexOf(id) + 1).find(lacks);
    if (next !== undefined) document.getElementById(`vikt-${next}`)?.focus();
  }, []);

  const restCount = rabbits.filter(
    (r) => r.state === "att_valja" && !state.rabbits[r.id]?.val,
  ).length;
  const markRest = () => {
    edit((s) => {
      const next = { ...s.rabbits };
      for (const r of viewRef.current.rabbits)
        if (r.state === "att_valja" && !next[r.id]?.val)
          next[r.id] = { ...(next[r.id] ?? EMPTY_ENTRY), val: "kvar" };
      return { ...s, rabbits: next };
    });
    setAskRest(false);
  };

  const soldRabbit = rabbits.find((r) => r.id === soldFor);

  // ---- Skicka -------------------------------------------------------------
  const handle = (p: Problem) => {
    const ext = p.extensions ?? {};
    if (p.status === 401) setSaveState("loggedout");
    else if (p.status === 422 && Array.isArray(ext.refusals))
      setRefusals(ext.refusals as Refusal[]);
    else if (p.status === 409 && ext.code === "rundan_stangd")
      setRefusals([
        { individual_id: null, code: "rundan_stangd", message: p.detail },
      ]);
    else if (p.status === 409) {
      setNotice(`${CONFLICT_TEXT}. Vi har läst in den senaste.`);
      router.refresh();
    } else setNotice(p.detail || "Det gick inte att skicka. Försök igen.");
    setPhase("idle");
  };

  const send = async (body: Submission) => {
    setPhase("sending");
    const res = await actions.submitReport(herd.herd, year, body, post);
    if (res.ok) {
      keyRef.current = keyAfter("ok", keyRef.current!);
      frozen.current = null;
      updatedAt.current = null;
      writeLocal(herd.herd, year, null);
      setLocalCopy(false);
      setReceipt(res.data);
      setMode("receipt");
      setPhase("idle");
      setWithdrawn(null);
      router.refresh();
    } else if (
      res.problem.status === 408 ||
      res.problem.status === 502 ||
      res.problem.status === 504
    )
      setPhase("timeout"); // the same key and the same body go again
    else handle(res.problem);
  };

  const skicka = async () => {
    if (phase !== "idle") return;
    setRefusals(null);
    setNotice(null);
    const body = toBody(state, keyRef.current!, view.report?.revision ?? null);
    frozen.current = body; // never stored: it may hold a buyer
    setPhase("checking");
    const dry = await actions.dryRun(herd.herd, year, body, post);
    if (!dry.ok) {
      if (dry.problem.status === 408 || dry.problem.status === 502)
        setNotice("Det gick inte att nå servern. Försök igen.");
      else handle(dry.problem);
      return setPhase("idle");
    }
    if (!dry.data.ok) {
      setRefusals(dry.data.refusals);
      return setPhase("idle");
    }
    await send(body);
  };

  const withdraw = async (reason?: string): Promise<string | null> => {
    const res = await actions.withdrawReport(
      herd.herd,
      year,
      view.report!.revision,
      reason,
      post,
    );
    if (res.ok) {
      keyRef.current = keyAfter("withdrawn", keyRef.current!);
      const d = res.data.draft;
      if (d) {
        setState(fromBody(d.data));
        updatedAt.current = d.updated_at;
      }
      setWithdrawn(fmtDate(new Date().toISOString()));
      setReceipt(null);
      setMode("form");
      router.refresh();
      return null;
    }
    const ext = res.problem.extensions ?? {};
    if (res.problem.status === 403)
      return "Tiden för att dra tillbaka rapporten har gått ut.";
    if (res.problem.status === 409) return `${CONFLICT_TEXT}. Ladda om sidan.`;
    if (Array.isArray(ext.refusals))
      return refusalText((ext.refusals as Refusal[])[0]);
    return res.problem.detail;
  };

  const startChange = () => {
    if (!localCopy) {
      setState(fromBody(view.draft?.data ?? view.report?.submitted ?? {}));
      updatedAt.current = view.draft?.updated_at ?? null;
    }
    setLocalCopy(false);
    setMode("form");
  };

  // ---- Texts and states ---------------------------------------------------
  const device =
    typeof navigator !== "undefined" &&
    /Mobi|Android|iPhone/i.test(navigator.userAgent)
      ? "telefonen"
      : "webbläsaren";
  const status: StatusKind =
    phase === "timeout"
      ? { kind: "timeout" }
      : phase !== "idle"
        ? { kind: "sending" }
        : saveState === "offline"
          ? { kind: "offline", device }
          : saveState === "loggedout"
            ? {
                kind: "loggedout",
                href: `/auth/sign-in?return_to=${encodeURIComponent(typeof window === "undefined" ? "/stamboken/arsrapport" : window.location.pathname)}`,
              }
            : saveState === "conflict"
              ? { kind: "conflict" }
              : saveState === "closed"
                ? { kind: "closed" }
                : withdrawn && version === 0
                  ? { kind: "withdrawn", date: withdrawn }
                  : saveState === "saving"
                    ? { kind: "saving" }
                    : { kind: "saved", at: savedAt, changing: !!view.report };
  const deadline = round.deadline
    ? round.deadline < new Date().toISOString().slice(0, 10)
      ? ({ kind: "late", deadline: fmtDate(round.deadline) } as const)
      : ({ kind: "deadline", deadline: fmtDate(round.deadline) } as const)
    : null;
  const closedText = !view.report && !canEdit;
  const breed = view.herd.genebank.toLowerCase();
  const heading = (
    <header>
      <h1 className={styles.title}>Årsrapport {year}</h1>
      <p className={styles.herdLine}>
        {herd.herd} {herd.name}
      </p>
    </header>
  );
  const root = {
    "--report-sticky-top": `${stickyTop}px`,
  } as React.CSSProperties;

  if (mode === "receipt" && (view.report || receipt)) {
    return (
      <div className={styles.root} style={root}>
        {heading}
        {editor && (
          <ReportStatus status={{ kind: "editor", herd: herd.herd }} />
        )}
        <Receipt
          view={view}
          receipt={receipt}
          hasDraft={!!view.draft || localCopy}
          busy={false}
          onChange={startChange}
          onWithdraw={withdraw}
        />
      </div>
    );
  }

  const rabbitErrors = [
    ...new Set(
      (refusals ?? [])
        .filter((r) => r.individual_id !== null)
        .map((r) => r.individual_id),
    ),
  ];
  const byId = new Map(rabbits.map((r) => [r.id, r]));
  const lonely = (refusals ?? []).filter((r) => r.individual_id === null);
  const buttonText = view.report ? "Skicka ändringarna" : "Skicka årsrapporten";
  const sending = phase === "checking" || phase === "sending";
  const lower = <ReportStatus status={status} />;

  return (
    <div className={styles.root} style={root}>
      {heading}
      <p className={styles.lead}>
        Gäller kaninerna i {herd.herd} den 31 december {year}.
      </p>
      {editor && <ReportStatus status={{ kind: "editor", herd: herd.herd }} />}
      {closedText ? (
        <ReportStatus status={{ kind: "closed" }} />
      ) : (
        <>
          <ReportStatus status={status} />
          {deadline && <ReportStatus status={deadline} />}
          {notice && (
            <p className={styles.errorText} role="alert">
              {notice}
            </p>
          )}

          {refusals && (
            <div
              ref={boxRef}
              tabIndex={-1}
              role="alert"
              className={styles.errorBox}
              id="felruta"
            >
              <h2>
                {rabbitErrors.length > 0
                  ? `${rabbitErrors.length} ${rabbitErrors.length === 1 ? "kanin är" : "kaniner är"} inte klara`
                  : "Rapporten kan inte skickas"}
              </h2>
              <ul>
                {rabbitErrors.map((id) => {
                  const r = byId.get(id!);
                  const text = rowErrors.get(id!);
                  return (
                    <li key={id}>
                      <a
                        href={`#rabbit-${id}`}
                        onClick={(e) => {
                          e.preventDefault();
                          focusId(`rabbit-${id}`);
                        }}
                      >
                        {r ? `${r.number} ${r.name ?? ""}` : `Kanin ${id}`}
                      </a>
                      : {text}
                    </li>
                  );
                })}
                {lonely.map((r, i) => (
                  <li key={i}>
                    {r.code === "halsa_saknas" || r.code === "orsak_kravs" ? (
                      <a
                        href={r.code === "halsa_saknas" ? "#halsa" : "#reason"}
                        onClick={(e) => {
                          e.preventDefault();
                          focusId(
                            r.code === "halsa_saknas" ? "halsa" : "reason",
                          );
                        }}
                      >
                        {refusalText(r)}
                      </a>
                    ) : (
                      refusalText(r)
                    )}
                  </li>
                ))}
              </ul>
              {rabbitErrors.length > 0 && (
                <button
                  type="button"
                  className={`sb-btn sb-btn-secondary ${styles.btn}`}
                  onClick={() => chooseFilter("inte_klara")}
                >
                  Visa bara dem som inte är klara
                </button>
              )}
            </div>
          )}

          <fieldset
            disabled={phase !== "idle"}
            style={{
              border: 0,
              padding: 0,
              margin: 0,
              minWidth: 0,
              display: "contents",
            }}
          >
            <div className={styles.sticky}>
              <div className={styles.stickyRow}>
                <input
                  type="search"
                  className={styles.field}
                  placeholder="Sök nummer eller namn"
                  aria-label="Sök nummer eller namn"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter" || visible.length !== 1) return;
                    e.preventDefault();
                    const id = visible[0].id;
                    (
                      document.getElementById(`vikt-${id}`) ??
                      document.querySelector<HTMLElement>(`#rabbit-${id} input`)
                    )?.focus();
                  }}
                />
                <span className={styles.counter} aria-live="polite">
                  {doneCount} av {rabbits.length} klara
                </span>
              </div>
              <progress
                className={styles.progress}
                max={rabbits.length || 1}
                value={doneCount}
                aria-hidden="true"
              />
            </div>

            <div className={styles.filters} role="group" aria-label="Visa">
              {(
                [
                  ["inte_klara", `Inte klara (${notDone.length})`],
                  ["kvar", "Finns kvar"],
                  ["dod", "Döda"],
                  ["sald", "Sålda"],
                  ["alla", "Alla"],
                ] as [Filter, string][]
              ).map(([f, label]) => (
                <button
                  key={f}
                  type="button"
                  className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                  aria-pressed={filter === f}
                  onClick={() => chooseFilter(f)}
                >
                  {label}
                </button>
              ))}
            </div>

            {rabbits.length === 0 ? (
              <p>
                Stamboken har inga kaniner registrerade i {herd.herd} den 31
                december {year}. Saknas kaniner? Kontakta genbanksansvarig. Har
                du inga kaniner kvar? Välj Jag avslutar min genbank.
              </p>
            ) : (
              <div className="sb-card-flat">
                <div className={styles.list}>
                  {visible.map((r) => (
                    <RabbitRow
                      key={r.id}
                      r={r}
                      entry={state.rabbits[r.id]}
                      ending={state.ending}
                      year={year}
                      canSell={view.can_sell}
                      done={!!done.get(r.id)}
                      error={rowErrors.get(r.id)}
                      onChange={onRow}
                      onSell={onSell}
                      onNextWeight={onNextWeight}
                    />
                  ))}
                  {visible.length === 0 && (
                    <p className={styles.meta} style={{ padding: 16 }}>
                      Ingen kanin matchar.
                    </p>
                  )}
                </div>
              </div>
            )}
            <div ref={endRef} />
            {rabbits.length > BIG_LIST && seenEnd && restCount > 0 && (
              <div className={styles.detail}>
                {askRest ? (
                  <div
                    className={styles.note}
                    role="alertdialog"
                    aria-label="Markera resten"
                  >
                    <span>
                      Markera {restCount} kaniner som finns kvar? Vuxna kaniner
                      behöver ändå vikt eller Ej vägd.
                    </span>
                    <button
                      type="button"
                      className={`sb-btn ${styles.btn}`}
                      onClick={markRest}
                    >
                      Ja, markera
                    </button>
                    <button
                      type="button"
                      className={`sb-btn sb-btn-secondary ${styles.btn}`}
                      onClick={() => setAskRest(false)}
                    >
                      Avbryt
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                    onClick={() => setAskRest(true)}
                  >
                    Markera resten som finns kvar
                  </button>
                )}
              </div>
            )}

            <MbCard title={`Kullar under ${year}`}>
              {view.litters.length === 0 ? (
                <p>
                  Inga kullar under {year} i Stamboken. Minst en kull krävs för
                  stödet.
                </p>
              ) : (
                <ul className={styles.cardList}>
                  {view.litters.map((l) => (
                    <li key={l.id}>
                      Född {fmtDate(l.birth_date)}
                      {l.litter_number != null
                        ? `, kull ${l.litter_number}`
                        : ""}
                      {l.mother ? `, mor ${l.mother}` : ""}
                      {l.father ? `, far ${l.father}` : ""}
                      {l.litter_size != null ? `, ${l.litter_size} födda` : ""}
                      {l.litter_size6w != null
                        ? `, ${l.litter_size6w} efter sex veckor`
                        : ""}
                    </li>
                  ))}
                </ul>
              )}
            </MbCard>

            <MbCard title={`Sålda under ${year}`}>
              {view.sales.length === 0 ? (
                <p>Inga försäljningar under {year} i Stamboken.</p>
              ) : (
                <ul className={styles.cardList}>
                  {view.sales.map((s) => (
                    <li key={s.individual_id}>
                      {s.number} till{" "}
                      {s.to_herd === "GX1" || s.to_herd === "MX1"
                        ? "utanför genbanken"
                        : s.to_herd}
                      , {fmtDate(s.date)}
                    </li>
                  ))}
                </ul>
              )}
            </MbCard>

            <MbCard title="Hälsa">
              <div id="halsa" tabIndex={-1} className={styles.detail}>
                <div
                  className={styles.choices}
                  role="radiogroup"
                  aria-label="Hälsa"
                >
                  {(
                    [
                      ["inga", "Inga sjukdomsfall eller defekter"],
                      ["ja", "Ja, fyll i"],
                    ] as const
                  ).map(([v, label]) => (
                    <label key={v} className={styles.choice}>
                      <input
                        type="radio"
                        name="health"
                        checked={state.health === v}
                        onChange={() => edit((s) => ({ ...s, health: v }))}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
                {state.health === "ja" && (
                  <>
                    {DISEASES.map(({ key, label }) => (
                      <div key={key} className={styles.line}>
                        <span
                          className={styles.label}
                          style={{ minWidth: "7em" }}
                        >
                          {label}
                        </span>
                        {key === "annat" && (
                          <input
                            className={styles.field}
                            aria-label="Annat, vad"
                            placeholder="Vad"
                            maxLength={100}
                            value={state.diseases.annat.namn}
                            onChange={(e) =>
                              edit((s) => ({
                                ...s,
                                diseases: {
                                  ...s.diseases,
                                  annat: {
                                    ...s.diseases.annat,
                                    namn: e.target.value,
                                  },
                                },
                              }))
                            }
                          />
                        )}
                        <input
                          className={styles.field}
                          style={{ width: "6ch" }}
                          inputMode="numeric"
                          aria-label={`${label}, antal kaniner`}
                          placeholder="Antal"
                          value={state.diseases[key].antal}
                          onChange={(e) =>
                            edit((s) => ({
                              ...s,
                              diseases: {
                                ...s.diseases,
                                [key]: {
                                  ...s.diseases[key],
                                  antal: e.target.value.replace(/\D/g, ""),
                                },
                              },
                            }))
                          }
                        />
                        <input
                          className={styles.field}
                          aria-label={`${label}, ålder`}
                          placeholder="Ålder"
                          maxLength={50}
                          value={state.diseases[key].alder}
                          onChange={(e) =>
                            edit((s) => ({
                              ...s,
                              diseases: {
                                ...s.diseases,
                                [key]: {
                                  ...s.diseases[key],
                                  alder: e.target.value,
                                },
                              },
                            }))
                          }
                        />
                      </div>
                    ))}
                    {state.defects.map((d, i) => (
                      <div key={i} className={styles.line}>
                        <select
                          className={styles.field}
                          aria-label="Kanin med defekt"
                          value={d.individual_id}
                          onChange={(e) =>
                            edit((s) => ({
                              ...s,
                              defects: s.defects.map((x, j) =>
                                j === i
                                  ? {
                                      ...x,
                                      individual_id: Number(e.target.value),
                                    }
                                  : x,
                              ),
                            }))
                          }
                        >
                          {rabbits.map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.number} {r.name}
                            </option>
                          ))}
                        </select>
                        <input
                          className={styles.field}
                          aria-label="Defekt"
                          placeholder="Vilken defekt"
                          maxLength={500}
                          value={d.beskrivning}
                          onChange={(e) =>
                            edit((s) => ({
                              ...s,
                              defects: s.defects.map((x, j) =>
                                j === i
                                  ? { ...x, beskrivning: e.target.value }
                                  : x,
                              ),
                            }))
                          }
                        />
                        <button
                          type="button"
                          className={`sb-btn sb-btn-ghost ${styles.btn}`}
                          onClick={() =>
                            edit((s) => ({
                              ...s,
                              defects: s.defects.filter((_, j) => j !== i),
                            }))
                          }
                        >
                          Ta bort
                        </button>
                      </div>
                    ))}
                    {rabbits.length > 0 && (
                      <div>
                        <button
                          type="button"
                          className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                          onClick={() =>
                            edit((s) => ({
                              ...s,
                              defects: [
                                ...s.defects,
                                {
                                  individual_id: rabbits[0].id,
                                  beskrivning: "",
                                },
                              ],
                            }))
                          }
                        >
                          Lägg till defekt
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </MbCard>

            <MbCard title="Meddelande">
              <label className={styles.label}>
                Meddelande till genbanksansvarig (frivilligt)
                <textarea
                  className={styles.field}
                  rows={3}
                  maxLength={2000}
                  value={state.message}
                  onChange={(e) =>
                    edit((s) => ({ ...s, message: e.target.value }))
                  }
                />
              </label>
            </MbCard>

            <MbCard title="Jag avslutar min genbank">
              <div className={styles.detail}>
                <label className={styles.line} style={{ minHeight: 48 }}>
                  <input
                    type="checkbox"
                    checked={state.ending}
                    onChange={(e) =>
                      edit((s) => ({ ...s, ending: e.target.checked }))
                    }
                  />
                  Jag avslutar min genbank
                </label>
                {state.ending && (
                  <>
                    <p className={styles.lead}>
                      Fyll gärna i döda och sålda kaniner också, så att
                      registret stämmer. Genbanken kan väckas igen genom att
                      kontakta genbanksansvarig, med samma besättningsnummer.
                    </p>
                    {!view.other_active_herd && (
                      <div
                        role="radiogroup"
                        aria-label="Medlemskapet"
                        className={styles.detail}
                      >
                        {(
                          [
                            [
                              "kvar_utan_genbank",
                              "Jag vill vara kvar i föreningen som medlem utan genbank",
                            ],
                            [
                              "avsluta_medlemskap",
                              "Jag vill även avsluta mitt medlemskap",
                            ],
                          ] as [Membership, string][]
                        ).map(([v, label]) => (
                          <label
                            key={v}
                            className={styles.line}
                            style={{ minHeight: 48 }}
                          >
                            <input
                              type="radio"
                              name="membership"
                              checked={state.membership === v}
                              onChange={() =>
                                edit((s) => ({ ...s, membership: v }))
                              }
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </MbCard>

            {contactSlot}

            {editor && (
              <MbCard title="Orsak">
                <label className={styles.label}>
                  Varför ändras rapporten?
                  <textarea
                    id="reason"
                    className={styles.field}
                    rows={2}
                    maxLength={500}
                    value={state.reason}
                    onChange={(e) =>
                      edit((s) => ({ ...s, reason: e.target.value }))
                    }
                  />
                </label>
              </MbCard>
            )}
          </fieldset>

          {lower}
          {phase === "timeout" ? (
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              onClick={() => send(frozen.current!)}
            >
              Försök igen
            </button>
          ) : (
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              onClick={skicka}
              disabled={sending}
            >
              {sending ? "Skickar…" : buttonText}
            </button>
          )}
        </>
      )}

      <SoldDialog
        open={soldFor !== null}
        number={soldRabbit?.number ?? ""}
        year={year}
        herds={view.herds}
        breed={breed}
        existing={
          soldFor !== null ? (state.rabbits[soldFor]?.sald ?? null) : null
        }
        onSave={(s: SaldState) => {
          onRow(soldFor!, { val: "sald", sald: s });
          setSoldFor(null);
        }}
        onClose={() => setSoldFor(null)}
      />
    </div>
  );
}
