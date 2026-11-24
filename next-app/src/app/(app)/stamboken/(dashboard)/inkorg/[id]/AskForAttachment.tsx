"use client";

import { useState, useTransition } from "react";
import { useTranslation } from "react-i18next";
import { changeState } from "../actions";
import styles from "../inkorg.module.css";

export function AskForAttachment({ itemId }: { itemId: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (!open)
    return (
      <button
        type="button"
        className="sb-btn sb-btn-secondary"
        onClick={() => {
          setNote(t("queueDetail.requestNote"));
          setError(null);
          setOpen(true);
        }}
      >
        {t("queueDetail.request")}
      </button>
    );

  return (
    <form
      className={styles.ask}
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        start(async () => {
          const result = await changeState(itemId, "ofullstandig", {
            note: note.trim(),
          });
          if (result.ok) setOpen(false);
          else setError(result.problem.detail);
        });
      }}
    >
      <label className="sb-label">
        {t("queueDetail.messageToSender")}
        <textarea
          className="sb-input"
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          autoFocus
          required
        />
      </label>
      <p className={styles.muted}>{t("queueDetail.requestEffect")}</p>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      <div className={styles.row}>
        <button
          type="submit"
          className="sb-btn"
          disabled={pending || !note.trim()}
        >
          {t("queueDetail.send")}
        </button>
        <button
          type="button"
          className="sb-btn sb-btn-secondary"
          disabled={pending}
          onClick={() => setOpen(false)}
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}
