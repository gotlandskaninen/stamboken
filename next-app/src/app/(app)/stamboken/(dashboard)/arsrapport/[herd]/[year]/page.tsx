import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { dryRun, saveDraft, submitReport, withdrawReport } from "../../actions";
import type { ReportView } from "../../lib";
import { ReportForm } from "../../ReportForm";

export const dynamic = "force-dynamic";

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ herd: string; year: string }>;
  searchParams: Promise<{ post?: string }>;
}) {
  const [{ herd, year }, sp] = await Promise.all([params, searchParams]);
  if (!/^[A-Z]{1,3}[0-9]{1,6}$/.test(herd) || !/^\d{4}$/.test(year)) notFound();
  const post = /^\d+$/.test(sp.post ?? "") ? Number(sp.post) : undefined;
  let view: ReportView;
  try {
    view = await fetchApi<ReportView>(
      `/v2/arsrapport/besattning/${herd}/${year}${post ? `?post=${post}` : ""}`,
    );
  } catch (e) {
    if (e instanceof ApiError && (e.status === 403 || e.status === 404))
      notFound();
    throw e;
  }
  return (
    <ReportForm
      view={view}
      actions={{ saveDraft, dryRun, submitReport, withdrawReport }}
      post={post}
    />
  );
}
