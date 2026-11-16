"use client";

import { useMode } from "@/lib/mode-context";
import { Topbar } from "@/components/shell/Topbar";
import { ShellFooter } from "@/components/shell/ShellFooter";
import { DemoBanner } from "@/components/public/DemoBanner.client";
import { ModeHtmlAttribute } from "@/components/public/ModeHtmlAttribute.client";
import { WipBanner } from "@/components/public/WipBanner.client";
import SessionExpiredModal from "@/components/auth/SessionExpiredModal";
import type { InboxCount } from "@/lib/inkorg";
import styles from "@/components/shell/shell.module.css";

export function DashboardShell({
  children,
  inbox,
}: {
  children: React.ReactNode;
  inbox?: InboxCount;
}) {
  const mode = useMode();
  return (
    <div className={styles.appShell}>
      <ModeHtmlAttribute />
      <Topbar inbox={inbox} />
      <main className={styles.appMain}>
        {mode === "demo" && <DemoBanner />}
        <WipBanner />
        {children}
      </main>
      <ShellFooter />
      <SessionExpiredModal />
    </div>
  );
}
