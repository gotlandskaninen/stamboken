import { fetchApi } from "@/lib/api";
import { PaginatedIndividualsResponse } from "@/redux/api/apiSlice";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import RabbitExplorer from "@/components/explorer/RabbitExplorer";

export const dynamic = "force-dynamic"; // Never statically generate

export default async function AllaKaninerPage() {
  // Auth handled by dashboard layout's requireUser()
  // fetchApi<T> throws on error — caught by error.tsx boundary
  let initialData: PaginatedIndividualsResponse | null = null;
  try {
    initialData = await fetchApi<PaginatedIndividualsResponse>(
      `/individuals?page=1&per_page=${DEFAULT_PAGE_SIZE}&sort=name&order=asc`,
    );
  } catch (e) {
    // If server-side fetch fails (e.g. API down), render with no initial data.
    // Client-side RTK Query will retry after hydration.
    console.error("SSR fetch failed for /api/individuals:", e);
  }

  return <RabbitExplorer initialData={initialData} />;
}
