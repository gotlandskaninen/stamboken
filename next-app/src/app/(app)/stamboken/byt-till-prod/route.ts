import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { fetchApi } from "@/lib/api";
import {
  MODE_COOKIE,
  PROD_ORIGIN,
  isTestHost,
  modeCookieOptions,
} from "@/lib/mode";

/**
 * Landing point for "Byt till riktiga stamboken" from the test host: sets
 * sb_mode=prod on the production host, only for a promoted user (same check
 * as setMode). The test host never sets prod; it forwards here.
 */
export async function GET() {
  if (isTestHost(await headers()))
    redirect(`${PROD_ORIGIN}/stamboken/byt-till-prod`);
  let promoted = false;
  try {
    const user = await fetchApi<{ v2_prod_access?: boolean }>("/user", {
      forceProd: true,
    });
    promoted = !!user?.v2_prod_access;
  } catch {
    promoted = false;
  }
  if (promoted) (await cookies()).set(MODE_COOKIE, "prod", modeCookieOptions);
  redirect("/stamboken");
}
