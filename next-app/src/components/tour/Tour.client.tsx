"use client";

import React from "react";
import { flushSync } from "react-dom";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Alert } from "@mui/material";
import type { Driver } from "driver.js";
import "driver.js/dist/driver.css";
import "./tour.css";
import { useOptionalUser } from "@/lib/user-context";
import { useSnackbar } from "@/components/SnackbarProvider";
import { answerOffer, shouldOffer, stepsFor } from "./tour";

interface Tour {
  /** Starts the tour on the current page. */
  start: () => void;
  /** The first-login offer is still unanswered and nothing hides it. */
  offerOpen: boolean;
  /** Nej tack: saved at once. */
  decline: () => void;
  /** Hides the offer while another Visa runt button is on the page. */
  hideOffer: (hidden: boolean) => void;
}

/** null outside a TourProvider; then no Visa runt button is shown. */
export const TourContext = React.createContext<Tour | null>(null);

export const useStartTour = () => React.useContext(TourContext)?.start ?? null;

/** While the calling component shows its own Visa runt, the offer hides. */
export function useHideTourOffer(hidden: boolean) {
  const hideOffer = React.useContext(TourContext)?.hideOffer;
  React.useEffect(() => {
    if (!hideOffer || !hidden) return;
    hideOffer(true);
    return () => hideOffer(false);
  }, [hideOffer, hidden]);
}

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
  const { showSnackbar } = useSnackbar();
  const pathname = usePathname();
  const tour = React.useRef<Driver | null>(null);
  // Bumped by every end: a start still loading driver.js sees it and stops.
  const generation = React.useRef(0);
  const [answered, setAnswered] = React.useState(false);
  const [offerHidden, setOfferHidden] = React.useState(false);
  // localStorage on the client, "no" on the server, so hydration matches.
  const unanswered = React.useSyncExternalStore(
    noSubscription,
    () => !!user && shouldOffer(user.id),
    () => false,
  );

  const end = React.useCallback(() => {
    generation.current++;
    const running = tour.current;
    tour.current = null; // ended by us: leave focus where it is
    running?.destroy();
  }, []);
  // A new page has other parts: end the tour rather than point at nothing.
  React.useEffect(() => end, [pathname, end]);

  const start = React.useCallback(async () => {
    if (!user) return;
    end();
    const mine = generation.current;
    // driver.js returns focus to the last focused element, which after Nästa
    // is a button in the closed popover. Return it to where the tour started,
    // read before the await below unmounts the offer, or to the menu when
    // that button is gone.
    const opener = document.activeElement;
    let driver: typeof import("driver.js").driver;
    try {
      ({ driver } = await import("driver.js"));
    } catch {
      if (mine === generation.current) showSnackbar(t("tour.failed"), "error");
      return;
    }
    // The page changed, or another start came, while driver.js loaded.
    if (mine !== generation.current) return;
    const steps = stepsFor(user);
    if (steps.length === 0) {
      showSnackbar(t("tour.failed"), "error");
      return;
    }
    // The tour will run: it now counts as the answer to the offer. The offer
    // leaves the page before driver.js measures it, so nothing shifts after.
    answerOffer(user.id);
    flushSync(() => setAnswered(true));
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const running = driver({
      steps: steps.map((step) => ({
        element: step.element,
        popover: {
          title: t(`tour.steps.${step.id}.title`),
          // driver.js sets this as HTML: every text is escaped.
          description:
            `<p>${escapeHtml(t(`tour.steps.${step.textKey}`))}</p>` +
            (step.href
              ? `<p><a href="${escapeHtml(step.href)}">${escapeHtml(t("tour.more"))}</a></p>`
              : ""),
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
          opener instanceof HTMLElement &&
          opener.isConnected &&
          opener !== document.body
            ? opener
            : document.querySelector<HTMLElement>('[data-tour="user-menu"]');
        // After driver.js's own focus call, which can land on the old popover.
        requestAnimationFrame(() => back?.focus());
      },
    });
    tour.current = running;
    running.drive();
  }, [user, t, end, showSnackbar]);

  const value = React.useMemo<Tour>(
    () => ({
      start,
      offerOpen: !!user && unanswered && !answered && !offerHidden,
      decline: () => {
        if (user) answerOffer(user.id);
        setAnswered(true);
      },
      hideOffer: setOfferHidden,
    }),
    [start, user, unanswered, answered, offerHidden],
  );

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
}

/**
 * The offer after the first login, on Min besättning only, where a new user
 * lands. It stays until the user answers, and never starts the tour itself.
 */
export function TourOffer() {
  const tour = React.useContext(TourContext);
  const pathname = usePathname();
  const { t } = useTranslation();

  if (!tour?.offerOpen) return null;
  if (!pathname.startsWith("/stamboken/min-besattning")) return null;

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
            onClick={tour.start}
          >
            {t("tour.start")}
          </button>
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={tour.decline}
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
