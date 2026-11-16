"use client";

import { useState, useTransition } from "react";
import { cancelMessage, retryMessage } from "./actions";
import { rowAction } from "./lib";

export function RowActions({ id, status }: { id: number; status: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const action = rowAction(status);
  if (!action) return null;
  const run = () =>
    start(async () => {
      const res = await (action === "retry" ? retryMessage : cancelMessage)(id);
      setError(res ? res.error : null);
    });
  return (
    <>
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        disabled={pending}
        onClick={run}
      >
        {action === "retry" ? "Försök igen" : "Stoppa"}
      </button>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
