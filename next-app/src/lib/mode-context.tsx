"use client";
import { createContext, useContext } from "react";
import type { Mode } from "@/lib/mode";

// Server-first (ADR-0008): the dashboard layout resolves the initial mode from
// the sb_mode cookie during SSR and passes it here, so client components (banner,
// toggle) render the correct mode with no flash-of-wrong-mode.
const ModeCtx = createContext<Mode | null>(null);

export function ModeProvider({
  mode,
  children,
}: {
  mode: Mode;
  children: React.ReactNode;
}) {
  return <ModeCtx.Provider value={mode}>{children}</ModeCtx.Provider>;
}

export function useMode() {
  const ctx = useContext(ModeCtx);
  if (!ctx) throw new Error("useMode must be used within ModeProvider");
  return ctx;
}
