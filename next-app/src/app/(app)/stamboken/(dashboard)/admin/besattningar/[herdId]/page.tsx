import { notFound } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { HerdEditClient } from "./HerdEditClient";

export const dynamic = "force-dynamic";

// Shape per da.get_herd_for_admin.
export interface HerdDetail {
  id: number;
  // Legacy GET /api/manage/herd/<id>: `herd` = the code (G1274), `herd_name`
  // = the display name; `name` is a DIFFERENT legacy field (contact name)
  // and is usually null — never use it to identify the herd.
  herd: string;
  herd_name: string | null;
  name: string | null;
  name_privacy: string | null;
  physical_address: string | null;
  email: string | null;
  mobile_phone: string | null;
  wire_phone: string | null;
  www: string | null;
  is_active: boolean;
  genebank_id: number;
  genebank_name: string;
  // ALL users holding {"level":"owner","herd":<id>} — a herd can have
  // several owners (museum herds, shared family herds).
  owners: { id: number; username: string; fullname: string | null }[];
}

export default async function HerdDetailPage({
  params,
}: {
  params: Promise<{ herdId: string }>;
}) {
  await requireHerdAdmin();
  // URL:en bär besättningsnumret (G1274) — begripligt för användare;
  // API:et accepterar även det interna numeriska id:t (bakåtkompat).
  const { herdId } = await params;
  const herd = await fetchApi<HerdDetail>(
    `/manage/herd/${encodeURIComponent(herdId)}`,
    { forceProd: true },
  ).catch(() => null);
  if (!herd) notFound();

  return (
    <>
      <AdminBackLink
        href="/stamboken/admin/besattningar"
        label="Alla besättningar"
      />
      <div className={ds["ad-page-head"]}>
        <div>
          <h2 className={ds["ad-page-title"]}>
            {herd.herd}
            {herd.herd_name ? ` — ${herd.herd_name}` : ""}
          </h2>
          <div className={ds["ad-page-sub"]}>{herd.genebank_name}</div>
        </div>
      </div>
      <HerdEditClient herd={herd} />
    </>
  );
}
