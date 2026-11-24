"use client";

import { usePathname } from "next/navigation";
import { Alert } from "@mui/material";
import { useMode } from "@/lib/mode-context";
import { Topbar } from "@/components/shell/Topbar";
import { ShellFooter } from "@/components/shell/ShellFooter";
import { TyckTillTab } from "@/components/tyck-till/TyckTillDialog.client";
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
  // Skicka in intyg and Mina inskick call production in every mode (inskick/).
  const toProd = usePathname()?.startsWith("/stamboken/inskick");
  return (
    <div className={styles.appShell}>
      <ModeHtmlAttribute />
      <Topbar inbox={inbox} />
      <main className={styles.appMain}>
        {mode === "demo" && <DemoBanner />}
        {mode === "demo" && toProd && (
          <Alert
            severity="info"
            sx={{ borderRadius: 0, justifyContent: "center" }}
          >
            Det du skickar in här går till riktiga Stamboken, också när du är i
            testmiljön.
          </Alert>
        )}
        <WipBanner />
        {children}
      </main>
      <ShellFooter />
      <TyckTillTab />
      <SessionExpiredModal />
    </div>
  );
}
