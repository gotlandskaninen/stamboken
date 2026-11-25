import { useEffect, useState } from "react";
import type { GeneticPriority } from "@/redux/api/apiSlice";
import { MODE_COOKIE, type Mode } from "@/lib/mode";

/** A row of the work list: a priority with the rabbit's details, read fresh (app/blueprints/genetics.py). */
export interface WorkListRow extends GeneticPriority {
  // Missing when the database no longer has the number; name and herd null when the
  // rabbit now stands in a genebank the user cannot read.
  name?: string | null;
  sex?: "female" | "male" | "eunuch" | null; // eunuch: a legacy value
  birth_date?: string | null; // YYYY-MM-DD
  herd?: string | null; // current besättningsnummer
}

// The view's own mode picks the API, by the RTK baseQuery's rule (modeAwareBaseQuery).
const apiBase = (mode: Mode) =>
  mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
    ? process.env.NEXT_PUBLIC_API_TEST_URL
    : "/api";

/**
 * The work list, read with fetch and not RTK Query (ADR-0008: no new RTK endpoints). The server
 * logs every read. `error` has the shape GeneticsError reads ({ status }).
 */
export function useWorkList(genebankId: number, mode: Mode) {
  // Each answer is bound to the mode and genebank it was asked for: after a switch the
  // list is loading until its own answer arrives, never the other mode's rows.
  const asked = `${mode}:${genebankId}`;
  const [result, setResult] = useState<{
    asked?: string;
    data?: WorkListRow[];
    error?: { status: number | string };
  }>({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // Started a tick later and cancelled on unmount or a new genebank, so a read the page
    // drops is never sent: every read is logged, and React's dev double mount would log two.
    const controller = new AbortController();
    const start = setTimeout(() =>
      fetch(`${apiBase(mode)}/v2/genetics/${genebankId}/work-list`, {
        credentials: "include",
        signal: controller.signal,
      })
        .then(async (res) => {
          const next = res.ok
            ? { asked, data: (await res.json()) as WorkListRow[] }
            : { asked, error: { status: res.status } };
          if (!controller.signal.aborted) setResult(next);
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setResult({ asked, error: { status: "FETCH_ERROR" } });
        }),
    );
    return () => {
      clearTimeout(start);
      controller.abort();
    };
  }, [asked, genebankId, mode, attempt]);
  const own = result.asked === asked ? result : {};
  return {
    data: own.data,
    error: own.error,
    isLoading: !own.data && !own.error,
    refetch: () => {
      setResult({});
      setAttempt((n) => n + 1);
    },
  };
}

export const PRIORITY_ORDER: Record<GeneticPriority["priority"], number> = {
  critical: 0,
  important: 1,
  normal: 2,
};

export const PRIORITY_LABEL: Record<GeneticPriority["priority"], string> = {
  critical: "Högsta",
  important: "Hög",
  normal: "Övriga",
};

export const sexLabel = (sex?: string | null) =>
  sex === "female"
    ? "Hona"
    : sex === "male"
      ? "Hane"
      : sex === "eunuch" // a legacy value
        ? "Hane (kastrerad)"
        : "Okänt";

/** The rows grouped per besättning within each level, so Högsta comes first and each herd's rabbits together. */
export const byHerd = (rows: WorkListRow[]) =>
  [...rows].sort(
    (a, b) =>
      PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] ||
      (a.herd ?? "").localeCompare(b.herd ?? "", "sv", { numeric: true }),
  );

/** The server's text (DEMO_EXPORT_REFUSED, app/blueprints/common.py). */
export const EXPORT_ONLY_IN_PROD =
  "Exporten går bara att göra i den riktiga Stamboken, där varje uttag loggas.";

const SWITCHED_TO_DEMO =
  "Stamboken har bytts till testmiljön i en annan flik. Ladda om sidan innan du laddar ner.";

/** The sb_mode cookie as sent (undefined when missing); readModeCookieClient turns a missing one into demo. */
export function rawModeCookie(): string | undefined {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${MODE_COOKIE}=`))
    ?.slice(MODE_COOKIE.length + 1);
}

/**
 * Why the export may not start, or null. The file is real data and every download is logged,
 * so only a view of the riktiga Stamboken exports. A cookie set to exactly "demo" means another
 * tab has switched to the testmiljö since; the server refuses that request too.
 */
export function exportRefusal(
  viewMode: Mode,
  cookie: string | undefined,
): string | null {
  if (viewMode !== "prod") return EXPORT_ONLY_IN_PROD;
  if (cookie === "demo") return SWITCHED_TO_DEMO;
  return null;
}

/** The server's CSV of the list (app/blueprints/genetics.py), which logs who took which rabbits. */
export function prioritiesCsvUrl(
  genebankId: number,
  levels: GeneticPriority["priority"][],
  perHerd: boolean,
): string {
  const query = `levels=${levels.join(",")}${perHerd ? "&per_herd=1" : ""}`;
  return `/api/v2/genetics/${genebankId}/priorities.csv?${query}`;
}

/**
 * Fetches the file and hands it to the browser. On a refusal (the demo, an expired
 * session) it returns the server's reason instead, so the page can show it in place.
 */
export async function downloadExport(
  url: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const failed = "Filen gick inte att hämta. Försök igen om en stund.";
  let res: Response;
  let blob: Blob;
  try {
    res = await fetch(url, { credentials: "include", signal });
    if (res.ok) blob = await res.blob();
  } catch {
    return signal?.aborted ? null : failed;
  }
  if (!res.ok) {
    const problem = await res.json().catch(() => null);
    return problem?.detail ?? failed;
  }
  const name =
    /filename="([^"]+)"/.exec(
      res.headers.get("Content-Disposition") ?? "",
    )?.[1] ?? "avelsprioritet.csv";
  // The page or its mode changed while the file came: nothing is saved.
  if (signal?.aborted) return null;
  if (rawModeCookie() === "demo") return SWITCHED_TO_DEMO;
  const href = URL.createObjectURL(blob!);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  // In the document while clicked (Firefox needs that); the blob lives until the download has started.
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
  return null;
}
