import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { CreateHerdForm } from "./CreateHerdForm";

export const dynamic = "force-dynamic";

export default async function NewHerdPage() {
  const user = await requireHerdAdmin();
  const body = await fetchApi<{
    genebanks: { id: number; name: string }[];
  }>("/genebanks", { forceProd: true });
  // add_herd is gated admin-or-manager(own gb) server-side; scope the picker
  // the same way so managers only see their own gb(s).
  const genebanks = user.is_admin
    ? body.genebanks
    : body.genebanks.filter((gb) => (user.is_manager ?? []).includes(gb.id));
  return (
    <>
      <AdminBackLink
        href="/stamboken/admin/besattningar"
        label="Alla besättningar"
      />
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>Ny besättning</h2>
      </div>
      <CreateHerdForm genebanks={genebanks} />
    </>
  );
}
