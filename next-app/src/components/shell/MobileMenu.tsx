"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { badgeKey, badgeLabel, navItemsFor } from "./nav-items";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

export function MobileMenu({
  onNavigate,
  worksInQueue = false,
  unread = 0,
}: {
  onNavigate: () => void;
  worksInQueue?: boolean;
  unread?: number;
}) {
  const pathname = usePathname();
  const { t } = useTranslation();
  return (
    <nav className={styles.mobileNav} aria-label="Mobilmeny">
      {navItemsFor(worksInQueue).map((item) => {
        const active = pathname.startsWith(item.href);
        const badge =
          item.key === badgeKey(worksInQueue) ? badgeLabel(unread) : null;
        return (
          <Link
            key={item.key}
            href={item.href}
            onClick={onNavigate}
            className={`${styles.mobileNavItem} ${active ? styles.mobileNavItemActive : ""}`}
            aria-current={active ? "page" : undefined}
          >
            <SbIcon name={item.icon} size={18} />
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
