"use client";

import { useState, useTransition } from "react";
import { FormControlLabel, Switch } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { updateConsent } from "./actions";
import styles from "./profil.module.css";
import type { Consent } from "./types";

export type { Consent };

const CONSENT_KEYS = ["name", "phone", "email", "address"] as const;

const CONSENT_LABELS: Record<keyof Consent, string> = {
  name: "Namn",
  phone: "Telefon",
  email: "E-post",
  address: "Adress",
};

export function PubliceringClient({
  readOnly = false,
  initial,
  answered,
}: {
  readOnly?: boolean;
  initial: Consent;
  // false = the member has never answered the Koharen question (stored `{}`,
  // "ej angivet" in the export) — see Me.consent_answered.
  answered: boolean;
}) {
  const [consent, setConsent] = useState(initial);
  // What the server last acknowledged for THIS tab — the base the partial
  // update is diffed against. `initial` is refreshed by revalidatePath after
  // every Server Action on the page while React keeps `consent` across that
  // refresh; diffing against the refreshed prop would turn a switch another
  // tab withdrew meanwhile into a "dirty" key here and send the stale value
  // back up. Same for `answered`: once this tab has answered,
  // its next save must be partial even before the props catch up.
  const [baseline, setBaseline] = useState(initial);
  const [hasAnswered, setHasAnswered] = useState(answered);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  const save = () =>
    start(async () => {
      // Partial update: send only the switches that actually moved,
      // so a second tab editing another switch cannot have its value replayed
      // from this tab's stale read — that is how a withdrawn consent came back.
      // The first answer is the exception: all four keys go up so an all-off
      // answer is recorded as "angivet" instead of staying unset.
      const changed = CONSENT_KEYS.filter((k) => consent[k] !== baseline[k]);
      if (hasAnswered && changed.length === 0) {
        showSnackbar("Publiceringsval sparade", "success");
        return;
      }
      const patch: Partial<Consent> = hasAnswered
        ? Object.fromEntries(changed.map((k) => [k, consent[k]]))
        : consent;
      const result = await updateConsent(patch);
      if (result.ok) {
        // The backend merged our keys onto the row it locked — its answer is
        // the truth for every switch, including one another tab changed.
        setConsent(result.consent);
        setBaseline(result.consent);
        setHasAnswered(result.answered);
        showSnackbar("Publiceringsval sparade", "success");
      } else {
        showSnackbar(result.error, "error");
        addNotification({
          title: "Kunde inte spara publiceringsvalen",
          message: result.error,
          type: "error",
        });
      }
    });

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Publicering i Koharen</h3>
      </div>
      <div className={styles.cardBody}>
        {readOnly && (
          <div className={`${styles.banner} ${styles.bannerInfo}`}>
            Endast huvudmedlemmen kan ändra medlemskapets uppgifter.
          </div>
        )}
        <p className={styles.note}>
          Medlemsmatrikeln trycks i Koharen. Välj vilka uppgifter som får finnas
          med. Inget av detta visas på webben — besättningens synlighet på
          webben ställer du in under Min besättning.
        </p>
        {CONSENT_KEYS.map((k) => (
          <FormControlLabel
            key={k}
            className={styles.switchRow}
            labelPlacement="start"
            label={CONSENT_LABELS[k]}
            control={
              <Switch
                checked={consent[k]}
                disabled={readOnly}
                onChange={(e) =>
                  setConsent({ ...consent, [k]: e.target.checked })
                }
              />
            }
          />
        ))}
        <div className={styles.actions}>
          <button
            type="button"
            className="sb-btn"
            disabled={readOnly || pending}
            onClick={save}
          >
            {pending ? "Sparar..." : "Spara"}
          </button>
        </div>
      </div>
    </section>
  );
}
