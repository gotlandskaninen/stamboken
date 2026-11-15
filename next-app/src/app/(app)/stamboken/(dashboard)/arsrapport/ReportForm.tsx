"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { readModeCookieClient, type Mode } from "@/lib/mode";
import { MbCard } from "../min-besattning/min-besattning-ui";
import type * as Actions from "./actions";
import type { ActionResult } from "../inkorg/actions";
import {
  CONFLICT_TEXT,
  DISEASES,
  EMPTY_ENTRY,
  emptyPaperFields,
  emptyState,
  fmtDate,
  fmtTime,
  fromBody,
  isDone,
  keyAfter,
  matrikelBody,
  MATRIKEL_LABEL,
  newKey,
  paperKey,
  refusalText,
  stockholmDay,
  toBody,
  toDraft,
  todayStockholm,
  type DraftData,
  type Entry,
  type FormState,
  type Membership,
  type PaperField,
  type PaperFields,
  type Receipt as ReceiptData,
  type Refusal,
  type ReportView,
  type SaldState,
  type Submission,
} from "./lib";
import { NumberRow } from "./NumberRow";
import { PaperChanges } from "./PaperChanges";
import { RabbitRow } from "./RabbitRow";
import { Receipt } from "./Receipt";
import { ReportStatus, type StatusKind } from "./ReportStatus";
import { SoldDialog } from "./SoldDialog";
import styles from "./arsrapport.module.css";

export type ReportActions = Pick<
  typeof Actions,
  "saveDraft" | "dryRun" | "submitReport" | "withdrawReport"
>;

// "Från blankett": what the page around the form supplies (PaperEntry).
export interface PaperProps {
  documentIds: number[]; // formDocumentIds(item): the form pages still open
  intygPending: boolean; // the item's intyg come first (5.8)
  archive: (documentId: number) => Promise<ActionResult<unknown>>; // dismiss one page
  leave: (message: string) => void; // back to the queue, with a message
}
const QUEUE = "/stamboken/inkorg";
type Gate = "draft" | "reported" | null;
const enteredFrom = (rabbits: ReportView["rabbits"], s: FormState) =>
  rabbits
    .filter((r) => {
      const v = s.rabbits[r.id]?.val;
      return v && v !== "ej_angiven";
    })
    .map((r) => r.id);
// Paper starts from the helper's own draft; a member's draft and a submitted
// report wait behind a gate (5.5).
const startFrom = (v: ReportView, isPaper: boolean) =>
  isPaper
    ? fromBody(v.draft?.own ? v.draft.data : {})
    : fromBody(v.draft?.data ?? v.report?.submitted ?? {});
const gateOf = (v: ReportView, isPaper: boolean): Gate =>
  !isPaper
    ? null
    : v.report
      ? "reported"
      : v.draft?.own === false
        ? "draft"
        : null;
const summaryLine = (herd: string, r: ReceiptData) => {
  const { kvar, doda, salda, ej_angivna } = r.summary;
  return `${herd} inskickad: ${[
    `${kvar} finns kvar`,
    doda ? `${doda} ${doda === 1 ? "död" : "döda"}` : "",
    salda ? `${salda} ${salda === 1 ? "såld" : "sålda"}` : "",
    ej_angivna ? `${ej_angivna} ej angivna` : "",
  ]
    .filter(Boolean)
    .join(", ")}.`;
};

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
type ServerDraft = {
  data: DraftData;
  updated_at: string;
  submission_key: string | null;
};

const AUTOSAVE_MS = 2000;
const BIG_LIST = 30;
const NET_TEXT = "Det gick inte att nå servern. Försök igen.";

// A server action can reject when the browser loses the connection to the
// Next server: that becomes the same 502 as a dropped API connection.
async function safe<T>(
  call: Promise<ActionResult<T>>,
): Promise<ActionResult<T>> {
  try {
    return await call;
  } catch {
    return {
      ok: false,
      problem: { status: 502, title: "Bad Gateway", detail: NET_TEXT },
    };
  }
}

// localStorage holds what the server has not confirmed yet, apart per data
// environment (demo and prod answer from different databases). It never gets
// a buyer or a matrikel: toDraft strips them.
const localKey = (env: Mode, herd: string, year: number) =>
  `arsrapport:${env}:${herd}:${year}`;
