"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useTransition,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { undoAssignment } from "./actions";
import styles from "./inkorg.module.css";

type Location = "item" | "herd";
type Notice = {
  location: Location;
  message: string;
  token?: string | null;
  error?: string;
};
const QueueUndo = createContext<{
  offerUndo: (
    token: string | null,
    message: string,
    location?: Location,
  ) => void;
  notice: Notice | null;
  setPaused: (paused: boolean) => void;
  undo: (restoreFocus: () => void) => void;
  pending: boolean;
  revision: number;
} | null>(null);

export function useQueueUndo() {
  const context = useContext(QueueUndo);
  if (!context) throw new Error("QueueUndoProvider saknas.");
  return context;
}

// The inbox layout stays mounted when a taken item opens in the registration view.
export function QueueUndoProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [revision, setRevision] = useState(0);
  const [paused, setPaused] = useState(false);
  const [pending, start] = useTransition();
  useEffect(() => {
    if (!notice || paused || pending) return;
    const timer = window.setTimeout(() => setNotice(null), 20_000);
    return () => window.clearTimeout(timer);
  }, [notice, paused, pending]);

  const offerUndo = (
    token: string | null,
    message: string,
    location: Location = "item",
  ) => {
    setRevision((r) => r + 1);
    setNotice({ token, message, location });
  };

  const undo = (restoreFocus: () => void) => {
    if (!notice?.token || pending) return;
    const token = notice.token;
    start(async () => {
      const res = await undoAssignment(token);
      setRevision((r) => r + 1);
      const retryable =
        !res.ok &&
        (res.problem.status >= 500 ||
          (res.problem.status === 409 &&
            res.problem.detail.startsWith("Utskicket pågår")));
      if (!retryable) restoreFocus();
      setNotice((current) => {
        if (current !== notice) return current;
        if (res.ok)
          return {
            location: notice.location,
            message: [t("queueAssignment.undone"), res.data.warning]
              .filter(Boolean)
              .join(" "),
          };
        return {
          ...notice,
          error: res.problem.detail,
          token: retryable ? token : null,
        };
      });
    });
  };

  return (
    <QueueUndo.Provider
      value={{ offerUndo, revision, notice, setPaused, undo, pending }}
    >
      {children}
    </QueueUndo.Provider>
  );
}

export function focusCaseHeading() {
  const heading =
    document.getElementById("case-subject") ??
    document.querySelector<HTMLElement>("main h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus();
  }
}

export function QueueUndoStatus({
  location = "item",
}: {
  location?: Location;
}) {
  const { t } = useTranslation();
  const { notice, setPaused, pending, undo } = useQueueUndo();
  const shown = notice?.location === location ? notice : null;
  const bar = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const pause = !!shown && (hovered || focused);
  useEffect(() => {
    if (!pause) return;
    setPaused(true);
    return () => setPaused(false);
  }, [pause, setPaused]);

  function restoreFocus() {
    if (!bar.current?.contains(document.activeElement)) return;
    if (location === "herd")
      bar.current.closest("details")?.querySelector("summary")?.focus();
    else focusCaseHeading();
  }

  return (
    <div
      ref={bar}
      role="status"
      className={shown ? styles.undoBar : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) =>
        setFocused(event.currentTarget.contains(event.relatedTarget))
      }
    >
      {shown && (
        <>
          <span>{shown.message}</span>
          {shown.error && <span role="alert">{shown.error}</span>}
          {shown.token && (
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              aria-disabled={pending}
              onClick={() => undo(restoreFocus)}
            >
              {t("queueAssignment.undo")}
            </button>
          )}
        </>
      )}
    </div>
  );
}
