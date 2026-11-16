import { ClientProviders } from "../client-providers";

// The address is a personal link: never indexed, and no Referer leaves the page.
export const metadata = {
  title: "Årsrapport",
  robots: { index: false, follow: false },
  referrer: "no-referrer" as const,
};

export default function RapportLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ClientProviders>{children}</ClientProviders>;
}
