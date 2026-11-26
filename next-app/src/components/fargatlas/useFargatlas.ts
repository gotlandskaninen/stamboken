"use client";

import { useEffect, useState } from "react";
import { getFargatlas } from "@/app/(app)/stamboken/(dashboard)/fargatlas/actions";

export type AtlasData = Awaited<ReturnType<typeof getFargatlas>>;

/**
 * The atlas, read again each time `open` turns true, so a failed read gets a new try and a switch between test mode
 * and production gets the right atlas: undefined until the first answer, null when it could not be read.
 */
export function useFargatlas(open: boolean): AtlasData | undefined {
  const [data, setData] = useState<AtlasData | undefined>(undefined);
  // Each opening starts from "loading", never from the last opening's atlas or error.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setData(undefined);
  }
  useEffect(() => {
    if (!open) return;
    let current = true;
    getFargatlas().then(
      (atlas) => current && setData(atlas),
      () => current && setData(null),
    );
    return () => {
      current = false;
    };
  }, [open]);
  return data;
}
