"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useDebounce } from "@/hooks/useDebounce";
import { useUser } from "@/lib/user-context";
import { useTestbreedMutation } from "@/redux/api/apiSlice";
import type { PaginatedIndividualItem } from "@/redux/api/apiSlice";
import {
  MAX_MALES,
  buildTestbreedRequest,
  createSequence,
  deriveMaleSlots,
  editLayout,
  effectiveSelection,
  emptySlot,
  EMPTY_LAYOUT,
  formatPercent,
  layoutFor,
  paramsFromSearch,
  pickedFromIndividual,
  replaceMale,
  serializeProvparningParams,
  settleLayout,
  slotNow,
  sortResults,
  tooManyMales,
  withDetails,
  type AnimalInput,
  type SlotLayout,
  type ProvparningParams,
  type ServerSelection,
  type Slot,
  type TestbreedRequest,
  type TestbreedResponse,
} from "@/lib/provparning";
import { AnimalPicker } from "./AnimalPicker";
import { AnimalName, ResultCard } from "./ResultCard";
import styles from "./provparning.module.css";

interface Props {
  genebanks: { id: number; name: string }[];
  /** serializeProvparningParams() of the URL the server rendered. */
  requestedQuery: string;
  initialGenebankId: number | null;
  initialFemale: PaginatedIndividualItem | null;
  initialMales: PaginatedIndividualItem[];
}

type Sex = "female" | "male";

let keyCounter = 0;
const newKey = () => `a${++keyCounter}`;

const canonical = (qs: string) =>
  serializeProvparningParams(paramsFromSearch(qs));

const stub = (number: string, sex: Sex) =>
  pickedFromIndividual({ number, name: null, sex, herd: "", alive: true });

/**
 * The male slot layout. A store rather than state: two edits in one task
 * must see each other's layout before React renders (the second edit of the
 * same slot replaces what the first one wrote, not what is on screen).
 */
