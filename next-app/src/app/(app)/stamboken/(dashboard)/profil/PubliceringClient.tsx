"use client";

import { useState, useTransition } from "react";
import {
  PublicationFields,
  toConsent,
  type Publication,
} from "@/components/member/PublicationFields";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { CONSENT_TEXT_VERSION, UTOM_ALL } from "../arsrapport/lib";
import { updateConsent } from "./actions";
import styles from "./profil.module.css";
import type { Consent } from "./types";

export type { Consent };

const CONSENT_KEYS = ["name", "phone", "email", "address"] as const;

// The stored keys as the question's answer (spec 5.11): never answered is no
// answer, and `name` is the Ja. Nej is every key false; Ja is `name` and every
// key not left out.
const toAnswer = (c: Consent, answered: boolean): Publication | null =>
  answered
    ? { ja: c.name, utom: c.name ? UTOM_ALL.filter((k) => !c[k]) : [] }
    : null;

export function PubliceringClient({
  readOnly = false,
  initial,
  answered,
}: {
  readOnly?: boolean;
  initial: Consent;
  // false = the member has never answered the Koharen question (stored `{}`,
  // not in the Koharen list) — see Me.consent_answered.
  answered: boolean;
}) {
  const [answer, setAnswer] = useState(() => toAnswer(initial, answered));
  // What the server last acknowledged for THIS tab — the base the partial
  // update is diffed against. `initial` is refreshed by revalidatePath after
  // every Server Action on the page while React keeps `answer` across that
  // refresh; diffing against the refreshed prop would turn a key another
  // tab withdrew meanwhile into a "dirty" key here and send the stale value
  // back up. Same for `answered`: once this tab has answered,
  // its next save must be partial even before the props catch up.
  const [baseline, setBaseline] = useState(initial);
  const [hasAnswered, setHasAnswered] = useState(answered);
  // A Ja or Nej chosen since the last save: the answer is new and goes whole.
  const [chose, setChose] = useState(false);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  const save = (chosen: Publication) =>
    start(async () => {
      // A tick within a standing Ja sends only the keys that moved, so a
      // second tab's withdrawal cannot be replayed from this tab's stale read.
      // A Ja or Nej, and the first answer, is whole: all four keys go up, so
      // nothing another tab allowed stays in an answer the member did not give.
      const consent = toConsent(chosen);
      const partial = hasAnswered && baseline.name && chosen.ja && !chose;
      const changed = CONSENT_KEYS.filter((k) => consent[k] !== baseline[k]);
      if (partial && changed.length === 0) {
        showSnackbar("Publiceringsval sparade", "success");
        return;
      }
      const patch: Partial<Consent> = partial
        ? Object.fromEntries(changed.map((k) => [k, consent[k]]))
        : consent;
      // The version of the text this page shows: the server refuses another.
      const result = await updateConsent({
        ...patch,
        text_version: CONSENT_TEXT_VERSION,
      });
      if (result.ok) {
        // The backend merged our keys onto the row it locked — its answer is
        // the truth for every key, including one another tab changed.
        setAnswer(toAnswer(result.consent, result.answered));
        setBaseline(result.consent);
        setHasAnswered(result.answered);
        setChose(false);
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
        <PublicationFields
          value={answer}
          onChange={(next) => {
            if (next?.ja !== answer?.ja) setChose(true); // a radio, not a tick
            setAnswer(next);
          }}
          disabled={readOnly}
        />
        <p className={styles.note}>
          Inget av detta visas på webben — besättningens synlighet på webben
          ställer du in under Min besättning.
        </p>
        <div className={styles.actions}>
          {/* No answer stays no answer: nothing to save until Ja or Nej is chosen (spec 5.11). */}
          <button
            type="button"
            className="sb-btn"
            disabled={readOnly || pending || answer === null}
            onClick={() => answer && save(answer)}
          >
            {pending ? "Sparar..." : "Spara"}
          </button>
        </div>
      </div>
    </section>
  );
}
