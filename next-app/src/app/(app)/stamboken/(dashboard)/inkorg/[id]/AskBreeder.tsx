"use client";

import { useState, useTransition } from "react";
import type { Rect } from "../lib";
import { askBreeder } from "./ask";
import styles from "../inkorg.module.css";

/**
 * "Fråga uppfödaren": a question by mail to the herd's holder, who answers by
 * replying. With "Bifoga utsnitt" a frame lies on the photo (the caller draws
 * it with the photo's rectangle editor) and its part of the photo goes along.
 * `crop` is the frame in the document's saved rotation, as the API takes it.
 */
export function AskBreeder({
  itemId,
  documentId,
  crop,
  onFrame,
}: {
  itemId: number;
  documentId: number | null;
  crop: Rect | null;
  onFrame: (on: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const close = () => {
    setOpen(false);
    setText("");
    setError(null);
    onFrame(false);
  };

  if (!open)
    return (
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        aria-expanded={false}
        onClick={() => setOpen(true)}
      >
        Fråga uppfödaren
      </button>
    );

  return (
    <form
      className={styles.ask}
      aria-label="Fråga uppfödaren"
      onSubmit={(e) => {
        e.preventDefault();
        start(async () => {
          const part =
            crop && documentId !== null ? { document: documentId, crop } : null;
          const res = await askBreeder(itemId, text, part);
          if (res.ok) close();
          else setError(res.problem.detail);
        });
      }}
    >
      <label className="sb-label">
        Frågan går per mejl till besättningens innehavare. Svaret hamnar här.
        <textarea
          className="sb-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          maxLength={2000}
          required
          autoFocus
        />
      </label>
      {documentId !== null && (
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={crop !== null}
            onChange={(e) => onFrame(e.target.checked)}
          />
          Bifoga utsnitt
        </label>
      )}
      {crop && (
        <p className={styles.muted}>
          Dra ramen på fotot runt det som frågan gäller.
        </p>
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      <div className={styles.row}>
        <button type="submit" className="sb-btn sb-btn-sm" disabled={pending}>
          Skicka frågan
        </button>
        <button
          type="button"
          className="sb-btn sb-btn-ghost sb-btn-sm"
          onClick={close}
        >
          Avbryt
        </button>
      </div>
    </form>
  );
}
