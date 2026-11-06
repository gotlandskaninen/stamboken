import { fetchApi } from "@/lib/api";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { SystemPillNav } from "../../_components/SystemPillNav";
import { requireAdmin } from "../../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import { OnlineClient } from "./OnlineClient";
import { MassLogoutClient } from "./MassLogoutClient";

export const dynamic = "force-dynamic";

type OnlineRow = {
  username: string | null; // hbuser.username is nullable
  fullname: string | null;
  last_active: string | null;
};

export default async function OnlinePage({
  searchParams,
}: {
  searchParams: Promise<{ minutes?: string }>;
}) {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const sp = await searchParams;
  const minutes = ["1", "5", "15"].includes(sp.minutes ?? "")
    ? (sp.minutes as string)
    : "5";
  const rows = await fetchApi<OnlineRow[]>(
    `/v2/admin/online-users?minutes=${minutes}`,
    { forceProd: true },
  );
  return (
    <>
      <AdminBackLink href="/stamboken/admin/system" label="System" />
      <SystemPillNav current="online" />
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>Aktiva användare</h2>
      </div>
      <p className={ds["ad-hint"]}>
        Listan visar användare som varit aktiva under den valda tidsperioden.
      </p>
      <OnlineClient rows={rows} minutes={minutes} />
      <MassLogoutClient />
    </>
  );
}
