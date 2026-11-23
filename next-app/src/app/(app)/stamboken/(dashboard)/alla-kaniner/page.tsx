import { fetchApi } from "@/lib/api";
import { PaginatedIndividualsResponse } from "@/redux/api/apiSlice";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import RabbitExplorer from "@/components/explorer/RabbitExplorer";

export const dynamic = "force-dynamic"; // Never statically generate

export default async function AllaKaninerPage() {
  // Auth handled by dashboard layout's requireUser()
  // fetchApi<T> throws on error — caught by error.tsx boundary
  let initialData: PaginatedIndividualsResponse | null = null;
  let initialGenebank = 0;
  try {
    const { genebanks } = await fetchApi<{
      genebanks: { id: number }[] | null;
    }>("/genebanks");
    const ids = (genebanks ?? []).map((g) => g.id);
    // Gotlandskanin (1) first, else the member's only genebank
    initialGenebank = ids.includes(1) ? 1 : (ids[0] ?? 0);
    const genebankParam = initialGenebank
      ? `&genebank_id=${initialGenebank}`
      : "";
    initialData = await fetchApi<PaginatedIndividualsResponse>(
      `/individuals?page=1&per_page=${DEFAULT_PAGE_SIZE}&sort=birth_date&order=desc&status=active${genebankParam}`,
    );
  } catch (e) {
    // If server-side fetch fails (e.g. API down), render with no initial data.
    // Client-side RTK Query will retry after hydration.
    console.error("SSR fetch failed for /api/individuals:", e);
  }

  return (
    <RabbitExplorer
      initialData={initialData}
      initialGenebank={initialGenebank}
    />
  );
}
