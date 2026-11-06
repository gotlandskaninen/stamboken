import { notFound } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import { AdminBackLink } from "../../_components/AdminBackLink";
import type { AdminUserDetail, AdminUserListItem } from "../../_lib/types";
import type { UserOption } from "../../_components/OwnerPickerAutocomplete";
import { GenebankEditClient } from "./GenebankEditClient";

export const dynamic = "force-dynamic";

interface GenebankDetail {
  id: number;
  name: string;
  herds: { id: number; is_active: boolean | null }[];
}

export default async function GenebankDetailPage({
  params,
}: {
  params: Promise<{ gbId: string }>;
}) {
  const user = await requireHerdAdmin();
  const { gbId } = await params;
  const gbid = Number(gbId);
  if (!Number.isFinite(gbid)) notFound();

  const gb = await fetchApi<GenebankDetail>(`/genebank/${gbid}`, {
    forceProd: true,
  }).catch(() => null);
  if (!gb) notFound();

  // Admin-only: resolve current managers of THIS gb + picker options.
  let managers: UserOption[] = [];
  let userOptions: UserOption[] = [];
  if (user.is_admin) {
    const list = await fetchApi<{ users: AdminUserListItem[] }>(
      "/v2/admin/users?role=manager&per_page=200",
      { forceProd: true },
    );
    const details = await Promise.all(
      list.users.map((u) =>
        fetchApi<AdminUserDetail>(`/v2/admin/users/${u.id}`, {
          forceProd: true,
        }),
      ),
    );
    managers = details
      .filter((d) =>
        d._privileges.some((p) => p.level === "manager" && p.genebank === gbid),
      )
      .map((d) => ({
        id: d.id,
        // hbuser.username is nullable — fall back to the non-null email.
        username: d.username ?? d.email,
        fullname: d.fullname ?? "",
      }));
    const allUsers = await fetchApi<{
      users: { id: number; name: string; fullname: string | null }[];
    }>("/manage/users", { forceProd: true });
    userOptions = (allUsers.users ?? []).map((u) => ({
      id: u.id,
      username: u.name,
      fullname: u.fullname ?? "",
    }));
  }

  const activeHerds = gb.herds.filter((h) => h.is_active).length;

  return (
    <>
      <AdminBackLink href="/stamboken/admin/genbanker" label="Alla genbanker" />
      <div className={ds["ad-page-head"]}>
        <div>
          <h2 className={ds["ad-page-title"]}>{gb.name}</h2>
          <div className={ds["ad-page-sub"]}>
            {activeHerds === 1
              ? "1 aktiv besättning"
              : `${activeHerds} aktiva besättningar`}
            {user.is_admin
              ? ` · ${managers.length} ${managers.length === 1 ? "genbanksansvarig" : "genbanksansvariga"}`
              : ""}
          </div>
        </div>
      </div>
      <GenebankEditClient
        gb={{ id: gb.id, name: gb.name }}
        isAdmin={user.is_admin}
        managers={managers}
        userOptions={userOptions}
      />
    </>
  );
}
