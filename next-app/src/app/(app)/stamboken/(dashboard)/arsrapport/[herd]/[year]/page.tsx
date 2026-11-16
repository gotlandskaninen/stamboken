import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ApiError, fetchApi } from "@/lib/api";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { dryRun, saveDraft, submitReport, withdrawReport } from "../../actions";
import { getGenebankHerds } from "../../../individ/[number]/actions";
import type { InboxDetail } from "../../../inkorg/lib";
import type { ReportView } from "../../lib";
import { ReportForm } from "../../ReportForm";
import { PaperEntry } from "./PaperEntry";

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
  // The data environment the fetch below answers from (api.ts reads the same cookie).
  const env = parseMode((await cookies()).get(MODE_COOKIE)?.value);
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
  if (post && view.item) {
    // The queue item behind the paper form: its pages and its other documents.
    const item = await fetchApi<InboxDetail>(`/v2/inkorg/${post}`);
    return (
      <PaperEntry
        key={env}
        env={env}
        view={view}
        item={item}
        post={post}
        actions={{
          saveDraft,
          dryRun,
          submitReport,
          withdrawReport,
          getGenebankHerds,
        }}
      />
    );
  }
  return (
    <ReportForm
      key={env}
      env={env}
      view={view}
      actions={{
        saveDraft,
        dryRun,
        submitReport,
        withdrawReport,
        getGenebankHerds,
      }}
      post={post}
    />
  );
}
