"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ClickAwayListener from "@mui/material/ClickAwayListener";
import Popper from "@mui/material/Popper";
import { useTranslation } from "react-i18next";
import {
  useNotifications,
  type Notification,
} from "@/contexts/NotificationContext";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

const MAX_VISIBLE = 8;

function formatTime(date: Date, nowLabel: string) {
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / (1000 * 60));
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (minutes < 1) return nowLabel;
  if (minutes < 60) return `${minutes}m`;
  if (hours < 24) return `${hours}h`;
  return `${days}d`;
}

const TYPE_CLASS: Record<Notification["type"], string> = {
  success: styles.typeSuccess,
  error: styles.typeError,
  warning: styles.typeWarning,
  info: styles.typeInfo,
};

export function NotificationBell() {
  const { t } = useTranslation();
  const { notifications, getUnreadCount, markAsRead, markAllAsRead } =
    useNotifications();
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  const unreadCount = getUnreadCount();
  const visible = notifications.slice(0, MAX_VISIBLE);
  const hiddenCount = notifications.length - visible.length;

  const closeAndRefocus = () => {
    setOpen(false);
    anchorRef.current?.focus();
  };

  // Non-modal Popper: Escape must work regardless of where focus sits.
  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        anchorRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const handleClickAway = (event: MouseEvent | TouchEvent) => {
    // The trigger's own click already toggles — don't double-close.
    if (anchorRef.current?.contains(event.target as Node)) {
      return;
    }
    setOpen(false);
  };

  const handleRowClick = (notification: Notification) => {
    if (!notification.read) {
      markAsRead(notification.id);
    }
    if (notification.action) {
      notification.action.onClick?.();
      // Action rows navigate (href) or act (onClick) — the popover must not
      // linger over the destination. Plain rows stay open for mark-as-read.
      setOpen(false);
    }
  };

  return (
    <>
      <button
        type="button"
        ref={anchorRef}
        className={styles.bellBtn}
        aria-label={t("notifications.title")}
        title={t("notifications.title")}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <SbIcon name="bell" size={19} />
        {unreadCount > 0 && (
          <span className={styles.bellDot}>
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>
      <Popper
        open={open}
        anchorEl={anchorRef.current}
        placement="bottom-end"
        className={styles.popper}
        modifiers={[{ name: "offset", options: { offset: [0, 8] } }]}
      >
        <ClickAwayListener onClickAway={handleClickAway}>
          <div
            role="dialog"
            aria-label={t("notifications.title")}
            className={`sb-card ${styles.popover}`}
          >
            <div className={styles.popoverHead}>
              <span className="sb-h6">{t("notifications.title")}</span>
              <button
                type="button"
                className="sb-btn sb-btn-ghost sb-btn-sm"
                onClick={closeAndRefocus}
              >
                {t("notifications.close")}
              </button>
            </div>
            {unreadCount > 0 && (
              <div className={styles.markAllRow}>
                <button
                  type="button"
                  className="sb-btn sb-btn-ghost sb-btn-sm"
                  onClick={markAllAsRead}
                >
                  {t("notifications.markAllRead")}
                </button>
              </div>
            )}
            {visible.length === 0 ? (
              <div className={styles.notifEmpty}>
                {t("notifications.empty")}
              </div>
            ) : (
              visible.map((notification) => {
                const rowClass = [
                  styles.notif,
                  TYPE_CLASS[notification.type],
                  notification.read ? "" : styles.unread,
                ]
                  .filter(Boolean)
                  .join(" ");
                const content = (
                  <>
                    <span className={styles.notifTitle}>
                      <span>{notification.title}</span>
                      <span className="sb-meta">
                        {formatTime(
                          notification.timestamp,
                          t("notifications.now"),
                        )}
                      </span>
                    </span>
                    <span className={styles.notifBody}>
                      {notification.message}
                    </span>
                  </>
                );
                return notification.action?.href ? (
                  <Link
                    key={notification.id}
                    href={notification.action.href}
                    className={rowClass}
                    onClick={() => handleRowClick(notification)}
                  >
                    {content}
                  </Link>
                ) : (
                  <button
                    key={notification.id}
                    type="button"
                    className={rowClass}
                    onClick={() => handleRowClick(notification)}
                  >
                    {content}
                  </button>
                );
              })
            )}
            {hiddenCount > 0 && (
              <div className={`${styles.olderRow} sb-meta`}>
                {t("notifications.older", { count: hiddenCount })}
              </div>
            )}
          </div>
        </ClickAwayListener>
      </Popper>
    </>
  );
}
