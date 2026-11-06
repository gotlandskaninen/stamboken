"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { NAV_ITEMS } from "./nav-items";
import styles from "./topbar.module.css";

export function TopbarNav() {
  const pathname = usePathname();
  const { t } = useTranslation();
  return (
    <nav className={styles.nav} aria-label="Huvudmeny">
      {NAV_ITEMS.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.key}
            href={item.href}
            className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
            aria-current={active ? "page" : undefined}
          >
            {t(item.i18nKey)}
          </Link>
        );
      })}
    </nav>
  );
}
