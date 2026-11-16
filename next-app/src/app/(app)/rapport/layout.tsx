import { ClientProviders } from "../client-providers";
import { CLEAR_HASH_SCRIPT } from "./clearHash";

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
  return (
    <>
      {/* First in the body: it runs while the HTML is parsed, before any application script */}
      <script dangerouslySetInnerHTML={{ __html: CLEAR_HASH_SCRIPT }} />
      <ClientProviders>{children}</ClientProviders>
    </>
  );
}
