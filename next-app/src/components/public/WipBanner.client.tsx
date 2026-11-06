"use client";

import { useEffect, useState } from "react";
import { Alert, Collapse, Link as MuiLink } from "@mui/material";

const DISMISS_KEY = "herdbook-wip-banner-dismissed";

/**
 * Dismissible "this is the new Stamboken (beta)" notice. Starts closed so the
 * server and first client render match (no hydration mismatch), then reveals
 * after reading localStorage; `unmountOnExit` removes it from the DOM once
 * dismissed. Dismissal is persisted per browser.
 */
export function WipBanner() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      setOpen(localStorage.getItem(DISMISS_KEY) !== "1");
    } catch {
      setOpen(true);
    }
  }, []);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // ignore unavailable localStorage
    }
    setOpen(false);
  };

  return (
    <Collapse in={open} unmountOnExit>
      <Alert
        severity="info"
        onClose={dismiss}
        sx={{ borderRadius: 0, justifyContent: "center" }}
      >
        Detta är nya Stamboken (beta). Den gamla versionen finns kvar på{" "}
        <MuiLink href="https://stamboken.gotlandskaninen.se" color="inherit">
          stamboken.gotlandskaninen.se
        </MuiLink>
        .
      </Alert>
    </Collapse>
  );
}
