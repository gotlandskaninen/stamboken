"use client";

import Link from "next/link";
import { useTransition } from "react";
import { noticeHref, type Notice } from "@/lib/inkorg";
import { markNoticesRead } from "./actions";
import styles from "../inskick/inskick.module.css";

export function NoticeList({
  notices,
  unread,
}: {
  notices: Notice[];
  unread: number;
}) {
  const [pending, start] = useTransition();
  return (
    <section className="sb-card">
      <div className={styles.cardBody}>
        {unread > 0 && (
          <div className={styles.actions} style={{ marginBottom: 14 }}>
            <button
              type="button"
              className="sb-btn sb-btn-ghost sb-btn-sm"
              disabled={pending}
              onClick={() => start(() => void markNoticesRead({ all: true }))}
            >
              Markera alla som lästa
            </button>
          </div>
        )}
        <ul className={styles.list}>
          {notices.map((n) => (
            <li key={n.id}>
              <Link
                href={noticeHref(n)}
                className="sb-link"
                style={{ fontWeight: n.read_at ? 400 : 600 }}
                onClick={() => {
                  if (!n.read_at) void markNoticesRead({ ids: [n.id] });
                }}
              >
                {n.text}
                {n.item_id != null && ` (ärende ${n.item_id})`}
              </Link>
              <div className="sb-meta">
                {new Date(n.created_at).toLocaleString("sv-SE")}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
