import { Suspense } from "react";
import { getUser } from "@/lib/auth";
import { fetchApi } from "@/lib/api";
import MinBesattningContent from "./min-besattning-content";

export const dynamic = "force-dynamic";

export default async function MinBesattningPage({
  searchParams,
}: {
  searchParams: Promise<{ herd?: string; tab?: string }>;
}) {
  // Auth handled by dashboard layout's requireUser() — use getUser() here
  // so SSR degrades gracefully if the API is briefly unreachable
  const [user, params] = await Promise.all([getUser(), searchParams]);

  const userHerdNumber = params.herd || (user?.is_owner?.[0] ?? null);
  const initialTab = params.tab || null;

  if (!user || !userHerdNumber) {
    return (
      <Suspense>
        <MinBesattningContent
          herd={null}
          breedings={null}
          herdNumber={null}
          initialTab={initialTab}
        />
      </Suspense>
    );
  }

  // Fetch herd + breeding data in parallel
  const [herdResult, breedingResult] = await Promise.allSettled([
    fetchApi(`/herd/${userHerdNumber}`),
    fetchApi<{ breedings: any[] }>(`/breeding/${userHerdNumber}`),
  ]);

  const herd = herdResult.status === "fulfilled" ? herdResult.value : null;
  const breedings =
    breedingResult.status === "fulfilled"
      ? breedingResult.value.breedings
      : null;

  if (herdResult.status === "rejected") {
    console.error("SSR fetch failed for /api/herd:", herdResult.reason);
  }
  if (breedingResult.status === "rejected") {
    console.error("SSR fetch failed for /api/breeding:", breedingResult.reason);
  }

  return (
    <Suspense>
      <MinBesattningContent
        herd={herd}
        breedings={breedings}
        herdNumber={userHerdNumber}
        initialTab={initialTab}
      />
    </Suspense>
  );
}
