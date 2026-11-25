import type { GeneticPriority } from "@/redux/api/apiSlice";

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
export const byHerd = (rows: GeneticPriority[]) =>
  [...rows].sort(
    (a, b) =>
      PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] ||
      (a.herd ?? "").localeCompare(b.herd ?? "", "sv", { numeric: true }),
  );

/**
 * The server's CSV of the list (app/blueprints/genetics.py), which logs who took which rabbits.
 * Same demo/prod routing rule as the RTK baseQuery and medlem/statistik/exportUrl.ts: the demo
 * goes to the test API, which refuses the export, never to production.
 */
export function prioritiesCsvUrl(
  mode: string,
  apiTestUrl: string | undefined,
  genebankId: number,
  levels: GeneticPriority["priority"][],
  perHerd: boolean,
): string {
  const base = mode === "demo" && apiTestUrl ? apiTestUrl : "/api";
  const query = `levels=${levels.join(",")}${perHerd ? "&per_herd=1" : ""}`;
  return `${base}/v2/genetics/${genebankId}/priorities.csv?${query}`;
}

/**
 * Fetches the file and hands it to the browser. On a refusal (the demo, an expired
 * session) it returns the server's reason instead, so the page can show it in place.
 */
export async function downloadExport(url: string): Promise<string | null> {
  const failed = "Filen gick inte att hämta. Försök igen om en stund.";
  let res: Response;
  try {
    res = await fetch(url, { credentials: "include" });
  } catch {
    return failed;
  }
  if (!res.ok) {
    const problem = await res.json().catch(() => null);
    return problem?.detail ?? failed;
  }
  const name =
    /filename="([^"]+)"/.exec(
      res.headers.get("Content-Disposition") ?? "",
    )?.[1] ?? "avelsprioritet.csv";
  const href = URL.createObjectURL(await res.blob());
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
