// Server component — root layout for all routes.
// Provides the global design-system base (tokens.css + next/font variables)
// and the MUI baseline — heavy providers (Redux, i18n, charts)
// are loaded only in the stamboken dashboard layout.
import { Source_Serif_4, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { RootThemeProvider } from "./root-theme-provider";
import { CLEAR_HASH_SCRIPT } from "./rapport/clearHash";
import "@/styles/tokens.css";

// Stamboken design-system fonts (ADR-0009), hoisted from (public)/layout.tsx
// and (auth)/layout.tsx so the tokens.css font variables resolve on every
// route (DS-01).
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-source-serif",
  display: "swap",
});

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "https://gotlandskaninen.se",
  ),
  title: "Gotlandskaninen",
  description:
    "Föreningen Gotlandskaninen — digitalt stamregister och information om lantraskaniner",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="sv">
      <head>
        {/* The personal report link's hash is cleared before the app's own code runs; it is the first inline script, and not claimed to precede framework chunks (only on /rapport) */}
        <script dangerouslySetInnerHTML={{ __html: CLEAR_HASH_SCRIPT }} />
        <link rel="icon" href="/static/img/icons/favicon.ico" sizes="any" />
        <link
          rel="icon"
          href="/static/img/icons/favicon-32x32.png"
          type="image/png"
          sizes="32x32"
        />
        <link
          rel="icon"
          href="/static/img/icons/favicon-16x16.png"
          type="image/png"
          sizes="16x16"
        />
        <link
          rel="apple-touch-icon"
          href="/static/img/icons/apple-touch-icon.png"
        />
      </head>
      <body
        className={`${sourceSerif.variable} ${ibmPlexSans.variable} ${ibmPlexMono.variable}`}
        suppressHydrationWarning={true}
      >
        <RootThemeProvider>{children}</RootThemeProvider>
      </body>
    </html>
  );
}
