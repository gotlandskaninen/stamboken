import { cookies } from "next/headers";
import { fetchApi } from "@/lib/api";
import { requireDashboardSession } from "@/lib/auth";
import { NO_INBOX } from "@/lib/inkorg";
import { getInboxCount } from "@/lib/inkorg-server";
import { UserProvider } from "@/lib/user-context";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { ModeProvider } from "@/lib/mode-context";
import { DemoAccountMissing } from "@/components/public/DemoAccountMissing.client";
import { ClientProviders } from "../../client-providers";
import { DashboardShell } from "./dashboard-shell";

// "[TEST]" first in the tab title in testmiljön, so open tabs differ too.
export async function generateMetadata() {
  const cookieStore = await cookies();
  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  const prefix = mode === "demo" ? "[TEST] " : "";
  return {
    title: { default: `${prefix}Stamboken`, template: `${prefix}%s` },
  };
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await requireDashboardSession();
  // CR-02: valid prod session but no row in herdbook_demo yet (account newer
  // than the nightly sync) — friendly info page instead of a redirect loop.
  if (session.kind === "missing-in-demo") {
    return (
      <ClientProviders>
        <DemoAccountMissing />
      </ClientProviders>
    );
  }
  const user = session.user;
  // Resolve the initial mode server-side so client components render the
  // correct dataset with no flash-of-wrong-mode (ADR-0008 server-first).
  const cookieStore = await cookies();
  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  // The menu must render even when the notice count is unavailable.
  const inbox = await getInboxCount().catch(() => NO_INBOX);
  // The check page choice (stamboken #6) from production, where it is saved: the demo copy can be a day old. Only
  // for those who issue certificates, the hint's only readers; unknown leaves the hint hidden.
  const issues = user.is_admin || user.is_manager || user.is_owner;
  const checkPage = issues
    ? await fetchApi<{ show: boolean | null }>(
        "/v2/certificates/check-page-name",
        { forceProd: true },
      ).catch(() => null)
    : null;
  return (
    <ClientProviders>
      <UserProvider
        user={{
          ...user,
          name_on_check_page: checkPage ? checkPage.show : undefined,
        }}
      >
        <ModeProvider mode={mode}>
          <DashboardShell inbox={inbox}>{children}</DashboardShell>
        </ModeProvider>
      </UserProvider>
    </ClientProviders>
  );
}
