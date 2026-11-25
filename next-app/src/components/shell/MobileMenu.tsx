"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { badgeKey, badgeLabel, navItemsFor, RESURSER } from "./nav-items";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

export function MobileMenu({
  onNavigate,
  onTyckTill,
  worksInQueue = false,
  unread = 0,
}: {
  onNavigate: () => void;
  onTyckTill: () => void;
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
      <p className={styles.mobileNavRubrik} id="mobil-resurser">
        {t("sidebar.resurser")}
      </p>
      <ul className={styles.mobileNavLista} aria-labelledby="mobil-resurser">
        {RESURSER.map((r) => {
          const active = !r.extern && pathname.startsWith(r.href);
          return (
            <li key={r.key}>
              <Link
                href={r.href}
                onClick={onNavigate}
                className={`${styles.mobileNavItem} ${active ? styles.mobileNavItemActive : ""}`}
                aria-current={active ? "page" : undefined}
                {...(r.extern && { target: "_blank", rel: "noopener" })}
              >
                <SbIcon name={r.icon} size={18} />
                {t(r.i18nKey)}
              </Link>
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        onClick={onTyckTill}
        className={`${styles.mobileNavItem} ${styles.mobileNavButton}`}
      >
        <SbIcon name="message" size={18} />
        Tyck till
      </button>
    </nav>
  );
}
