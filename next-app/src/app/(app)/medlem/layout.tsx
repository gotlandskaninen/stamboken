import { cookies } from "next/headers";
import { requireUser } from "@/lib/auth";
import { UserProvider } from "@/lib/user-context";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { ModeProvider } from "@/lib/mode-context";
import { ClientProviders } from "../client-providers";
import { DashboardShell } from "../stamboken/(dashboard)/dashboard-shell";

export default async function MedlemLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await requireUser();
  // DashboardShell's chrome calls useMode() — resolve the mode cookie
  // server-side exactly like stamboken/(dashboard)/layout.tsx does.
  const cookieStore = await cookies();
  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  return (
    <ClientProviders>
      <UserProvider user={user}>
        <ModeProvider mode={mode}>
          <DashboardShell>{children}</DashboardShell>
        </ModeProvider>
      </UserProvider>
    </ClientProviders>
  );
}
