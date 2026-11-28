"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { badgeKey, badgeLabel, navItemsFor, RESURSER } from "./nav-items";
import styles from "./topbar.module.css";

export function TopbarNav({
  worksInQueue = false,
  unread = 0,
}: {
  worksInQueue?: boolean;
  unread?: number;
}) {
  const pathname = usePathname();
  const { t } = useTranslation();
  return (
    <nav className={styles.nav} aria-label="Huvudmeny">
      {navItemsFor(worksInQueue).map((item) => {
        const active = pathname.startsWith(item.href);
        const badge =
          item.key === badgeKey(worksInQueue) ? badgeLabel(unread) : null;
        return (
          <Link
            key={item.key}
            href={item.href}
            className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
            aria-current={active ? "page" : undefined}
            data-tour={`nav-${item.key}`}
          >
            {t(item.i18nKey)}
            {badge && (
              <span
                className={styles.navBadge}
                aria-label={`${badge} olästa notiser`}
              >
                {badge}
              </span>
            )}
          </Link>
        );
      })}
      <Resurser />
    </nav>
  );
}

/** The "Resurser" submenu: opens on click, closes on Escape, a click outside or a choice. */
function Resurser() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const utanfor = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", utanfor);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", utanfor);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const active = RESURSER.some((r) => !r.extern && pathname.startsWith(r.href));
  return (
    <div ref={ref} className={styles.navGrupp}>
      <button
        type="button"
        className={`${styles.navItem} ${styles.navKnapp} ${active ? styles.navItemActive : ""}`}
        aria-expanded={open}
        aria-controls="resurser-meny"
        onClick={() => setOpen((o) => !o)}
      >
        {t("sidebar.resurser")}
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d="m6 9 6 6 6-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>
      </button>
      {open && (
        <ul id="resurser-meny" className={styles.navMeny}>
          {RESURSER.map((r) => (
            <li key={r.key}>
              <Link
                href={r.href}
                className={styles.navMenyLank}
                aria-current={
                  !r.extern && pathname.startsWith(r.href) ? "page" : undefined
                }
                onClick={() => setOpen(false)}
                {...(r.extern && { target: "_blank", rel: "noopener" })}
              >
                {t(r.i18nKey)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
