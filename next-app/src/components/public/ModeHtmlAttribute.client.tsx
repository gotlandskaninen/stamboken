"use client";
import { useEffect } from "react";
import { useMode } from "@/lib/mode-context";

/**
 * Mirrors the current mode onto <html data-mode="…"> so tokens.css can restyle
 * the whole page (body background included) in testmiljön. The root layout is
 * a server component without access to the mode cookie, hence the effect.
 */
export function ModeHtmlAttribute() {
  const mode = useMode();
  useEffect(() => {
    document.documentElement.dataset.mode = mode;
    return () => {
      delete document.documentElement.dataset.mode;
    };
  }, [mode]);
  return null;
}
