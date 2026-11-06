import { notFound } from "next/navigation";
import { getUser } from "@/lib/auth";
import type { UserContext } from "@/lib/user-context";
import { isHerdAdmin } from "../_components/navConfig";

/**
 * Page-level admin gate. The layout's role gate cannot protect
 * pages: Next renders layout and page CONCURRENTLY, so an admin-only page's
 * fetchApi fires (and its 403 escapes as a 500) even when the layout already
 * decided notFound() — found by e2e spec 02 on local-production. Every
 * admin-only page calls this FIRST. 404, not 403
 * (URL-enumeration hardening).
 */
export async function requireAdmin(): Promise<UserContext> {
  const user = await getUser();
  if (!user?.is_admin) notFound();
  return user;
}

/**
 * Page-level gate for the besättningar/genbanker surfaces (admin + manager).
 * The layout's hasAnyVisible() also admits matrikel admins since the landing
 * page grew its Medlemsregister card, so it no longer mirrors these pages'
 * authorization: a matrikel-only admin could open /stamboken/admin/genbanker/1
 * directly and be shown an editable form the API would refuse to save.
 * Same contract as requireAdmin — 404, not 403.
 */
export async function requireHerdAdmin(): Promise<UserContext> {
  const user = await getUser();
  if (!user || !isHerdAdmin(user)) notFound();
  return user;
}
