"use client";

import React from "react";
import CheckRounded from "@mui/icons-material/CheckRounded";
import type { Individual } from "@/redux/api/apiSlice";
import { MANUAL_PATH } from "@/lib/constants";
import { readModeCookieClient } from "@/lib/mode";
import { useUser } from "@/lib/user-context";
import {
  MbCard,
  rabbitStatus,
  type BreedingRecord,
  type TabValue,
} from "./min-besattning-ui";
import styles from "./min-besattning.module.css";

export interface OnboardingStep {
  title: string;
  text: string;
  done: boolean;
  manual: string;
  /** Link text into the manual, distinct per step for screen readers. */
  more: string;
}

// A new herd cannot register its own first rabbit: the add-rabbit dialog needs
// a mother already in the herd. The start animals arrive when the seller sells
// them to the herd, so that is step one.
export function onboardingSteps(
  individuals: Individual[],
  breedings: BreedingRecord[],
): OnboardingStep[] {
  // Living, uncastrated breeding stock. Not "Aktiv": that needs a life sign
  // within 13 months, which a herd that has not bred may lack.
  const stock = individuals.filter(
    (i) => rabbitStatus(i) !== "Död" && !i.castration_date,
  );
  return [
    {
      title: "Ta emot dina startdjur",
      text: "När du har köpt dina startdjur säljer uppfödaren dem till din besättning i Stamboken. De syns sedan under Kaniner. Du behöver minst en hane och en hona.",
      done:
        stock.some((i) => i.sex === "male") &&
        stock.some((i) => i.sex === "female"),
      manual: "#sälja-eller-flytta-en-kanin",
      more: "Så säljer uppfödaren",
    },
    {
      title: "Ladda upp ett foto",
      text: "Öppna en kanin under Kaniner och ladda upp ett foto, så känner andra igen den.",
      done: individuals.some((i) => i.has_photo),
      manual: "#ladda-upp-ett-foto",
      more: "Så laddar du upp ett foto",
    },
    {
      title: "Registrera din första parning",
      text: "När du parar dina djur registrerar du parningen. Stamboken räknar då ut när ungarna väntas.",
      done: breedings.length > 0,
      manual: "#registrera-en-parning",
      more: "Så registrerar du en parning",
    },
  ];
}

/**
 * Getting-started steps for a herd that has not bred yet (issue #41). Whether
 * a step is done comes from the herd's own data, so it holds across browsers
 * and logins; only "Stäng" is remembered per browser.
 */
export default function OnboardingChecklist({
  herd,
  breedings,
  herdNumber,
  onGoTab,
  onNewMating,
}: {
  herd: { is_active?: boolean; individuals?: Individual[] } | null;
  breedings: BreedingRecord[] | null;
  herdNumber: string;
  onGoTab: (tab: TabValue) => void;
  onNewMating: () => void;
}) {
  const user = useUser();
  // Per mode too: Stäng in the test environment must not hide the list in
  // the real stamboken (same origin, the mode is a cookie).
  const key = `sb-onboarding-dismissed-${readModeCookieClient()}-${herdNumber}`;
  // Read per render, not once: the herd switcher changes herdNumber without
  // remounting. Min besättning renders tabs only after hydration, so reading
  // localStorage here cannot cause a markup mismatch.
  const [closedKey, setClosedKey] = React.useState<string | null>(null);
  let dismissed = closedKey === key;
  try {
    dismissed ||= localStorage.getItem(key) === "1";
  } catch {
    // unavailable storage: only this visit's Stäng counts
  }

  // Only the owner gets "your start animals"; a herd that has bred is not
  // new; a failed fetch shows nothing.
  if (!user?.is_owner?.includes(herdNumber)) return null;
  if (dismissed || !herd?.is_active || breedings === null) return null;
  if (breedings.length > 0) return null;

  const individuals = herd.individuals ?? [];
  const steps = onboardingSteps(individuals, breedings);
  // The mating form needs a doe in the herd; the buck may be borrowed.
  const hasDoe = individuals.some(
    (i) => i.sex === "female" && rabbitStatus(i) !== "Död",
  );
  const actions: Array<React.ReactNode> = [
    null,
    individuals.length > 0 && (
      <button
        key="kaniner"
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={() => onGoTab("individuals")}
      >
        Till Kaniner
      </button>
    ),
    hasDoe && (
      <button
        key="parning"
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={onNewMating}
      >
        Ny parning
      </button>
    ),
  ];

  const dismiss = () => {
    try {
      localStorage.setItem(key, "1");
    } catch {
      // unavailable storage: closed for this visit only
    }
    setClosedKey(key);
  };

  return (
    <div className={styles["mb-onboarding"]}>
      <MbCard
        title="Kom igång med din besättning"
        action={
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            aria-label="Stäng Kom igång med din besättning"
            onClick={dismiss}
          >
            Stäng
          </button>
        }
      >
        <ol
          className={styles["mb-onboarding-steps"]}
          // list-style: none drops list semantics in Safari/VoiceOver.
          role="list"
        >
          {steps.map((step, i) => (
            <li key={step.title} data-done={step.done}>
              <span className={styles["mb-onboarding-num"]} aria-hidden>
                {step.done ? <CheckRounded fontSize="small" /> : i + 1}
              </span>
              <div>
                <h3 className="sb-h6">
                  {step.title}
                  {step.done && (
                    <span className="sb-badge sb-badge-skog">Klart</span>
                  )}
                </h3>
                <p>{step.text}</p>
                <div className={styles["mb-onboarding-links"]}>
                  {!step.done && actions[i]}
                  <a href={MANUAL_PATH + step.manual}>{step.more}</a>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </MbCard>
    </div>
  );
}
