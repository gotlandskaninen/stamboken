import { fetchApi } from "@/lib/api";
import type { IndividualGeneticsData } from "@/lib/genetics";
import { GeneticsSummary } from "./GeneticsSummary";

/** Server Component in its own <Suspense>: a cold build never blocks the page. */
export async function IndividualGenetics({ number }: { number: string }) {
  let data: IndividualGeneticsData;
  try {
    data = await fetchApi<IndividualGeneticsData>(
      `/v2/individual/${encodeURIComponent(number)}/genetics`,
      { timeout: 30000 },
    );
  } catch {
    return <p className="sb-meta">Genetiken kan inte visas just nu</p>;
  }
  return <GeneticsSummary data={data} />;
}

export function GeneticsSkeleton() {
  return <p className="sb-meta">Hämtar genetik…</p>;
}
