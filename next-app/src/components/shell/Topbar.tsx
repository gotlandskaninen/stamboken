"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { TopbarNav } from "./TopbarNav";
import { MobileMenu } from "./MobileMenu";
import { LanguageToggle } from "./LanguageToggle";
import { NotificationBell } from "./NotificationBell";
import { AvatarMenu } from "./AvatarMenu";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

export function Topbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  // Close the mobile menu whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  return (
    <header className={styles.topbar}>
      <div className={styles.inner}>
        <div className={styles.left}>
          <button
            type="button"
            className={styles.menuBtn}
            aria-label="Meny"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((v) => !v)}
          >
            <SbIcon name="menu" size={22} />
          </button>
          <Link href="/stamboken/min-besattning" className={styles.wordmark}>
            <Image
              src="/stamboken/logo.png"
              alt=""
              width={33}
              height={33}
              className={styles.emblem}
            />
            <span className={styles.wordmarkText}>Stamboken</span>
          </Link>
          <TopbarNav />
        </div>
        <div className={styles.right}>
          <LanguageToggle />
          <NotificationBell />
          <AvatarMenu />
        </div>
      </div>
      {mobileOpen && <MobileMenu onNavigate={() => setMobileOpen(false)} />}
    </header>
  );
}
