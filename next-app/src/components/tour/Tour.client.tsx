"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Alert } from "@mui/material";
import type { Driver } from "driver.js";
import "driver.js/dist/driver.css";
import "./tour.css";
import { useOptionalUser } from "@/lib/user-context";
import { answerOffer, shouldOffer, stepsFor } from "./tour";

/** Starts the tour; null outside a TourProvider (then no button is shown). */
export const TourContext = React.createContext<(() => void) | null>(null);

export const useStartTour = () => React.useContext(TourContext);

const noSubscription = () => () => {};

const escapeHtml = (s: string) =>
  s.replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!,
  );

/**
 * The tour (stamboken #229): driver.js points at the parts of the current
 * page, one step at a time. It starts only when the user asks for it.
 */
export function TourProvider({ children }: { children: React.ReactNode }) {
  const user = useOptionalUser();
  const { t } = useTranslation();
  const pathname = usePathname();
  const tour = React.useRef<Driver | null>(null);

  // A new page has other parts: end the tour rather than point at nothing.
  const end = () => {
    const running = tour.current;
    tour.current = null; // ended by us: leave focus where it is
    running?.destroy();
  };
  React.useEffect(() => end, [pathname]);

  const start = React.useCallback(async () => {
    if (!user) return;
    const { driver } = await import("driver.js");
    end();
    const steps = stepsFor(user);
    if (steps.length === 0) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // driver.js returns focus to the last focused element, which after Nästa
    // is a button in the closed popover. Return it to where the tour started,
    // or to the menu when that is gone (the offer hides itself).
    const opener = document.activeElement;
    const running = driver({
      steps: steps.map((step) => ({
        element: step.element,
        popover: {
          title: t(`tour.steps.${step.id}.title`),
          // driver.js sets this as HTML: every text is escaped.
          description:
            `<p>${escapeHtml(t(`tour.steps.${step.text?.(user) ?? `${step.id}.text`}`))}</p>` +
            `<p><a href="${escapeHtml(step.href)}">${escapeHtml(t("tour.more"))}</a></p>`,
        },
      })),
      animate: !still,
      smoothScroll: !still,
      showProgress: true,
      // Kept as driver.js placeholders, which it fills in per step.
      progressText: t("tour.progress", {
        current: "{{current}}",
        total: "{{total}}",
      }),
      nextBtnText: t("tour.next"),
      prevBtnText: t("tour.prev"),
      doneBtnText: t("tour.done"),
      closeBtnLabel: t("tour.close"),
      // A click on the highlighted link would leave the page mid-tour.
      disableActiveInteraction: true,
      popoverClass: "sb-tour",
      // Every close by the user (Klar, the cross, Esc, the overlay) comes here
      // first; driver.js then leaves the teardown to us. Its own onDestroyed
      // is skipped when Esc comes between two steps.
      onDestroyStarted: () => {
        running.destroy();
        if (tour.current !== running) return;
        tour.current = null;
        const back =
          opener instanceof HTMLElement && opener.isConnected
            ? opener
            : document.querySelector<HTMLElement>('[data-tour="user-menu"]');
        // After driver.js's own focus call, which can land on the old popover.
        requestAnimationFrame(() => back?.focus());
      },
    });
    tour.current = running;
    running.drive();
  }, [user, t]);

  return <TourContext.Provider value={start}>{children}</TourContext.Provider>;
}

/**
 * The offer after the first login, on Min besättning only, where a new user
 * lands. It stays until the user answers, and never starts the tour itself.
 */
export function TourOffer() {
  const user = useOptionalUser();
  const start = useStartTour();
  const pathname = usePathname();
  const { t } = useTranslation();
  const [answered, setAnswered] = React.useState(false);
  // localStorage on the client, "no" on the server, so hydration matches.
  const unanswered = React.useSyncExternalStore(
    noSubscription,
    () => !!user && shouldOffer(user.id),
    () => false,
  );

  if (answered || !unanswered || !user || !start) return null;
  if (!pathname.startsWith("/stamboken/min-besattning")) return null;

  const answer = (yes: boolean) => {
    answerOffer(user.id);
    setAnswered(true);
    if (yes) start();
  };

  return (
    <Alert
      severity="info"
      role="region"
      aria-label={t("tour.offerLabel")}
      sx={{ borderRadius: 0, alignItems: "center", flexWrap: "wrap" }}
      action={
        <span className="sb-tour-offer-actions">
          <button
            type="button"
            className="sb-btn sb-btn-sm"
            onClick={() => answer(true)}
          >
            {t("tour.start")}
          </button>
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={() => answer(false)}
          >
            {t("tour.noThanks")}
          </button>
        </span>
      }
    >
      {t("tour.offer")}
    </Alert>
  );
}
