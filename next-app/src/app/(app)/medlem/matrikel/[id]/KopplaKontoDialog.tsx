"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Dialog } from "@mui/material";
import { useDebounce } from "@/hooks/useDebounce";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { readModeCookieClient } from "@/lib/mode";
import { linkPersonUser } from "../actions";
import type { Person } from "../types";
import { ROLE_LABELS } from "../types";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";

type UserHit = { id: number; username: string | null; email: string };
type Conveys = { id: number; herd: string; herd_name: string | null }[];

function searchBase(): string {
  const test = process.env.NEXT_PUBLIC_API_TEST_URL;
  return readModeCookieClient() === "demo" && test ? test : "/api";
}

export function KopplaKontoDialog({
  open,
  person,
  membershipId,
  membershipNumber,
  onClose,
}: {
  open: boolean;
  person: Person | null;
  membershipId: number;
  membershipNumber: number | null;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const debounced = useDebounce(q, 300);
  const [hits, setHits] = useState<UserHit[]>([]);
  const [selected, setSelected] = useState<UserHit | null>(null);
  const [conveys, setConveys] = useState<Conveys | null>(null);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  // Monotonic request id. The effect's abort only fires once the DEBOUNCED
  // value changes, so a slow response for an older query could otherwise land
  // after the admin typed on (or closed the dialog) and its hits be selected
  // and linked. Every keystroke and every close bumps the id;
  // a response only counts if nothing invalidated it since it was sent.
  const searchReq = useRef(0);
  const invalidateSearch = () => {
    searchReq.current += 1;
  };

  // Fetch-only: `hits` is cleared where the query changes (onChange/reset),
  // never synchronously from here.
  useEffect(() => {
    const query = debounced.trim();
    // Only when the live input still says what the debounced value says:
    // after Avbryt (reset → q "") `debounced` lingers for 300 ms, and a
    // close → immediate reopen would otherwise re-run the OLD query with a
    // fresh id and list its hits under an empty field. Having
    // `q` in the deps also aborts an in-flight request on the keystroke
    // itself, not 300 ms later.
    if (!open || query.length < 2 || q.trim() !== query) return;
    const ctrl = new AbortController();
    const reqId = ++searchReq.current;
    fetch(`${searchBase()}/v2/users/search?q=${encodeURIComponent(query)}`, {
      credentials: "include",
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : { users: [] }))
      .then((b: { users: UserHit[] }) => {
        if (reqId === searchReq.current) setHits(b.users ?? []);
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, [debounced, q, open]);

  const select = (u: UserHit) => {
    setSelected(u);
    setConveys(null);
  };

  const reset = () => {
    invalidateSearch();
    setQ("");
    setHits([]);
    setSelected(null);
    setConveys(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const submit = () => {
    if (!person || !selected) return;
    start(async () => {
      const result = await linkPersonUser(
        membershipId,
        person.id,
        selected.id,
        conveys ? conveys.map((h) => h.id) : undefined,
      );
      if (result.ok) {
        showSnackbar("Konto kopplat", "success");
        addNotification({
          title: "Konto kopplat",
          message: `${selected.username ?? selected.email} är nu kopplat till ${person.first_name} ${person.last_name}.`,
          type: "success",
        });
        close();
      } else if ("confirmRequired" in result) {
        const herds = result.confirmRequired.conveysHerds;
        if (herds.length === 0) {
          // Nothing to confirm: re-sending [] would be refused again, so the
          // banner would be a silent dead end. Surface it instead.
          const message = "Kunde inte koppla kontot — ladda om sidan";
          showSnackbar(message, "error");
          addNotification({
            title: "Kunde inte koppla kontot",
            message,
            type: "error",
          });
          return;
        }
        setConveys(herds); // first call, or the delta changed — show/refresh the warning
      } else {
        showSnackbar(result.error, "error");
        addNotification({
          title: "Kunde inte koppla kontot",
          message: result.error,
          type: "error",
        });
      }
    });
  };

  const herdList = (conveys ?? [])
    .map((h) => (h.herd_name ? `${h.herd} — ${h.herd_name}` : h.herd))
    .join(", ");

  return (
    <Dialog
      open={open}
      onClose={pending ? undefined : close}
      fullWidth
      maxWidth="sm"
      aria-labelledby="koppla-title"
    >
      <div className={ds["ad-card-body"]} style={{ paddingTop: 20 }}>
        <h2 id="koppla-title" className="sb-h5" style={{ margin: 0 }}>
          Koppla användarkonto
        </h2>
        {person && (
          <p className={ds["ad-note"]}>
            {person.first_name} {person.last_name} ·{" "}
            {ROLE_LABELS[person.role] ?? person.role} i medlemskap nr{" "}
            {membershipNumber ?? "–"}
          </p>
        )}
        <label className="sb-label" htmlFor="koppla-q">
          Sök användare
        </label>
        <input
          id="koppla-q"
          className="sb-input"
          role="combobox"
          aria-controls="koppla-hits"
          aria-expanded={hits.length > 0}
          aria-autocomplete="list"
          value={q}
          onChange={(e) => {
            invalidateSearch();
            setQ(e.target.value);
            setHits([]);
            setSelected(null);
            setConveys(null);
          }}
          autoFocus
        />
        <p className={ds["ad-field-hint"]}>Matchar användarnamn och e-post.</p>
        <ul
          id="koppla-hits"
          className={styles.searchList}
          role="listbox"
          aria-label="Sökträffar"
        >
          {hits.map((u) => (
            <li
              key={u.id}
              role="option"
              tabIndex={0}
              aria-selected={selected?.id === u.id}
              className={`${styles.searchRow} ${selected?.id === u.id ? styles.searchRowActive : ""}`}
              onClick={() => select(u)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault(); // Space would scroll the dialog instead
                  select(u);
                }
              }}
            >
              <span className={styles.mono}>{u.username ?? "—"}</span>
              <span className="sb-meta">{u.email}</span>
            </li>
          ))}
        </ul>
        {conveys && conveys.length > 0 && selected && (
          <div
            className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}
            role="status"
          >
            <strong>Kontot får ägaråtkomst till {herdList}.</strong>{" "}
            {selected.username ?? selected.email} har i dag ingen egen
            ägarbehörighet på besättningen. Kopplingen loggas i matrikelloggen.
          </div>
        )}
        <div
          className={ds["ad-form-actions"]}
          style={{ justifyContent: "flex-end" }}
        >
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={close}
            disabled={pending}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            onClick={submit}
            disabled={pending || !selected}
          >
            {pending ? "Kopplar…" : "Koppla konto"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
