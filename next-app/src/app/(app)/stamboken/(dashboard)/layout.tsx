import { cookies } from "next/headers";
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
  return (
    <ClientProviders>
      <UserProvider user={user}>
        <ModeProvider mode={mode}>
          <DashboardShell inbox={inbox}>{children}</DashboardShell>
        </ModeProvider>
      </UserProvider>
    </ClientProviders>
  );
}
