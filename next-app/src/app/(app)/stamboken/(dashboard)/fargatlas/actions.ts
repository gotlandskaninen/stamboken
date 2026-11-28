"use server";

import { cookies } from "next/headers";
import { fetchApi } from "@/lib/api";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import type { Fargatlas } from "@/lib/fargatlas/atlas";

/**
 * The atlas, and the base the browser loads its photos from: the photos need the session, so in test mode they
 * come from the demo API, as fetchApi reads the atlas from it (a session the demo API made is refused by /api).
 */
export async function getFargatlas(): Promise<{
  atlas: Fargatlas;
  fotoBas: string;
} | null> {
  const demo = parseMode((await cookies()).get(MODE_COOKIE)?.value) === "demo";
  // The same condition as fetchApi's for reading from the demo API, so the photos come from where the atlas came.
  const fotoBas =
    demo && process.env.API_TEST_INTERNAL_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL || "/api-test"
      : "/api";
  try {
    const atlas = await fetchApi<Fargatlas>("/v2/fargatlas");
    return { atlas, fotoBas };
  } catch {
    return null;
  }
}
