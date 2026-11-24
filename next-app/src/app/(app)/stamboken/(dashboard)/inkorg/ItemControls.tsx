"use client";

import { useTranslation } from "react-i18next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { releaseItem, takeItem } from "./actions";
import { useQueueUndo } from "./QueueUndo";
import {
  itemActions,
  lacksRole,
  shownAssignment,
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
  item: Pick<
    InboxItem,
    "id" | "assigned_to" | "assigned_at" | "genebank_id" | "state"
  >;
  user: QueueUser;
  myGenebanks: number[] | null;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const { offerUndo } = useQueueUndo();
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
          : await takeItem(
              item.id,
              action === "over" ? shownAssignment(item) : undefined,
            );
      if (!res.ok) return setError(res.problem.detail);
      const message = {
        take: "taken",
        over: "takenOver",
        release: "released",
      };
      offerUndo(
        res.data.undo,
        t(`queueAssignment.${message[action]}`, { id: item.id }),
      );
      if (action === "take") router.push(href);
    });
  }

  return (
    <>
      {mine ? (
        <>
          <Link className="sb-btn" href={href} prefetch={false}>
            {t("queueAssignment.register")}
          </Link>
          {item.state === "tagen" && (
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              disabled={pending}
              onClick={() => change("release")}
            >
              {t("queueAssignment.release")}
            </button>
          )}
        </>
      ) : actions.includes("ta") ? (
        <button
          type="button"
          className="sb-btn"
          disabled={pending}
          onClick={() => change("take")}
        >
          {t("queueAssignment.register")}
        </button>
      ) : (
        actions.includes("ta_over") && (
          <button
            type="button"
            className="sb-btn"
            disabled={pending}
            onClick={() => change("over")}
          >
            {t("queueAssignment.takeOver", {
              name: item.assigned_to?.name.trim().split(/\s+/)[0],
            })}
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