const readLocal = (env: Mode, herd: string, year: number): DraftData | null => {
  try {
    const raw = window.localStorage.getItem(localKey(env, herd, year));
    return raw ? (JSON.parse(raw) as DraftData) : null;
  } catch {
    return null;
  }
};
const writeLocal = (
  env: Mode,
  herd: string,
  year: number,
  data: DraftData | null,
) => {
  try {
    if (data)
      window.localStorage.setItem(
        localKey(env, herd, year),
        JSON.stringify(data),
      );
    else window.localStorage.removeItem(localKey(env, herd, year));
  } catch {
    /* storage can be blocked: the server draft still works */
  }
};

// Focus the first control on a rabbit's row that still needs input.
function focusRow(id: number): boolean {
  const row = document.getElementById(`rabbit-${id}`);
  if (!row) return false;
  const target =
    row.querySelector<HTMLElement>("[data-need]") ??
    row.querySelector<HTMLElement>("input, select, button") ??
    row;
  target.focus();
  target.scrollIntoView?.({ block: "center" });
  return true;
}
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
    <Link
      href="/stamboken/profil"
      className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
    >
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
  env,
  paper,
}: {
  view: ReportView;
  actions: ReportActions;
  contactSlot?: React.ReactNode;
  stickyTop?: number;
  post?: number;
  paper?: PaperProps;
  // The data environment the view was read from; the page mounts the form
  // with key={env}, so a switch starts over from the other one's draft.
  env: Mode;
}) {
  const router = useRouter();
  const { herd, year, round } = view;
  const editor = view.access === "manager" || view.access === "admin";
  const item = paper ? view.item : null; // paper entry runs through a queue item
  const isPaper = !!item;
  const canEdit =
    round.open || ((editor || view.access === "helper") && round.activated);
  // Paper over a report, or after the last day: Skicka needs a reason (D11).
  const late = !!round.end_date && todayStockholm() > round.end_date;
  const needReason = isPaper && (!!view.report || late);

  const [state, setState] = React.useState<FormState>(() =>
    startFrom(view, isPaper),
  );
  const [gate, setGate] = React.useState<Gate>(() => gateOf(view, isPaper));
  const [fields, setFields] = React.useState<PaperFields>(emptyPaperFields);
  const [receivedOn, setReceivedOn] = React.useState(() =>
    item ? stockholmDay(item.received_at) : "",
  );
  const [signedOn, setSignedOn] = React.useState<string | null>(null); // null: the day it came in
  const [entered, setEntered] = React.useState<number[]>(() =>
    enteredFrom(view.rabbits, startFrom(view, isPaper)),
  );
  const [archiving, setArchiving] = React.useState(false);
  const [archiveError, setArchiveError] = React.useState<string | null>(null);
  const [mode, setMode] = React.useState<"form" | "receipt">(
    view.report && !isPaper ? "receipt" : "form",
  );
  const [version, setVersion] = React.useState(0);
  const [retry, setRetry] = React.useState(0);
  const [saveState, setSaveState] = React.useState<SaveState>("saved");
  const [savedAt, setSavedAt] = React.useState<string | null>(
    view.draft ? fmtTime(view.draft.updated_at) : null,
  );
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [refusals, setRefusals] = React.useState<Refusal[] | null>(null);
  const [receipt, setReceipt] = React.useState<ReceiptData | null>(null);
  const [withdrawn, setWithdrawn] = React.useState<string | null>(null);
  const [withdrawing, setWithdrawing] = React.useState(false);
  const [localCopy, setLocalCopy] = React.useState(false);
  const [filter, setFilter] = React.useState<Filter>("alla");
  const [snapshot, setSnapshot] = React.useState<Set<number>>(new Set());
  const [search, setSearch] = React.useState("");
  const [soldFor, setSoldFor] = React.useState<number | null>(null);
  const [seenEnd, setSeenEnd] = React.useState(false);
  const [askRest, setAskRest] = React.useState(false);
  const [focusTick, setFocusTick] = React.useState(0);
  const [syncing, setSyncing] = React.useState(false);
  const [syncTimeout, setSyncTimeout] = React.useState(false);
  const syncTimer = React.useRef<ReturnType<typeof setTimeout>>(undefined);

  // Latest values for callbacks that outlive a render. Kept in effects, never
  // written during render.
  const stateRef = React.useRef(state);
  const viewRef = React.useRef(view);
  const versionRef = React.useRef(0);
  const routerRef = React.useRef(router);
  const actionsRef = React.useRef(actions);
  React.useEffect(() => {
    stateRef.current = state;
    viewRef.current = view;
    versionRef.current = version;
    routerRef.current = router;
    actionsRef.current = actions;
  });
  const keyRef = React.useRef<string | null>(null);
  if (keyRef.current === null)
    keyRef.current = view.draft?.submission_key ?? newKey();
  const updatedAt = React.useRef<string | null>(view.draft?.updated_at ?? null);
  const frozen = React.useRef<Submission | null>(null);
  const visibleIds = React.useRef<number[]>([]);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const stopped = React.useRef(false);
  const saving = React.useRef(false);
  const again = React.useRef(false);
  const resync = React.useRef(false);
  const pendingFocus = React.useRef<number | null>(null);
  const pendingEl = React.useRef<string | null>(null);

  const edit = React.useCallback((fn: (s: FormState) => FormState) => {
    setState(fn);
    setVersion((v) => v + 1);
  }, []);

  // A copy the server never confirmed (closed tab, lost connection) wins.
  React.useEffect(() => {
    const local = readLocal(env, herd.herd, year);
    if (local) {
      const s = fromBody(local);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage exists only after hydration
      setState(s);
      setEntered(enteredFrom(viewRef.current.rabbits, s));
      setLocalCopy(true);
      setVersion((v) => v + 1);
    }
  }, [env, herd.herd, year]);

  // The server's draft replaces the whole editing state: form, mode and key.
  const adoptDraft = (d: ServerDraft) => {
    const s = fromBody(d.data);
    setState(s);
    setEntered(enteredFrom(view.rabbits, s));
    updatedAt.current = d.updated_at;
    // a draft with no key (written by Dra tillbaka) must not revive a spent one
    keyRef.current = d.submission_key ?? newKey();
    setSavedAt(fmtTime(d.updated_at));
    writeLocal(env, herd.herd, year, null);
    setLocalCopy(false);
    setMode("form");
    setVersion(0);
  };
  // A conflict with no draft to adopt (a report was submitted meanwhile): load
  // ReportView again and reset everything from it when it arrives.
  const reload = () => {
    resync.current = true;
    stopped.current = true;
    setSoldFor(null); // a sale dialog cannot save into a state about to be replaced
    setSyncing(true); // editing and Skicka wait for the answer
    router.refresh();
    clearTimeout(syncTimer.current);
    // No answer after 10 s: stay locked and offer a full reload. A late
    // answer still syncs the form (the effect below).
    syncTimer.current = setTimeout(() => setSyncTimeout(true), 10000);
  };
  React.useEffect(() => {
    if (!resync.current) return;
    resync.current = false;
    stopped.current = false;
    clearTimeout(syncTimer.current);
    setSyncTimeout(false);
    setSyncing(false);
    const next = startFrom(view, isPaper);
    setState(next);
    setEntered(enteredFrom(view.rabbits, next));
    setGate(gateOf(view, isPaper));
    setMode(view.report && !isPaper ? "receipt" : "form");
    setVersion(0);
    setReceipt(null);
    setPhase("idle");
    setLocalCopy(false);
    keyRef.current = view.draft?.submission_key ?? newKey();
    updatedAt.current = view.draft?.updated_at ?? null;
    frozen.current = null;
    writeLocal(env, view.herd.herd, view.year, null);
  }, [view, env, isPaper]);

  // One save in flight at a time: a change made meanwhile is sent after it
  // has been answered, with the version it returned.
  const flush = async () => {
    if (saving.current) {
      again.current = true;
      return;
    }
    saving.current = true;
    try {
      do {
        again.current = false;
        if (readModeCookieClient() !== env) {
          stopped.current = true; // never save into the other environment
          break;
        }
        const mine = versionRef.current;
        const slow = setTimeout(() => setSaveState("saving"), 1000);
        const res = await safe(
          actionsRef.current.saveDraft(
            herd.herd,
            year,
            toDraft(stateRef.current),
            updatedAt.current,
            keyRef.current!,
            viewRef.current.report?.revision ?? null,
            env,
            post,
          ),
        );
        clearTimeout(slow);
        if (res.ok) {
          updatedAt.current = res.data.updated_at;
          setSavedAt(fmtTime(res.data.updated_at));
          setSaveState("saved");
          if (versionRef.current === mine)
            writeLocal(env, herd.herd, year, null);
          continue;
        }
        const p = res.problem;
        const ext = p.extensions ?? {};
        if (p.status === 409 && "draft" in ext) {
          if (ext.draft) adoptDraft(ext.draft as ServerDraft);
          else reload();
          setSaveState("conflict");
        } else if (p.status === 409 && ext.code === "rundan_stangd") {
          stopped.current = true;
          setSaveState("closed");
        } else if (p.status === 401) setSaveState("loggedout");
        else {
          setSaveState("offline");
          setTimeout(() => setRetry((n) => n + 1), 5000); // the page tries again
        }
        again.current = false;
      } while (again.current);
    } finally {
      saving.current = false;
    }
  };
  const flushRef = React.useRef(flush);
  React.useEffect(() => {
    flushRef.current = flush;
  });

  // Autosave: 2 s after the last change, from the revision the page started from.
  React.useEffect(() => {
    if (version === 0 || mode !== "form" || !canEdit || stopped.current) return;
    writeLocal(env, herd.herd, year, toDraft(stateRef.current));
    const t = setTimeout(() => void flushRef.current(), AUTOSAVE_MS);
    return () => clearTimeout(t);
  }, [version, retry, mode, canEdit, env, herd.herd, year]);

  const rabbits = view.rabbits;
  const lastId = rabbits.length ? rabbits[rabbits.length - 1].id : null;
  const lastVisible = React.useRef(false);

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
  const lastShown = lastId !== null && visible.some((r) => r.id === lastId);
  React.useEffect(() => {
    visibleIds.current = visible.map((r) => r.id);
    lastVisible.current = lastShown;
  });

  // "Markera resten" waits until the real last row has been on screen.
  React.useEffect(() => {
    if (mode !== "form" || lastId === null || !lastShown) return;
    if (typeof IntersectionObserver === "undefined") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no observer in this browser
      setSeenEnd(true);
      return;
    }
    const el = document.getElementById(`rabbit-${lastId}`);
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setSeenEnd(true);
    });
    io.observe(el);
    return () => io.disconnect();
  }, [mode, lastId, lastShown]);

  React.useEffect(() => {
    if (refusals) boxRef.current?.focus();
  }, [refusals]);

  // An error link or Enter on a search hit: show the rabbit, then focus.
  const reveal = (id: number) => {
    setSearch("");
    setFilter("alla");
    pendingFocus.current = id;
    setFocusTick((t) => t + 1);
  };
  React.useEffect(() => {
    const id = pendingFocus.current;
    if (id !== null && focusRow(id)) pendingFocus.current = null;
    if (pendingEl.current) {
      document.getElementById(pendingEl.current)?.focus();
      pendingEl.current = null;
    }
  }, [focusTick]);
  const focusLater = (elementId: string | null) => {
    pendingEl.current = elementId;
    setFocusTick((t) => t + 1);
  };

  // Paper: the keys of a rabbit's row (paperKey holds the chain). 1, 2 and 3
  // only choose on the radio group, never in a field.
  const onPaperKey = (e: React.KeyboardEvent<HTMLElement>) => {
    const t = e.target as HTMLElement;
    const field = t.dataset.paperField as PaperField | undefined;
    const row = t.closest<HTMLElement>("fieldset[id^='rabbit-']");
    if (!field || !row || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey)
      return;
    const id = Number(row.id.slice("rabbit-".length));
    const before = { field, val: stateRef.current.rabbits[id]?.val ?? null };
    const next = paperKey(before, e.key);
    if (next.field === before.field && next.val === before.val) return;
    e.preventDefault();
    if (next.val !== before.val)
      document.getElementById(`val-${id}-${next.val}`)?.click(); // the row's own choose()
    focusLater(
      {
        number: "paper-number",
        val: `val-${id}-kvar`,
        vikt: `vikt-${id}`,
        ej_vagd: `ejvagd-${id}`,
        hull: `hull-${id}`,
        month: `month-${id}`,
        sold: null, // the dialog takes the focus
      }[next.field],
    );
  };
  const pickRabbit = (id: number) => {
    setEntered((e) => [...e, id]);
    focusLater(`val-${id}-kvar`);
  };
  const markNotStated = () => {
    const on = new Set(entered);
    edit((s) => {
      const next = { ...s.rabbits };
      for (const r of viewRef.current.rabbits)
        if (r.state === "att_valja" && !on.has(r.id) && !next[r.id]?.val)
          next[r.id] = { ...EMPTY_ENTRY, val: "ej_angiven" };
      return { ...s, rabbits: next };
    });
  };

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
  const fail = (message: string) =>
    setRefusals([{ individual_id: null, code: "fel", message }]);

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
      // Someone changed or sent the report: show the current one.
      setSaveState("conflict");
      reload();
    } else fail(p.detail || NET_TEXT);
    setPhase("idle");
  };

  const ENV_TEXT = "Miljön har bytts. Ladda om sidan.";
  const send = async (body: Submission) => {
    if (readModeCookieClient() !== env) return fail(ENV_TEXT);
    setPhase("sending");
    const res = await safe(
      actionsRef.current.submitReport(herd.herd, year, body, env, post),
    );
    if (res.ok) {
      keyRef.current = keyAfter("ok", keyRef.current!);
      frozen.current = null;
      updatedAt.current = null;
      writeLocal(env, herd.herd, year, null);
      setLocalCopy(false);
      setReceipt(res.data);
      setMode("receipt");
      setPhase("idle");
      setWithdrawn(null);
      // On paper the submit has closed the item: ReportView is not read again
      // (with ?post= it would be refused), and the Receipt is the answer.
      if (!isPaper) router.refresh();
      else if (!res.data.warnings.length && !res.data.matrikel.length)
        paper!.leave(summaryLine(herd.herd, res.data));
    } else if (
      res.problem.status === 408 ||
      res.problem.status === 502 ||
      res.problem.status === 504
    )
      setPhase("timeout"); // the same key and the same body go again
    else handle(res.problem);
  };

  const skicka = async () => {
    if (phase !== "idle" || syncing) return;
    setRefusals(null);
    if (readModeCookieClient() !== env) return fail(ENV_TEXT);
    let body = toBody(state, keyRef.current!, view.report?.revision ?? null);
    if (isPaper) {
      const signed = signedOn ?? receivedOn;
      if (!receivedOn) return fail("Ange dagen blanketten kom in.");
      if (signed > receivedOn)
        return fail(
          "Blankettens datum kan inte vara senare än dagen den kom in.",
        );
      const matrikel = matrikelBody(fields);
      body = {
        ...body,
        inbox_item_id: item.id,
        received_on: receivedOn,
        signed_on: signed,
        ...(matrikel ? { matrikel } : {}),
      };
    }
    frozen.current = body; // never stored: it may hold a buyer or a matrikel
    setPhase("checking");
    const dry = await safe(
      actionsRef.current.dryRun(herd.herd, year, body, env, post),
    );
    if (!dry.ok) {
      if (dry.problem.status === 408 || dry.problem.status === 502) {
        fail(NET_TEXT);
        return setPhase("idle");
      }
      return handle(dry.problem);
    }
    if (!dry.data.ok) {
      setRefusals(dry.data.refusals);
      return setPhase("idle");
    }
    await send(body);
  };

  const withdraw = async (reason?: string): Promise<string | null> => {
    if (readModeCookieClient() !== env) return ENV_TEXT;
    setWithdrawing(true);
    const res = await safe(
      actionsRef.current.withdrawReport(
        herd.herd,
        year,
        view.report!.revision,
        reason,
        env,
        post,
      ),
    );
    setWithdrawing(false);
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
      setVersion(0); // so that "Dragen tillbaka" shows until the next edit
      router.refresh();
      return null;
    }
    const ext = res.problem.extensions ?? {};
    if (res.problem.status === 403)
      return "Tiden för att dra tillbaka rapporten har gått ut.";
    if (res.problem.status === 409) return `${CONFLICT_TEXT}. Ladda om sidan.`;
    if (Array.isArray(ext.refusals))
      return refusalText((ext.refusals as Refusal[])[0]);
    return res.problem.status === 502 ? NET_TEXT : res.problem.detail;
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
  const status: StatusKind = syncing
    ? { kind: "syncing" }
    : phase === "timeout"
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
    ? round.deadline < todayStockholm()
      ? ({ kind: "late", deadline: fmtDate(round.deadline) } as const)
      : ({ kind: "deadline", deadline: fmtDate(round.deadline) } as const)
    : null;
  const closedText = !view.report && !canEdit;
  const breed = view.herd.genebank.toLowerCase();
  const heading = item ? (
    <header>
      <h1 className={styles.title}>
        Från blankett · {herd.herd} · Ärende {item.id}
      </h1>
      <p className={styles.herdLine}>
        {herd.name} <Link href={`${QUEUE}/${item.id}`}>Till ärendet</Link>
      </p>
    </header>
  ) : (
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

  if (mode === "receipt" && isPaper && receipt) {
    // The submit closed the item: the Receipt alone, with what the matrikel took.
    return (
      <div className={styles.root} style={root}>
        {heading}
        <Receipt
          view={{ ...view, report: null }}
          receipt={receipt}
          hasDraft={false}
          busy={false}
          onChange={startChange}
          onWithdraw={withdraw}
        />
        {receipt.matrikel.length > 0 && (
          <div className={`${styles.status} ${styles.info}`}>
            <p>
              Sparat i matrikeln:{" "}
              {receipt.matrikel.map((f) => MATRIKEL_LABEL[f] ?? f).join(", ")}.
            </p>
          </div>
        )}
        <div className={styles.actions}>
          <Link href={QUEUE} className={`sb-btn ${styles.btn}`}>
            Nästa blankett
          </Link>
        </div>
      </div>
    );
  }
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
          busy={withdrawing || syncing}
          onChange={startChange}
          onWithdraw={withdraw}
        />
      </div>
    );
  }

  // The gates in front of the paper form: the item's intyg, a member's draft,
  // a report already sent (at most one shows).
  const archive = async () => {
    setArchiveError(null);
    setArchiving(true);
    let failed = false;
    for (const id of paper!.documentIds) {
      const res = await safe(paper!.archive(id));
      if (!res.ok) failed = true;
    }
    setArchiving(false);
    if (failed)
      setArchiveError("Det gick inte att arkivera blanketten. Försök igen.");
    else paper!.leave(`Blanketten för ${herd.herd} är arkiverad.`);
  };
  if (isPaper && (paper!.intygPending || gate)) {
    return (
      <div className={styles.root} style={root}>
        {heading}
        {paper!.intygPending ? (
          <div className={`${styles.status} ${styles.info}`} role="status">
            <p>
              Registrera intygen i ärendet först.{" "}
              <Link href={`${QUEUE}/${item.id}`}>Till ärendet</Link>
            </p>
          </div>
        ) : gate === "draft" ? (
          <MbCard title="Medlemmen har påbörjat rapporten">
            <p>
              Medlemmen har påbörjat rapporten (senast{" "}
              {fmtDate(view.draft!.updated_at)}).
            </p>
            <div className={styles.actions}>
              <button
                type="button"
                className={`sb-btn ${styles.btn}`}
                onClick={() => {
                  const s = fromBody(view.draft!.data);
                  setState(s);
                  setEntered(enteredFrom(rabbits, s));
                  setGate(null);
                }}
              >
                Fortsätt på medlemmens utkast
              </button>
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={() => setGate(null)}
              >
                Börja från blanketten
              </button>
            </div>
          </MbCard>
        ) : (
          <MbCard title="Redan rapporterad">
            <p>Redan rapporterad den {fmtDate(view.report!.received_at)}.</p>
            <label className={styles.label}>
              Varför ändras rapporten?
              <textarea
                className={styles.field}
                rows={2}
                maxLength={500}
                value={state.reason}
                onChange={(e) =>
                  setState((s) => ({ ...s, reason: e.target.value }))
                }
              />
            </label>
            {archiveError && (
              <p className={styles.errorText} role="alert">
                {archiveError}
              </p>
            )}
            <div className={styles.actions}>
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                disabled={archiving}
                onClick={archive}
              >
                Arkivera blanketten
              </button>
              <button
                type="button"
                className={`sb-btn ${styles.btn}`}
                disabled={archiving || !state.reason.trim()}
                onClick={() => {
                  const base = fromBody(
                    view.draft?.own
                      ? view.draft.data
                      : (view.report!.submitted ?? {}),
                  );
                  setState({ ...base, reason: state.reason });
                  setEntered(enteredFrom(rabbits, base));
                  setGate(null);
                }}
              >
                Ändra rapporten
              </button>
            </div>
          </MbCard>
        )}
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
  const buttonText = isPaper
    ? "Skicka och nästa blankett"
    : view.report
      ? "Skicka ändringarna"
      : "Skicka årsrapporten";
  const sending = phase === "checking" || phase === "sending";
  const lower = <ReportStatus status={status} />;
  const endCard = (
    <MbCard title="Jag avslutar min genbank">
      <div className={styles.detail}>
        <label className={styles.line} style={{ minHeight: 48 }}>
          <input
            type="checkbox"
            checked={state.ending}
            onChange={(e) => edit((s) => ({ ...s, ending: e.target.checked }))}
          />
          Jag avslutar min genbank
        </label>
        {state.ending && (
          <>
            <p className={styles.lead}>
              Fyll gärna i döda och sålda kaniner också, så att registret
              stämmer. Genbanken kan väckas igen genom att kontakta
              genbanksansvarig, med samma besättningsnummer.
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
                      onChange={() => edit((s) => ({ ...s, membership: v }))}
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
  );
  // Paper: the rows typed in, in the order they were typed, and the rest of the
  // register that the form does not mention.
  const noop = () => undefined;
  const enteredSet = new Set(entered);
  const enteredRabbits = entered.flatMap((id) => byId.get(id) ?? []);
  const restRabbits = rabbits.filter(
    (r) => r.state === "att_valja" && !enteredSet.has(r.id),
  );
  const unchosen = restRabbits.filter((r) => !state.rabbits[r.id]?.val).length;

  return (
    <div
      className={`${styles.root} ${closedText || isPaper ? "" : styles.wide} ${isPaper ? styles.paperForm : ""}`}
      style={root}
      data-report-root={stickyTop === 0 ? "bare" : "shell"}
    >
      {heading}
      <p className={styles.lead}>
        Gäller kaninerna i {herd.herd} den 31 december {year}.
      </p>
      {editor && !isPaper && (
        <ReportStatus status={{ kind: "editor", herd: herd.herd }} />
      )}
      {closedText ? (
        <ReportStatus status={{ kind: "closed" }} />
      ) : (
        <div className={styles.layout}>
          <div className={styles.side}>
            <div className={styles.sideStatus}>
              <ReportStatus status={status} />
              {deadline && <ReportStatus status={deadline} />}
              {syncTimeout && (
                <div role="alert" className={styles.errorBox}>
                  <h2>Det gick inte att hämta senaste versionen</h2>
                  <button
                    type="button"
                    className={`sb-btn ${styles.btn}`}
                    onClick={() => window.location.reload()}
                  >
                    Ladda om sidan
                  </button>
                </div>
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
                              reveal(id!);
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
                        {r.code === "halsa_saknas" ||
                        r.code === "orsak_kravs" ? (
                          <a
                            href={
                              r.code === "halsa_saknas" ? "#halsa" : "#reason"
                            }
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
                      className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                      onClick={() => chooseFilter("inte_klara")}
                    >
                      Visa bara dem som inte är klara
                    </button>
                  )}
                </div>
              )}
            </div>
            {!isPaper && (
              <>
                <div className={`${styles.sticky} ${styles.sideBar}`}>
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
                        focusRow(visible[0].id);
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

                <div
                  className={`${styles.filters} ${styles.sideFilters}`}
                  role="group"
                  aria-label="Visa"
                >
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
              </>
            )}

            <div className={styles.sideSend}>
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
                  disabled={sending || syncing}
                >
                  {sending ? "Skickar…" : buttonText}
                </button>
              )}
            </div>
          </div>
          <fieldset
            disabled={phase !== "idle" || syncing}
            className={styles.main}
          >
            {isPaper && (
              <MbCard title="Blanketten">
                <div className={styles.grid2}>
                  <label className={styles.label}>
                    Mottagen
                    <input
                      type="date"
                      className={styles.field}
                      style={{ width: "100%", boxSizing: "border-box" }}
                      value={receivedOn}
                      max={todayStockholm()}
                      onChange={(e) => setReceivedOn(e.target.value)}
                    />
                  </label>
                  <label className={styles.label}>
                    Blankettens datum
                    <input
                      type="date"
                      className={styles.field}
                      style={{ width: "100%", boxSizing: "border-box" }}
                      value={signedOn ?? receivedOn}
                      max={receivedOn || undefined}
                      onChange={(e) => setSignedOn(e.target.value)}
                    />
                  </label>
                </div>
              </MbCard>
            )}
            {isPaper && endCard}
            {isPaper && (
              <PaperChanges
                fields={fields}
                onChange={setFields}
                accountEnd={item.account_end}
              />
            )}
            {isPaper ? (
              <>
                <div className="sb-card-flat" onKeyDown={onPaperKey}>
                  <div className={styles.list}>
                    {enteredRabbits.map((r) => (
                      <RabbitRow
                        key={r.id}
                        r={r}
                        paper
                        entry={state.rabbits[r.id]}
                        ending={state.ending}
                        year={year}
                        canSell={view.can_sell}
                        done={!!done.get(r.id)}
                        error={rowErrors.get(r.id)}
                        onChange={onRow}
                        onSell={onSell}
                        onNextWeight={noop}
                      />
                    ))}
                    <NumberRow
                      herd={herd.herd}
                      year={year}
                      rabbits={rabbits}
                      entered={entered}
                      onPick={pickRabbit}
                    />
                  </div>
                </div>
                <MbCard
                  title={`Kvar i Stamboken men inte på blanketten (${unchosen})`}
                >
                  {unchosen > 0 && (
                    <button
                      type="button"
                      className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                      onClick={markNotStated}
                    >
                      Markera som ej angivna på blanketten
                    </button>
                  )}
                  <div onKeyDown={onPaperKey}>
                    {restRabbits.map((r) => (
                      <RabbitRow
                        key={r.id}
                        r={r}
                        paper
                        entry={state.rabbits[r.id]}
                        ending={state.ending}
                        year={year}
                        canSell={view.can_sell}
                        done={!!done.get(r.id)}
                        error={rowErrors.get(r.id)}
                        onChange={onRow}
                        onSell={onSell}
                        onNextWeight={noop}
                      />
                    ))}
                  </div>
                </MbCard>
              </>
            ) : rabbits.length === 0 ? (
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
            {!isPaper &&
              rabbits.length > BIG_LIST &&
              seenEnd &&
              restCount > 0 && (
                <div className={styles.detail}>
                  {askRest ? (
                    <div
                      className={styles.note}
                      role="alertdialog"
                      aria-label="Markera resten"
                    >
                      <span>
                        Markera {restCount} kaniner som finns kvar? Vuxna
                        kaniner behöver ändå vikt eller Ej vägd.
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
                        className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
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

            {!isPaper && endCard}

            {!isPaper && contactSlot}

            {(isPaper ? needReason : editor) && (
              <MbCard title="Orsak">
                <label className={styles.label}>
                  {isPaper && !view.report
                    ? "Varför kommer blanketten in efter sista dagen?"
                    : "Varför ändras rapporten?"}
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
        </div>
      )}

      <SoldDialog
        open={soldFor !== null && !syncing}
        number={soldRabbit?.number ?? ""}
        year={year}
        herds={view.herds}
        breed={breed}
        existing={
          soldFor !== null ? (state.rabbits[soldFor]?.sald ?? null) : null
        }
        onSave={(s: SaldState) => {
          if (syncing) return;
          onRow(soldFor!, { val: "sald", sald: s });
          setSoldFor(null);
          if (isPaper) focusLater("paper-number"); // the next row
        }}
        onClose={() => setSoldFor(null)}
      />
    </div>
  );
}
