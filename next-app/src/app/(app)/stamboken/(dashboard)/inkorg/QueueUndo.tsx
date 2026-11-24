"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useTransition,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { undoAssignment } from "./actions";
import styles from "./inkorg.module.css";

type Notice = { message: string; token?: string | null; error?: string };
const QueueUndo = createContext<{
  offerUndo: (token: string | null, message: string) => void;
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
  const [pending, start] = useTransition();
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 10_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const offerUndo = (token: string | null, message: string) => {
    setRevision((r) => r + 1);
    setNotice({ token, message });
  };

  const undo = () => {
    const token = notice?.token;
    if (!token) return;
    start(async () => {
      const res = await undoAssignment(token);
      setRevision((r) => r + 1);
      setNotice((current) => {
        if (current !== notice) return current;
        if (res.ok) return { message: t("queueAssignment.undone") };
        const { status, detail } = res.problem;
        const retryable =
          status >= 500 ||
          (status === 409 && detail.startsWith("Utskicket pågår"));
        return {
          message: notice.message,
          error: detail,
          token: retryable ? token : null,
        };
      });
    });
  };

  return (
    <QueueUndo.Provider value={{ offerUndo, revision }}>
      {children}
      {notice && (
        <div className={styles.undoBar} role="status">
          <span>{notice.message}</span>
          {notice.error && <span role="alert">{notice.error}</span>}
          {notice.token && (
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              disabled={pending}
              onClick={undo}
            >
              {t("queueAssignment.undo")}
            </button>
          )}
        </div>
      )}
    </QueueUndo.Provider>
  );
}
