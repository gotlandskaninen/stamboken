"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { releaseItem, takeItem } from "./actions";
import {
  itemActions,
  lacksRole,
  OPEN_STATES,
  type InboxItem,
  type QueueUser,
} from "./lib";
import styles from "./inkorg.module.css";

export function ItemControls({
  item,
  user,
  myGenebanks,
}: {
  item: Pick<InboxItem, "id" | "assigned_to" | "genebank_id" | "state">;
  user: QueueUser;
  myGenebanks: number[] | null;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState("");
  const href = `/stamboken/inkorg/${item.id}`;
  const actions = itemActions(item, user, myGenebanks);
  const mine = item.assigned_to?.id === user.id;
  if (
    !OPEN_STATES.includes(item.state) ||
    lacksRole(user, item.genebank_id, myGenebanks)
  )
    return null;

  function change(action: "take" | "over" | "release") {
    setError("");
    start(async () => {
      const res =
        action === "release"
          ? await releaseItem(item.id)
          : await takeItem(item.id, action === "over");
      if (!res.ok) return setError(res.problem.detail);
      if (action === "take") router.push(href);
    });
  }

  return (
    <>
      {mine ? (
        <>
          <Link className="sb-btn" href={href} prefetch={false}>
            Börja registrera
          </Link>
          <button
            type="button"
            className="sb-btn sb-btn-secondary"
            disabled={pending}
            onClick={() => change("release")}
          >
            Släpp ärendet
          </button>
        </>
      ) : actions.includes("ta") ? (
        <button
          type="button"
          className="sb-btn"
          disabled={pending}
          onClick={() => change("take")}
        >
          Börja registrera
        </button>
      ) : (
        actions.includes("ta_over") && (
          <button
            type="button"
            className="sb-btn"
            disabled={pending}
            onClick={() => change("over")}
          >
            Ta över från {item.assigned_to?.name.trim().split(/\s+/)[0]}
          </button>
        )
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </>
  );
}
