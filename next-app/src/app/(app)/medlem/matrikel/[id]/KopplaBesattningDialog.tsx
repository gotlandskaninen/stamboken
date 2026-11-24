"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Dialog } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { statusLabel } from "@/lib/membershipStatus";
import { readModeCookieClient } from "@/lib/mode";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";
import { linkMembershipHerd } from "../actions";
import type {
  HerdAccount,
  HerdCandidate,
  HerdLinkConfirmation,
  HerdLinkPreview,
} from "../types";

function membershipLabel(number: number | null) {
  return number === null ? "medlemskap utan nummer" : `medlemskap nr ${number}`;
}

function accountLabel(account: HerdAccount) {
  return account.username ?? `nr ${account.id}`;
}

function ownerEffect(access: NonNullable<HerdLinkPreview["new_access"]>) {
  if (access.already_manages) {
    return "Kontot får redan ändra, sälja och flytta kaniner genom sin roll. Som innehavare får kontot ge hushållet tillgång.";
  }
  if (access.already_edits) {
    return "Kontot får redan ändra kaniner och får nu också sälja och flytta kaniner och ge hushållet tillgång.";
  }
  return "Kontot får ändra, sälja och flytta kaniner och ge hushållet tillgång.";
}

function Preview({ preview }: { preview: HerdLinkPreview }) {
  const {
    herd,
    membership,
    new_access,
    inactive_main_account,
    new_readers,
    legacy_owners,
    grant_holders,
    contact_rows,
  } = preview;
  const gainsGrants = legacy_owners.find((u) => u.gains_household_grants);
  return (
    <div aria-live="polite">
      <h3 className="sb-h6">
        {herd.herd}
        {herd.herd_name && ` — ${herd.herd_name}`}
      </h3>
      <p>
        {herd.genebank_name} ·{" "}
        {herd.is_active ? "Aktiv besättning" : "Inaktiv besättning"}
      </p>
      <p>
        Kopplas till {membershipLabel(membership.member_number)} ·{" "}
        {statusLabel(membership.membership_status)}
      </p>
      <h3 className="sb-h6">Åtkomst som tillkommer</h3>
      {inactive_main_account && (
        <p>
          Huvudmedlemmens konto {accountLabel(inactive_main_account)} är
          inaktivt.
        </p>
      )}
      {membership.membership_status !== "active" ? (
        <p>Kopplingen ger åtkomst först när medlemskapet blir aktivt.</p>
      ) : (
        <>
          {new_access && (
            <p>
              Huvudmedlemmens konto {accountLabel(new_access)} blir
              besättningens innehavare. {ownerEffect(new_access)}
            </p>
          )}
          {gainsGrants && (
            <p>
              Huvudmedlemmens konto {accountLabel(gainsGrants)} kan nu ge
              hushållet tillgång till besättningen.
            </p>
          )}
          {new_readers.length > 0 && (
            <ul>
              {new_readers.map((u) => (
                <li key={u.id}>
                  {accountLabel(u)} får läsa matrikelns kontaktuppgifter för
                  besättningen.
                </li>
              ))}
            </ul>
          )}
          {!new_access && !gainsGrants && !new_readers.length && (
            <p>Inget konto får ny åtkomst.</p>
          )}
        </>
      )}
      <h3 className="sb-h6">Åtkomst som finns kvar</h3>
      {legacy_owners.length === 0 && grant_holders.length === 0 ? (
        <p>
          Inget konto har en gammal ägarroll eller ett aktivt skötartillstånd på
          besättningen.
        </p>
      ) : (
        <ul>
          {legacy_owners.map((u) => (
            <li key={`owner-${u.id}`}>
              {accountLabel(u)} · gammal ägarroll
              {!u.in_membership && " · saknar aktiv person i medlemskapet"}
            </li>
          ))}
          {grant_holders.map((u) => (
            <li key={`grant-${u.id}`}>
              {accountLabel(u)} · aktivt skötartillstånd
            </li>
          ))}
        </ul>
      )}
      <h3 className="sb-h6">Kontaktuppgifter</h3>
      {contact_rows ? (
        <ul>
          {contact_rows.map((row) => (
            <li key={row.field}>
              <strong>{row.label}</strong> · {row.effect}
            </li>
          ))}
        </ul>
      ) : (
        <p>Kontaktuppgifterna jämförs när medlemskapet blir aktivt.</p>
      )}
    </div>
  );
}