function createLayoutStore() {
  let layout = EMPTY_LAYOUT;
  const listeners = new Set<() => void>();
  return {
    get: () => layout,
    set: (next: SlotLayout) => {
      if (next === layout) return;
      layout = next;
      listeners.forEach((l) => l());
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

function describeError(err: unknown): string {
  const e = err as { status?: number | string; data?: { detail?: string } };
  if (e?.status === 429)
    return "För många beräkningar just nu. Vänta en stund och försök igen.";
  if (typeof e?.data?.detail === "string") return e.data.detail;
  return "Beräkningen misslyckades. Försök igen.";
}

/**
 * The URL is the only store of the registered selection (genebank, hona,
 * hane): every render derives it from useSearchParams(), and edits write it
 * with history.replaceState, which Next's app router feeds back into
 * useSearchParams(). A link, back/forward or a router-cache hit changes the
 * form exactly like an edit does — there is nothing to tell apart.
 *
 * Kept locally, never as a copy of the selection: details (name, herd) of
 * animals for the pickers, and per genebank (keyed child) the slot layout,
 * the unregistered ("inte registrerad än") slots and the calculation.
 */
export function ProvparningClient({
  genebanks,
  requestedQuery,
  initialGenebankId,
  initialFemale,
  initialMales,
}: Props) {
  const pathname = usePathname();
  const search = useSearchParams().toString();

  const server = useMemo<ServerSelection>(
    () => ({
      query: requestedQuery,
      selection: {
        genebank: initialGenebankId,
        hona: initialFemale?.number ?? null,
        hane: initialMales.map((m) => m.number),
      },
    }),
    [requestedQuery, initialGenebankId, initialFemale, initialMales],
  );
  const genebankIds = useMemo(() => genebanks.map((g) => g.id), [genebanks]);
  const selectionOf = useCallback(
    (qs: string) =>
      effectiveSelection(paramsFromSearch(qs), server, genebankIds),
    [server, genebankIds],
  );
  const selection = useMemo(() => selectionOf(search), [selectionOf, search]);

  // Edits start from the browser's URL, not from this render's
  // useSearchParams(): the router applies a replaceState in a later render,
  // so two quick edits would otherwise both start from the same old URL.
  const current = useCallback(
    () => ({
      query: canonical(window.location.search),
      selection: selectionOf(window.location.search),
    }),
    [selectionOf],
  );
  // history.replaceState rather than router.replace: no history spam and no
  // server round trip per change. Returns the query now in the URL.
  const write = useCallback(
    (next: ProvparningParams) => {
      const qs = serializeProvparningParams(next);
      if (qs === canonical(window.location.search)) return qs;
      try {
        window.history.replaceState(
          null,
          "",
          qs ? `${pathname}?${qs}` : pathname,
        );
      } catch {
        // The URL could not be written; the form keeps showing what it has.
      }
      return qs;
    },
    [pathname],
  );

  // Details by number: the server-resolved props, then every autocomplete
  // pick. A number known by neither (only possible on a URL from outside
  // that the server did not render) shows as the bare number — the
  // calculation needs nothing more.
  const [picks, setPicks] = useState<
    ReadonlyMap<string, PaginatedIndividualItem>
  >(() => new Map());
  const remember = useCallback(
    (item: PaginatedIndividualItem | null | undefined) =>
      setPicks((m) => withDetails(m, [item ?? null])),
    [],
  );
  const details = useMemo(() => {
    const known = withDetails(new Map(), [
      initialFemale,
      ...initialMales,
      ...picks.values(),
    ]);
    const missing = (n: string | null, sex: Sex) =>
      n && !known.has(n) ? stub(n, sex) : null;
    // One stub per URL, not per render: a new value object would make the
    // autocomplete reset its input text.
    return withDetails(known, [
      missing(selection.hona, "female"),
      ...selection.hane.map((n) => missing(n, "male")),
    ]);
  }, [initialFemale, initialMales, picks, selection]);
  const detail = useCallback(
    (number: string, sex: Sex) => details.get(number) ?? stub(number, sex),
    [details],
  );

  if (genebanks.length === 0) {
    return (
      <div className={styles.container}>
        <p className={`sb-card ${styles.empty}`}>
          Du har inte åtkomst till någon genbank.
        </p>
      </div>
    );
  }

  return (
    <ProvparningForm
      // Another genebank (own choice, link or back) starts a fresh layout.
      key={selection.genebank ?? ""}
      genebanks={genebanks}
      selection={selection}
      query={canonical(search)}
      current={current}
      write={write}
      detail={detail}
      remember={remember}
    />
  );
}

function ProvparningForm({
  genebanks,
  selection,
  query,
  current,
  write,
  detail,
  remember,
}: {
  genebanks: { id: number; name: string }[];
  selection: ProvparningParams;
  /** The URL's query in canonical form. */
  query: string;
  current: () => { query: string; selection: ProvparningParams };
  write: (next: ProvparningParams) => string;
  detail: (number: string, sex: Sex) => PaginatedIndividualItem;
  remember: (item: PaginatedIndividualItem | null | undefined) => void;
}) {
  const ownHerd = useUser().is_owner?.[0];
  const genebankId = selection.genebank;

  // Layout only: which numbers are chosen always comes from `selection`.
  const [femaleSlot, setFemaleSlot] = useState<Slot>(() => emptySlot(newKey()));
  const [store] = useState(createLayoutStore);
  const layout = useSyncExternalStore(store.subscribe, store.get, store.get);
  // The URL has been seen at this query: a write that led here is done. After
  // every commit, not on `query` changes: a navigation can land on the same
  // query the router showed before the write it never committed.
  useEffect(() => {
    store.set(
      settleLayout(store.get(), query, canonical(window.location.search)),
    );
  });

  const toInput = (slot: Slot, sex: Sex): AnimalInput => ({
    key: slot.key,
    picked: slot.number ? detail(slot.number, sex) : null,
    unregistered: slot.unregistered,
    mother: slot.mother,
    father: slot.father,
  });
  const female = toInput(
    selection.hona
      ? { ...femaleSlot, number: selection.hona, unregistered: false }
      : femaleSlot.unregistered
        ? femaleSlot
        : { ...femaleSlot, number: null },
    "female",
  );
  const maleSlots = deriveMaleSlots(layoutFor(layout, query), selection.hane);
  const males = maleSlots.map((s) => toInput(s, "male"));

  const changeFemale = (patch: Partial<AnimalInput>) => {
    const { selection: cur } = current();
    if ("picked" in patch) {
      write({ ...cur, hona: patch.picked?.number ?? null });
      remember(patch.picked);
    } else if (patch.unregistered) {
      write({ ...cur, hona: null });
      setFemaleSlot((f) => ({ ...f, unregistered: true, number: cur.hona }));
    } else if (patch.unregistered === false) {
      write({ ...cur, hona: cur.hona ?? femaleSlot.number });
      setFemaleSlot((f) => ({ ...f, unregistered: false }));
    } else {
      setFemaleSlot((f) => ({ ...f, ...patch }));
    }
  };

  // Edits slot `key` as the latest edit left it (slotNow), writes the new
  // male list (if any) and applies `edit` to the layout.
  const editMale = (
    key: string,
    plan: (slot: Slot) => {
      hane?: (cur: string[]) => string[];
      edit: (all: Slot[]) => Slot[];
    },
  ) => {
    const { query: from, selection: cur } = current();
    const latest = store.get();
    const slot = slotNow(latest, from, cur.hane, key);
    if (!slot) return;
    const { hane, edit } = plan(slot);
    const to = hane ? write({ ...cur, hane: hane(cur.hane) }) : from;
    store.set(editLayout(latest, from, to, cur.hane, edit));
  };
  const patchSlot = (key: string, patch: Partial<Slot>) => (all: Slot[]) =>
    all.map((s) => (s.key === key ? { ...s, ...patch } : s));
  // A male already chosen in another slot: the edited slot stays empty.
  const takenElsewhere = (all: Slot[], key: string, n: string | null) =>
    n != null &&
    all.some((s) => s.key !== key && !s.unregistered && s.number === n);

  const changeMale = (key: string, patch: Partial<AnimalInput>) => {
    if ("picked" in patch) {
      const next = patch.picked?.number ?? null;
      remember(patch.picked);
      editMale(key, (slot) => ({
        hane: (hane) => replaceMale(hane, slot.number, next),
        edit: (all) =>
          patchSlot(key, {
            number: takenElsewhere(all, key, next) ? null : next,
          })(all),
      }));
    } else if (patch.unregistered) {
      editMale(key, (slot) => ({
        hane: (hane) => replaceMale(hane, slot.number, null),
        edit: patchSlot(key, { unregistered: true }),
      }));
    } else if (patch.unregistered === false) {
      editMale(key, (slot) => ({
        hane: (hane) => replaceMale(hane, null, slot.number),
        edit: (all) =>
          patchSlot(key, {
            unregistered: false,
            number: takenElsewhere(all, key, slot.number) ? null : slot.number,
          })(all),
      }));
    } else {
      editMale(key, () => ({ edit: patchSlot(key, patch) }));
    }
  };

  const removeMale = (key: string) =>
    editMale(key, (slot) => ({
      hane: slot.unregistered
        ? undefined
        : (hane) => replaceMale(hane, slot.number, null),
      edit: (all) => all.filter((s) => s.key !== key),
    }));

  const addMale = () => {
    const { query: from, selection: cur } = current();
    store.set(
      editLayout(store.get(), from, from, cur.hane, (all) => [
        ...all,
        emptySlot(newKey()),
      ]),
    );
  };

  // The keyed parent remounts this form for the new genebank.
  const changeGenebank = (id: number) =>
    write({ genebank: id, hona: null, hane: [] });

  const request = buildTestbreedRequest(genebankId, female, males);
  // Never sent: the API would refuse it.
  const overLimit = tooManyMales(request);
  const requestKey = request && !overLimit ? JSON.stringify(request) : "";
  const debouncedKey = useDebounce(requestKey, 300);

  const [run, { isLoading }] = useTestbreedMutation();
  const [shown, setShown] = useState<{
    key: string;
    request: TestbreedRequest;
    data: TestbreedResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  // Every invocation gets an increasing id; only the newest may apply its
  // outcome (A -> B -> A: the first A must not overwrite the second one).
  const [sequence] = useState(createSequence);

  useEffect(() => {
    const id = sequence.next();
    // Nothing to calculate: the render guards on `requestKey`, so leftovers
    // in `shown`/`error` are never displayed.
    if (!debouncedKey) return;
    const req = JSON.parse(debouncedKey) as TestbreedRequest;
    setError(null);
    run(req)
      .unwrap()
      .then((data) => {
        if (sequence.isLatest(id))
          setShown({ key: debouncedKey, request: req, data });
      })
      .catch((err) => {
        if (!sequence.isLatest(id)) return;
        setShown(null);
        setError(describeError(err));
      });
  }, [debouncedKey, retry, run, sequence]);

  const settled = shown !== null && shown.key === requestKey;
  const busy = !!requestKey && !settled && !error;

  const parentLabel = (parents: {
    mother: string | null;
    father: string | null;
  }) =>
    [
      parents.mother && `mor ${parents.mother}`,
      parents.father && `far ${parents.father}`,
    ]
      .filter(Boolean)
      .join(", ");

  return (
    <div className={styles.container}>
      <div className={styles.layout}>
        <section
          className={`sb-card ${styles.form}`}
          aria-label="Välj djur"
          data-testid="provparning-form"
        >
          {genebanks.length > 1 && (
            <div>
              <label className="sb-label" htmlFor="provparning-genebank">
                Genbank
              </label>
              <select
                id="provparning-genebank"
                className="sb-input"
                value={genebankId ?? ""}
                onChange={(e) => changeGenebank(Number(e.target.value))}
              >
                {genebanks.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {genebankId != null && (
            <>
              <AnimalPicker
                key={female.key}
                sex="female"
                title="Hona"
                genebankId={genebankId}
                ownHerd={ownHerd}
                value={female}
                onChange={changeFemale}
                testId="picker-female"
              />
              {males.map((male, i) => (
                <AnimalPicker
                  key={male.key}
                  sex="male"
                  title={i === 0 ? "Hane" : `Hane ${i + 1}`}
                  genebankId={genebankId}
                  ownHerd={ownHerd}
                  value={male}
                  onChange={(patch) => changeMale(male.key, patch)}
                  onRemove={
                    males.length > 1 ? () => removeMale(male.key) : undefined
                  }
                  testId={`picker-male-${i + 1}`}
                />
              ))}
              {males.length < MAX_MALES && (
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  onClick={addMale}
                >
                  Lägg till en hane till
                </button>
              )}
            </>
          )}
        </section>

        <section
          className={styles.results}
          aria-live="polite"
          aria-busy={busy || isLoading}
          data-testid="provparning-results"
        >
          {overLimit && (
            <div
              className={`sb-card ${styles.errorBox}`}
              role="alert"
              data-testid="too-many-males"
            >
              <span>
                Högst {MAX_MALES} hanar åt gången — ta bort någon för att räkna.
              </span>
            </div>
          )}

          {!requestKey && !overLimit && (
            <p className={`sb-card ${styles.empty}`}>
              Välj en hona och minst en hane för att se vilken inavelsgrad en
              tänkt avkomma skulle få.
            </p>
          )}

          {requestKey && error && (
            <div className={`sb-card ${styles.errorBox}`} role="alert">
              <span>{error}</span>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                onClick={() => setRetry((n) => n + 1)}
              >
                Försök igen
              </button>
            </div>
          )}

          {requestKey && !error && !shown && (
            <div
              className={`sb-card ${styles.card} ${styles.skeleton}`}
              data-testid="provparning-skeleton"
            >
              <div className={`${styles.skelLine} ${styles.skelBig}`} />
              <div className={styles.skelLine} />
              <div className={styles.skelLine} />
            </div>
          )}

          {requestKey && !error && shown && (
            <div className={busy ? styles.resultsBusy : undefined}>
              <div className={styles.results}>
                <p className={styles.femaleLine} data-testid="female-summary">
                  Hona:{" "}
                  <AnimalName
                    number={shown.data.female.number}
                    name={shown.data.female.name}
                    fallback={`Oregistrerad hona (${parentLabel(
                      shown.request.female_parents ?? {
                        mother: null,
                        father: null,
                      },
                    )})`}
                  />
                  {shown.data.female.f != null &&
                    ` · F ${formatPercent(shown.data.female.f)}`}
                  {shown.data.female.mk != null &&
                    ` · MK ${formatPercent(shown.data.female.mk)}`}
                </p>

                {sortResults(shown.data.results).map(({ result, index }) => {
                  const payload = shown.request.males[index];
                  const fallback =
                    payload && "parents" in payload
                      ? `Oregistrerad hane (${parentLabel(payload.parents)})`
                      : "Hane";
                  return (
                    <ResultCard
                      key={`${index}-${result.male.number ?? "x"}`}
                      testId="result-card"
                      result={result}
                      thresholds={shown.data.thresholds}
                      femaleSummary={shown.data.female}
                      maleFallback={fallback}
                    />
                  );
                })}

                <p className={styles.thresholds}>
                  Bedömning efter avkomman F: bra upp till{" "}
                  {formatPercent(shown.data.thresholds.good_max, 0)}, utred
                  närmare upp till{" "}
                  {formatPercent(shown.data.thresholds.check_max, 0)}, över det
                  hög inavel. Det är ett stöd – andra faktorer kan tala för en
                  parning trots högre värde.
                </p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
