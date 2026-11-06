"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { NAV_ITEMS } from "./nav-items";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

export function MobileMenu({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  const { t } = useTranslation();
  return (
    <nav className={styles.mobileNav} aria-label="Mobilmeny">
      {NAV_ITEMS.map((item) => {
        const active = pathname.startsWith(item.href);
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
          </Link>
        );
      })}
    </nav>
  );
}
