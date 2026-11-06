"use client";

import { Alert } from "@mui/material";

/**
 * Unmissable demo-mode banner. The caller renders it only in demo mode
 * (via useMode()); when shown it is deliberately impossible to hide — no
 * dismiss button, no persisted-dismissal storage, no Collapse gating — so a
 * demo user can never lose the "everything resets nightly" warning (contrast
 * WipBanner.client.tsx, which is dismissible).
 *
 * Terminology (user-approved copy): demo mode is "testmiljön" in UI text;
 * "demo"/"prod" remain the internal Mode values.
 */
export function DemoBanner() {
  return (
    <Alert
      severity="warning"
      sx={{ borderRadius: 0, justifyContent: "center" }}
    >
      TESTMILJÖ – här kan du öva fritt. Allt återställs varje natt.
    </Alert>
  );
}
