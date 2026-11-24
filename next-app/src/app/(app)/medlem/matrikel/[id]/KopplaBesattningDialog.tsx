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
  HerdCandidate,
  HerdLinkConfirmation,
  HerdLinkPreview,
} from "../types";

function membershipLabel(number: number | null) {
  return number === null ? "medlemskap utan nummer" : `medlemskap nr ${number}`;
}

function Preview({ preview }: { preview: HerdLinkPreview }) {
  const { herd, membership, new_access, legacy_owners, contact_rows } = preview;
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
      <p>
        {membership.membership_status !== "active"
          ? "Kopplingen ger åtkomst först när medlemskapet blir aktivt."
          : new_access
            ? `Huvudmedlemmens konto ${new_access.username ?? `nr ${new_access.id}`} får ändra besättningen.`
            : "Inget konto får ny åtkomst."}
      </p>
      <h3 className="sb-h6">Åtkomst som finns kvar</h3>
      {legacy_owners.length === 0 ? (
        <p>Inget konto har en gammal ägarroll på besättningen.</p>
      ) : (
        <ul>
          {legacy_owners.map((u) => (
            <li key={u.id}>
              {u.username ?? `Konto nr ${u.id}`} · gammal ägarroll
              {!u.in_membership && " · saknar aktiv person i medlemskapet"}
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
      const result = await linkMembershipHerd(
        membershipId,
        selected.id,
        confirmation?.confirm_token,
      );
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
        chooseBank("");
        setError(result.error);
        setConfirmation(null);
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
                          disabled={pending || h.link !== "ingen"}
                          onChange={() => setSelected(h)}
                        />
                        <span>
                          {h.herd}
                          {h.herd_name && ` — ${h.herd_name}`}
                          {!h.is_active && " · Inaktiv"}
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
