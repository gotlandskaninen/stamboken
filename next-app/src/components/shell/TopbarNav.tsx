"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { badgeKey, badgeLabel, navItemsFor } from "./nav-items";
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
    </nav>
  );
}
