"use client";

import { useEffect } from "react";
import { markUploadsSeen } from "./ny/actions";

/**
 * Marks the user's "klart" notices read once the page is on their screen. The
 * render must not do it: a GET of the page (a link, a prefetch) would then write.
 */
export function MarkSeen() {
  useEffect(() => {
    void markUploadsSeen();
  }, []);
  return null;
}