export function KopplaBesattningButton({
  membershipId,
}: {
  membershipId: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={() => setOpen(true)}
      >
        Koppla besättning
      </button>
      {open && (
        <KopplaBesattningDialog
          membershipId={membershipId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

export function KopplaBesattningDialog({
  membershipId,
  onClose,
}: {
  membershipId: number;
  onClose: () => void;
}) {
  const [banks, setBanks] = useState<{ id: number; name: string }[] | null>(
    null,
  );
  const [bank, setBank] = useState("");
  const [herds, setHerds] = useState<HerdCandidate[] | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<HerdCandidate | null>(null);
  const [confirmation, setConfirmation] = useState<
    (HerdLinkConfirmation & { changed: boolean }) | null
  >(null);
  const title = useRef<HTMLHeadingElement>(null);
  const [error, setError] = useState("");
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  useEffect(() => {
    if (confirmation) title.current?.focus();
  }, [confirmation]);

  useEffect(() => {
    const ctrl = new AbortController();
    const base =
      (readModeCookieClient() === "demo" &&
        process.env.NEXT_PUBLIC_API_TEST_URL) ||
      "/api";
    const path = bank
      ? `/v2/memberships/${membershipId}/herd-candidates?genebank_id=${bank}`
      : "/v2/genebanks/public";
    async function load() {
      try {
        const response = await fetch(base + path, {
          credentials: "include",
          cache: "no-store",
          signal: ctrl.signal,
        });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (ctrl.signal.aborted) return;
        if (bank) setHerds(data.herds);
        else setBanks(data.genebanks);
      } catch {
        if (!ctrl.signal.aborted)
          setError(
            bank
              ? "Kunde inte hämta besättningarna."
              : "Kunde inte hämta genbankerna.",
          );
      }
    }
    void load();
    return () => ctrl.abort();
  }, [membershipId, bank]);

  const chooseBank = (value: string) => {
    setBank(value);
    setHerds(null);
    setQuery("");
    setSelected(null);
    setError("");
  };

  const submit = () => {
    if (!selected) return;
    start(async () => {
      setError("");
      let result;
      try {
        result = await linkMembershipHerd(
          membershipId,
          selected.id,
          confirmation?.confirm_token,
        );
      } catch {
        setError("Kunde inte nå servern. Försök igen.");
        return;
      }
      if (result.ok) {
        showSnackbar("Besättning kopplad", "success");
        addNotification({
          title: "Besättning kopplad",
          message: `${confirmation?.preview.herd.herd ?? selected.herd} har kopplats till medlemskapet.`,
          type: "success",
        });
        onClose();
      } else if ("confirmRequired" in result) {
        setConfirmation({
          ...result.confirmRequired,
          changed: confirmation !== null,
        });
      } else {
        if (result.resetSelection) {
          chooseBank("");
          setConfirmation(null);
        }
        setError(result.error);
      }
    });
  };

  const filtered = herds?.filter((h) =>
    h.herd.toLowerCase().includes(query.trim().toLowerCase()),
  );
  return (
    <Dialog
      open
      onClose={pending ? undefined : onClose}
      fullWidth
      maxWidth="sm"
      aria-labelledby="herd-link-title"
    >
      <div className={styles.herdLinkBody}>
        <h2 className="sb-h5" id="herd-link-title" tabIndex={-1} ref={title}>
          Koppla besättning
        </h2>
        {error && (
          <p role="alert" className={ds["ad-field-error"]}>
            {error}
          </p>
        )}
        {confirmation ? (
          <>
            {confirmation.changed && (
              <p
                role="alert"
                className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}
              >
                Underlaget har ändrats. Granska den nya förhandsvisningen innan
                du kopplar.
              </p>
            )}
            <Preview preview={confirmation.preview} />
          </>
        ) : (
          <>
            <div>
              <label className="sb-label" htmlFor="herd-link-bank">
                Genbank
              </label>
              <select
                className="sb-input"
                id="herd-link-bank"
                value={bank}
                disabled={pending || !banks?.length}
                onChange={(e) => chooseBank(e.target.value)}
              >
                <option value="" disabled>
                  {banks?.length === 0
                    ? "Inga genbanker hittades"
                    : "Välj genbank"}
                </option>
                {banks?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>
            {bank && (
              <>
                <div>
                  <label className="sb-label" htmlFor="herd-link-filter">
                    Filtrera på besättningsnummer
                  </label>
                  <input
                    className="sb-input"
                    id="herd-link-filter"
                    value={query}
                    disabled={pending}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setSelected(null);
                    }}
                  />
                </div>
                {filtered?.length ? (
                  <div
                    role="radiogroup"
                    aria-label="Besättningar"
                    className={styles.herdChoices}
                  >
                    {filtered.map((h) => (
                      <label key={h.id}>
                        <input
                          type="radio"
                          name="herd"
                          checked={h.id === selected?.id}
                          disabled={
                            pending ||
                            h.link !== "ingen" ||
                            !!h.unavailable_reason
                          }
                          onChange={() => setSelected(h)}
                        />
                        <span>
                          {h.herd}
                          {h.herd_name && ` — ${h.herd_name}`}
                          {!h.is_active && " · Inaktiv"}
                          {h.unavailable_reason && ` · ${h.unavailable_reason}`}
                          {h.link === "annat" &&
                            ` · Kopplad till ${membershipLabel(h.member_number)}`}
                          {h.link === "detta" &&
                            " · Kopplad till detta medlemskap"}
                        </span>
                      </label>
                    ))}
                  </div>
                ) : (
                  !error && (
                    <p role="status">
                      {herds
                        ? "Inga besättningar hittades."
                        : "Hämtar besättningar…"}
                    </p>
                  )
                )}
              </>
            )}
          </>
        )}
        <div className={ds["ad-form-actions"]}>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={onClose}
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
            {confirmation ? "Koppla" : "Visa vad kopplingen ger"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
